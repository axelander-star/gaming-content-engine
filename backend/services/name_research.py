"""Market data for channel names (channel assistant, 22.11.2026).

Before the assistant proposes a channel name it looks at what is going on in the
topic area instead of only filling a template:

* **Topic words** that come up again and again in the last 30 days: research items
  (RSS/news sources of the topic area), ideas from the idea lab and titles of
  competitor videos (Konkurrenz-Radar). Counted locally, no API call.
* **Competitors** from the Konkurrenz-Radar with the median views of their recent
  videos, so names can stand apart from the strongest channels.
* **Existing YouTube channels** for the topic (official YouTube Data API v3,
  ``search.list`` with ``type=channel`` and ``channels.list`` with
  ``part=statistics``; API key only, no cost). Only with ``YOUTUBE_API_KEY`` and
  ``TREND_SOURCES_MODE=live``; every call is booked against a daily quota in Redis
  first (search: own bucket, 100 calls per day per Google's documentation).

The result feeds the AI prompt (or the template fallback) and is stored on the task,
so the dashboard can show why a name was proposed.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import Language
from models.competitors import Competitor, CompetitorVideo
from models.projects import ContentProject
from models.research import Idea, ResearchItem
from services import quota
from services.sources.base import QuotaExceededError

log = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
#: Google: search.list has its own bucket of 100 calls per day; we stay well below.
SEARCH_DAILY_CALLS = 80
REGION = {Language.DE: "DE", Language.EN: "US"}
WINDOW = timedelta(days=30)

_STOP_WORDS = """
    aber alle allen also auch auf aus beim bereits bitte dann dass dein deine denn diese
    dieser dieses doch durch eine einem einen einer eines etwas euch für gegen geht gibt
    habe haben heute hier ihre immer jetzt kann kein keine mehr mein meine mich mit nach
    neue neuen neuer neues nicht noch nur oder ohne schon sehr sein seine sich sind so
    soll über unter viel vom von warum was weil wenn werden wieder wird wie wir woche
    zum zur zwei jahr jahre about after best been before can does each every first from
    have here into just like made make more most much must never new next only other
    over should some than that their them then there these they this those through today
    under very what when where which while with without will your year years week video
    videos shorts part
