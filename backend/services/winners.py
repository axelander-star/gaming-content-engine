"""Hook A/B tests and winner recycling (Ausbau A7).

Every post is judged against its own channel at the same age
(:func:`services.strategy.assess`, 1.0 = typical for the channel). On top of that:

* **Hook test:** the Creative Director makes variants of one clip with different
  hooks (A, B, …). When two or more of them ran on the *same* channel, their scores
  are compared. A hook wins when it is at least ``WIN_MARGIN`` better; otherwise it
  is a draw. :func:`balance` counts wins per hook type, which the dashboard shows
  and the recycling uses to choose the next hook.
* **Winner:** a post that did at least ``WINNER_SCORE`` times as well as usual.
  Once it is ``RECYCLE_AFTER_DAYS`` old (and at most ``RECYCLE_MAX_DAYS``), the
  Winner Recycling agent

  - plans the same clip again with a *different* hook (a new variant ``R1`` that
    runs through script, voice, subtitles and quality check like any variant;
    the Publishing Strategy Agent decides if and when it goes out), and
  - puts an idea "Teil 2" into the idea lab, so a follow-up can be made.

  Each winner is recycled once. Library videos (no clip) only get the idea.
Nothing is published here and no paid service is called.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import IdeaStatus, NotificationLevel, VideoStatus
from models.channels import Channel
from models.production import Clip, Variant
from models.publishing import Post
from models.research import Idea
from services import creative, notify, strategy, workflow

ACTOR = "winner_recycling"
WIN_MARGIN = 1.15
WINNER_SCORE = 2.0
RECYCLE_AFTER_DAYS = 7
RECYCLE_MAX_DAYS = 60
MAX_PER_RUN = 5


@dataclass
class Entry:
    variant_id: int
    post_id: int
    label: str
    hook_type: str | None
    score: float
    title: str | None


@dataclass
class HookTest:
    channel_id: int
    channel: str
    clip_id: int
    entries: list[Entry]
    winner: Entry | None  # None = draw

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "channel": self.channel,
            "clip_id": self.clip_id,
            "entries": [e.__dict__ for e in self.entries],
            "winner_variant_id": self.winner.variant_id if self.winner else None,
            "winner_hook": self.winner.hook_type if self.winner else None,
        }


@dataclass
class Scored:
    post: Post
    variant: Variant
    channel: Channel
    score: float


def scored_posts(
    session: Session, channel_ids: list[int] | None = None, include_mock: bool = True
) -> list[Scored]:
    """Every judged post with its score relative to its channel."""
    q = select(Channel).order_by(Channel.id)
    if channel_ids is not None:
        q = q.where(Channel.id.in_(channel_ids))
    out: list[Scored] = []
    for channel in session.scalars(q):
        history = strategy.load_history(session, channel.id, include_mock=include_mock)
        if not history:
            continue
        scores = {j.post_id: j.score for j in strategy.assess(history).judged}
        if not scores:
            continue
        rows = session.execute(
            select(Post, Variant)
            .join(Variant, Variant.id == Post.variant_id)
            .where(Post.id.in_(list(scores)))
        ).all()
        out += [Scored(p, v, channel, scores[p.id]) for p, v in rows]
    return out


def hook_tests(scored: list[Scored]) -> list[HookTest]:
    groups: dict[tuple[int, int], list[Scored]] = defaultdict(list)
    for s in scored:
        if s.variant.clip_id is not None:
            groups[(s.channel.id, s.variant.clip_id)].append(s)
    tests = []
    for (channel_id, clip_id), rows in groups.items():
        # one entry per variant label (the best post of it), at least two hooks
        best: dict[str, Scored] = {}
        for r in rows:
            if r.variant.variant_label not in best or r.score > best[r.variant.variant_label].score:
                best[r.variant.variant_label] = r
        if len(best) < 2:
            continue
        entries = sorted(
            (
                Entry(r.variant.id, r.post.id, label, r.variant.hook_type, r.score, r.variant.title)
                for label, r in best.items()
            ),
            key=lambda e: -e.score,
        )
        top, second = entries[0], entries[1]
        winner = top if top.score >= second.score * WIN_MARGIN else None
        tests.append(HookTest(channel_id, rows[0].channel.name, clip_id, entries, winner))
    return sorted(tests, key=lambda t: (t.channel_id, -t.clip_id))


@dataclass
class Balance:
    hook_type: str
    tests: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    scores: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "hook_type": self.hook_type,
            "label": creative.HOOK_LABELS.get(self.hook_type, self.hook_type),
            "tests": self.tests,
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "median_score": round(statistics.median(self.scores), 2) if self.scores else None,
        }


def balance(tests: list[HookTest]) -> list[Balance]:
    out: dict[str, Balance] = {}
    for t in tests:
        for e in t.entries:
            if not e.hook_type:
                continue
            b = out.setdefault(e.hook_type, Balance(e.hook_type))
            b.tests += 1
            b.scores.append(e.score)
            if t.winner is None:
                b.draws += 1
            elif t.winner.variant_id == e.variant_id:
                b.wins += 1
            else:
                b.losses += 1
    return sorted(out.values(), key=lambda b: (-b.wins, b.losses, b.hook_type))


def next_hook(current: str | None, video_format: str | None, table: list[Balance]) -> str:
    """The hook for a recycled clip: best record in the tests, never the old one."""
    fitting = creative.FORMAT_HOOKS.get(video_format or "", creative.HOOK_TYPES)
    ranked = [b.hook_type for b in table if b.hook_type in fitting and b.wins > b.losses]
    for hook in [*ranked, *fitting, *creative.HOOK_TYPES]:
        if hook != current:
            return hook
    return creative.HOOK_TYPES[0]


def _recycled(session: Session, variant: Variant) -> bool:
    origin = variant.concept.get("recycle_of") if variant.concept else None
    if origin is not None:  # a recycled variant is not recycled again
        return True
    return (
        session.scalar(
            select(Variant.id).where(Variant.concept["recycle_of"].as_integer() == variant.id)
        )
        is not None
    )


def _idea_exists(session: Session, project_id: int, marker: str) -> bool:
    return (
        session.scalar(
            select(Idea.id).where(
                Idea.content_project_id == project_id, Idea.reasoning.contains(marker)
            )
        )
        is not None
    )


def _times(score: float) -> str:
    return f"{score:.1f}".replace(".", ",")


def recycle(session: Session, s: Scored, table: list[Balance]) -> dict[str, Any]:
    """New hook for the clip (if it is one) and an idea "Teil 2"; idempotent."""
    v = s.variant
    title = v.title or f"Beitrag #{s.post.id}"
    out: dict[str, Any] = {"post_id": s.post.id, "variant_id": v.id, "score": s.score}
    if v.clip_id is not None and not _recycled(session, v):
        clip = session.get(Clip, v.clip_id)
        if clip is not None and clip.storage_uri:
            hook = next_hook(v.hook_type, v.video_format, table)
            labels = set(
                session.scalars(
                    select(Variant.variant_label).where(
                        Variant.clip_id == v.clip_id, Variant.channel_id == v.channel_id
                    )
                )
            )
            label = next(f"R{n}" for n in range(1, 99) if f"R{n}" not in labels)
            fresh = Variant(
                clip_id=v.clip_id,
                channel_id=v.channel_id,
                content_project_id=v.content_project_id,
                language=v.language,
                variant_label=label,
                video_format=v.video_format,
                hook_type=hook,
                concept={
                    **{k: x for k, x in (v.concept or {}).items() if k != "crosspost_of"},
                    "hook_type": hook,
                    "recycle_of": v.id,
                    "reason": f"Gewinner ({_times(s.score)}× so gut wie üblich), neuer Hook",
                },
                status=VideoStatus.EDITING,
                storage_uri=clip.storage_uri,
                sha256=clip.sha256,
                fingerprint=clip.fingerprint,
            )
            session.add(fresh)
            session.flush()
            workflow.record_entry(session, fresh, actor=ACTOR)
            out["recycled_variant_id"] = fresh.id
            out["new_hook"] = hook
    marker = f"[winner:{s.post.id}]"
    if not _idea_exists(session, v.content_project_id, marker):
        idea = Idea(
            content_project_id=v.content_project_id,
            title=f"Teil 2: {title}"[:200],
            pitch=(
                f"„{title}“ lief {_times(s.score)}-mal so gut wie sonst auf "
                f"{s.channel.name}. Eine Fortsetzung mit demselben Kern, aber neuem Moment "
                "oder neuer Frage."
            ),
            format="short",
            sources=[{"title": title, "url": s.post.url, "post_id": s.post.id}],
            trend_score=80,
            fit_score=90,
            effort_score=30,
            rights_risk=0 if v.library_item_id else 20,
            score=85,
            reasoning=f"Gewinner-Recycling: eigener Beitrag lief deutlich besser. {marker}",
            status=IdeaStatus.NEW,
            provider="rules",
        )
        session.add(idea)
        session.flush()
        out["idea_id"] = idea.id
    return out


def run(session: Session, now: datetime | None = None, include_mock: bool = True) -> dict[str, Any]:
    """Find winners that are due and recycle them; commits."""
    now = now or datetime.now(UTC)
    scored = scored_posts(session, include_mock=include_mock)
    table = balance(hook_tests(scored))
    due = [
        s for s in scored
        if s.score >= WINNER_SCORE and s.post.published_at is not None
        and now - timedelta(days=RECYCLE_MAX_DAYS)
        <= s.post.published_at
        <= now - timedelta(days=RECYCLE_AFTER_DAYS)
    ]  # fmt: skip
    done = []
    for s in sorted(due, key=lambda x: -x.score)[:MAX_PER_RUN]:
        result = recycle(session, s, table)
        if "recycled_variant_id" in result or "idea_id" in result:
            done.append(result)
            notify.add(
                session,
                f"Gewinner: „{(s.variant.title or '')[:80]}“ lief {_times(s.score)}× so gut",
                (
                    f"Neuer Hook ({creative.HOOK_LABELS.get(result['new_hook'], '')}) eingeplant. "
                    if "new_hook" in result
                    else ""
                )
                + ("Idee „Teil 2“ liegt im Ideenlabor." if "idea_id" in result else ""),
                level=NotificationLevel.INFO,
                kind="winner",
                link="/ideen",
            )
    session.commit()
    return {"winners": len(due), "recycled": done}
