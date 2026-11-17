"""Which topic area fits a campaign, and what would it earn there? (Ausbau A8)

Content Rewards has no API for clippers and its terms forbid scraping, so the
engine does not fetch campaigns. The operator pastes what the campaign page
says (name, brief, game, platforms, languages, CPM); this module ranks the
topic areas:

* **topic** (up to 50 points): words of the brief and the game against name,
  sub-topics, description and audience of the area; a known game name counts
  for gaming areas;
* **languages** and **platforms** (25 points each): share of what the campaign
  asks for that the area has active channels for;
* **earnings**: median views per post of those channels times CPM, after the
  platform fee and cap (same formula as :func:`services.campaigns.estimated_payout`).

The result is a suggestion; the operator picks the area when saving the campaign.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import ContentProjectStatus
from models.analytics import Metric
from models.campaigns import Campaign
from models.channels import Channel
from models.projects import ContentProject
from models.publishing import Post
from models.trends import Game
from services import campaigns

STOP = {
    "und", "oder", "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen",
    "mit", "für", "von", "auf", "aus", "bei", "nicht", "nur", "the", "and", "for",
    "with", "your", "you", "from", "this", "that", "clips", "clip", "videos", "video",
    "content", "campaign", "kampagne", "views", "post", "posts", "short", "shorts",
}  # fmt: skip
GAMING_WORDS = {"gaming", "game", "games", "spiel", "spiele", "gamer", "esport", "esports"}
RECENT_POSTS = 30


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]{3,}", text.lower()) if w not in STOP}


@dataclass
class Fit:
    project_id: int
    project: str
    score: int
    reasons: list[str] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    median_views: int | None = None
    usd_per_clip: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def median_views(session: Session, channel_ids: list[int]) -> int | None:
    """Median of the best measured views of the channels' recent posts."""
    if not channel_ids:
        return None
    best = (
        select(Post.id, func.max(Metric.views).label("views"))
        .join(Metric, Metric.post_id == Post.id)
        .where(Post.channel_id.in_(channel_ids), Metric.views.is_not(None))
        .group_by(Post.id)
        .order_by(Post.id.desc())
        .limit(RECENT_POSTS * len(channel_ids))
    )
    values = [int(v) for _, v in session.execute(best).all() if v is not None]
    return int(statistics.median(values)) if values else None


def rank(session: Session, data: dict[str, Any]) -> list[Fit]:
    text = " ".join(str(data.get(k) or "") for k in ("name", "brief", "game"))
    brief_words = words(text)
    low = text.lower()
    known_game = next(
        (
            g
            for g in session.scalars(select(Game.name).where(Game.is_test_data.is_(False)))
            if len(g) >= 3 and g.lower() in low
        ),
        None,
    ) or (str(data.get("game") or "").strip() or None)
    languages = [str(x) for x in data.get("languages") or []]
    platforms = [str(x) for x in data.get("platforms") or []]
    probe = Campaign(
        name="probe", url="", cpm_usd=data.get("cpm_usd"), min_views=data.get("min_views"),
        max_payout_per_clip_usd=data.get("max_payout_per_clip_usd"),
    )  # fmt: skip
    out = []
    projects = session.scalars(
        select(ContentProject)
        .where(ContentProject.status == ContentProjectStatus.ACTIVE)
        .order_by(ContentProject.priority, ContentProject.id)
    )
    for project in projects:
        area = words(
            " ".join(
                [project.name, project.slug.replace("-", " "), project.description or "",
                 project.audience or "", " ".join(str(s) for s in project.subtopics or [])]
            )
        )  # fmt: skip
        fit = Fit(project.id, project.name, 0)
        hits = sorted(brief_words & area)
        topic = min(50, 15 * len(hits))
        if hits:
            fit.reasons.append("passt zum Thema: " + ", ".join(hits[:5]))
        if known_game and area & GAMING_WORDS:
            topic = max(topic, 40)
            fit.reasons.append(f"Spiel „{known_game}“ passt zum Gaming-Bereich")
        channels = [
            c
            for c in session.scalars(
                select(Channel).where(Channel.content_project_id == project.id).order_by(Channel.id)
            )
            if (not platforms or c.platform.code.value in platforms)
            and (not languages or c.language.value in languages)
        ]
        have_lang = {c.language.value for c in channels}
        have_plat = {c.platform.code.value for c in channels}
        lang_part = 25 * (len(have_lang) / len(languages)) if languages else (25 if channels else 0)
        plat_part = 25 * (len(have_plat) / len(platforms)) if platforms else (25 if channels else 0)
        if channels:
            fit.reasons.append(
                f"{len(channels)} passende Kanäle ({', '.join(sorted(have_plat))}; "
                f"{', '.join(sorted(have_lang))})"
            )
            paused = sum(1 for c in channels if c.is_paused)
            if paused:
                fit.reasons.append(f"davon {paused} pausiert: vor dem Start einschalten")
        else:
            fit.reasons.append("keine Kanäle für diese Plattformen und Sprachen")
        fit.score = round(topic + lang_part + plat_part)
        fit.channels = [
            {"id": c.id, "name": c.name, "platform": c.platform.code.value,
             "language": c.language.value}
            for c in channels
        ]  # fmt: skip
        fit.median_views = median_views(session, [c.id for c in channels])
        if fit.median_views is not None and probe.cpm_usd is not None:
            probe.cpm_usd = Decimal(str(probe.cpm_usd))
            if probe.max_payout_per_clip_usd is not None:
                probe.max_payout_per_clip_usd = Decimal(str(probe.max_payout_per_clip_usd))
            payout = campaigns.estimated_payout(probe, fit.median_views)
            fit.usd_per_clip = float(payout) if payout is not None else None
        out.append(fit)
    return sorted(out, key=lambda f: (-f.score, -(f.usd_per_clip or 0), f.project_id))


def for_campaign(session: Session, campaign: Campaign) -> list[Fit]:
    return rank(
        session,
        {
            "name": campaign.name, "brief": campaign.brief, "game": None,
            "languages": campaign.languages, "platforms": campaign.platforms,
            "cpm_usd": campaign.cpm_usd, "min_views": campaign.min_views,
            "max_payout_per_clip_usd": campaign.max_payout_per_clip_usd,
        },
    )  # fmt: skip