"""  # German and English filler words
_STOP = frozenset(_STOP_WORDS.split())
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9]{3,}")


@dataclass
class SimilarChannel:
    title: str
    subscribers: int | None


@dataclass
class MarketContext:
    keywords: list[tuple[str, int]] = field(default_factory=list)  # word, mentions
    competitors: list[tuple[str, int]] = field(default_factory=list)  # name, median views
    similar: list[SimilarChannel] = field(default_factory=list)
    live: bool = False  # existing channels came from the YouTube API
    note: str | None = None  # why the live search was skipped
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def taken_names(self) -> set[str]:
        names = [c.title for c in self.similar] + [n for n, _ in self.competitors]
        return {norm_name(n) for n in names if n}

    def facts(self) -> list[str]:
        """Short German lines for the dashboard ("Datengrundlage")."""
        out: list[str] = []
        if self.keywords:
            words = ", ".join(f"{w} ({n}×)" for w, n in self.keywords[:6])
            out.append(f"Häufige Begriffe der letzten 30 Tage: {words}")
        if self.competitors:
            top = ", ".join(f"{n} (Ø {_views(v)} Aufrufe)" for n, v in self.competitors[:3])
            out.append(f"Stärkste Konkurrenz im Radar: {top}")
        if self.similar:
            top = ", ".join(f"{c.title} ({_subs(c.subscribers)})" for c in self.similar[:5])
            out.append(f"Ähnliche Kanäle auf YouTube: {top}")
        if not self.keywords and not self.competitors:
            out.append(
                "Noch keine Daten zum Thema: Quellen im Themenbereich oder Konkurrenten im "
                "Konkurrenz-Radar eintragen, dann werden die Vorschläge genauer."
            )
        if self.note:
            out.append(self.note)
        return out

    def prompt_block(self) -> str:
        lines = []
        if self.keywords:
            lines.append(
                "Frequent topic words (last 30 days): "
                + ", ".join(f"{w} ({n})" for w, n in self.keywords[:10])
            )
        if self.competitors:
            lines.append(
                "Strongest competitor channels (median views): "
                + ", ".join(f"{n} ({v})" for n, v in self.competitors[:5])
            )
        if self.similar:
            lines.append(
                "Existing YouTube channels for this topic (do not copy or imitate): "
                + ", ".join(
                    f"{c.title} ({c.subscribers if c.subscribers is not None else '?'} subs)"
                    for c in self.similar[:10]
                )
            )
        return "\n".join(lines) or "No market data yet."

    def to_json(self) -> dict[str, Any]:
        return {
            "facts": self.facts(),
            "keywords": [w for w, _ in self.keywords[:10]],
            "live": self.live,
            "collected_at": self.collected_at.isoformat(),
        }


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]", "", name.lower())


def _views(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _subs(n: int | None) -> str:
    return "Abos verborgen" if n is None else f"{_views(n)} Abos"


def keywords(texts: list[str], project: ContentProject, limit: int = 10) -> list[tuple[str, int]]:
    """Most frequent meaningful words; the topic name itself is left out."""
    own = {w.lower() for w in _WORD.findall(project.name)}
    counts: Counter[str] = Counter()
    shown: dict[str, str] = {}
    for text in texts:
        seen: set[str] = set()
        for word in _WORD.findall(text):
            key = word.lower()
            if key in _STOP or key in own or key.isdigit() or key in seen:
                continue
            seen.add(key)  # one count per title
            counts[key] += 1
            shown.setdefault(key, word if word[0].isupper() else word.capitalize())
    return [(shown[k], n) for k, n in counts.most_common(limit) if n >= 2]


def _local(session: Session, project: ContentProject, now: datetime) -> MarketContext:
    since = now - WINDOW
    titles = list(
        session.scalars(
            select(ResearchItem.title)
            .where(ResearchItem.content_project_id == project.id, ResearchItem.fetched_at >= since)
            .order_by(ResearchItem.fetched_at.desc())
            .limit(300)
        )
    )
    titles += list(
        session.scalars(
            select(Idea.title)
            .where(Idea.content_project_id == project.id, Idea.created_at >= since)
            .order_by(Idea.score.desc())
            .limit(100)
        )
    )
    rows = session.execute(
        select(Competitor.name, Competitor.handle, CompetitorVideo.title, CompetitorVideo.views)
        .join(CompetitorVideo, CompetitorVideo.competitor_id == Competitor.id)
        .where(
            Competitor.content_project_id == project.id,
            Competitor.active.is_(True),
            CompetitorVideo.seen_at >= since,
        )
    ).all()
    views: dict[str, list[int]] = {}
    for name, handle, title, n in rows:
        titles.append(title)
        views.setdefault(name or handle, []).append(int(n or 0))
    competitors = sorted(
        ((name, int(statistics.median(v))) for name, v in views.items() if v),
        key=lambda x: x[1],
        reverse=True,
    )
    return MarketContext(keywords=keywords(titles, project), competitors=competitors[:5])


def _youtube(
    settings: Settings,
    project: ContentProject,
    language: Language,
    redis: Redis | None,
    client: httpx.Client | None,
) -> tuple[list[SimilarChannel], str | None]:
    key = settings.youtube_api_key.get_secret_value()
    if not key or settings.trend_sources_mode != "live":
        return [], (
            "Live-Suche auf YouTube aus (YOUTUBE_API_KEY und TREND_SOURCES_MODE=live nötig)."
        )
    if redis is None:
        return [], None
    own = client is None
    http = client or httpx.Client(timeout=settings.http_timeout_s)
    try:
        quota.consume(redis, "youtube_search", 1, SEARCH_DAILY_CALLS)
        res = http.get(
            YOUTUBE_SEARCH_URL,
            params={
                "part": "snippet",
                "type": "channel",
                "q": project.name,
                "maxResults": 10,
                "regionCode": REGION[language],
                "relevanceLanguage": language.value,
                "key": key,
            },
        )
        res.raise_for_status()
        found: dict[str, str] = {}
        for item in res.json().get("items", []):
            cid = (item.get("id") or {}).get("channelId")
            title = (item.get("snippet") or {}).get("channelTitle") or ""
            if cid and title:
                found[cid] = title
        if not found:
            return [], None
        quota.consume(redis, "youtube", 1, settings.youtube_daily_quota_units)
        stats = http.get(
            YOUTUBE_CHANNELS_URL,
            params={"part": "statistics", "id": ",".join(found), "key": key},
        )
        stats.raise_for_status()
        subs: dict[str, int | None] = {}
        for item in stats.json().get("items", []):
            st = item.get("statistics") or {}
            hidden = bool(st.get("hiddenSubscriberCount"))
            raw = st.get("subscriberCount")
            subs[item.get("id", "")] = None if hidden or raw is None else int(raw)
        channels = [SimilarChannel(title, subs.get(cid)) for cid, title in found.items()]
        channels.sort(key=lambda c: c.subscribers or 0, reverse=True)
        return channels, None
    except QuotaExceededError:
        return [], "YouTube-Suche für heute aufgebraucht, morgen wieder."
    except RedisError:
        return [], "YouTube-Suche übersprungen (Kontingentzähler nicht erreichbar)."
    except (httpx.HTTPError, ValueError) as exc:
        # never log the URL: it contains the API key
        log.info("youtube channel search failed (%s)", type(exc).__name__)
        return [], "YouTube-Suche gerade nicht erreichbar."
    finally:
        if own:
            http.close()


def collect(
    session: Session,
    settings: Settings,
    project: ContentProject,
    language: Language,
    *,
    redis: Redis | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> MarketContext:
    ctx = _local(session, project, now or datetime.now(UTC))
    ctx.similar, ctx.note = _youtube(settings, project, language, redis, client)
    ctx.live = bool(ctx.similar)
    return ctx
