"""Publishing strategy (Phase 11, Agent 14): how much, what and when, per channel.

There is no fixed publishing amount. Every channel gets its own decision from

* performance: each post is compared with the channel's own baseline at the
  *same* measurement window (median of earlier posts after 24 h, 48 h or 7 days);
  a post is not judged on its first hours,
* quality of the videos waiting for publication and its recent trend,
* supply: how many approved videos are waiting and how many arrive per day,
* rules: the channel's safety bounds (``min_posts_per_day`` /
  ``max_posts_per_day``), the minimum interval between posts and the posting
  window of the day.

Changes are damped: at most one post per day up or down per daily decision, an
increase needs most recent posts above the baseline (one viral video is not
enough), and nothing changes while there is too little data. Every decision is
stored as a :class:`~models.publishing.StrategyVersion` with reasons and inputs so
it can be rolled back.

The decision logic is pure (plain data in, plain data out) and covered by
simulation tests; :func:`load_history` reads the data from the database.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import Language, MetricWindow, VideoStatus
from models.analytics import Metric
from models.channels import Channel
from models.production import Clip, GameplayFile, QualityCheck, Scene, Variant
from models.publishing import Post, StrategyVersion
from models.trends import Game

#: Windows mature enough to judge a post, most informative first.
MATURE_WINDOWS = (MetricWindow.D7, MetricWindow.H48, MetricWindow.H24)
#: Earlier posts needed at a window before it is used as a baseline.
MIN_BASELINE_POSTS = 5
#: Recent judged posts that decide about more or less.
RECENT_POSTS = 6
BASELINE_POSTS = 30
UP_RATIO = 1.2  # recent median this much above the baseline -> more
DOWN_RATIO = 0.8  # recent median this much below -> less
SUPPORT_SHARE = 0.6  # share of recent posts that must be above the baseline to increase
VIRAL_RATIO = 3.0  # one post this far above the baseline is an outlier, not a trend
REACH_WEIGHT = 0.6  # share of views in a post's score; the rest is engagement/retention
REL_CAP = 5.0  # relative values are capped so one viral post cannot dominate a mean
MAX_STEP = 1  # posts per day the amount may change per daily decision
#: Days after a change before the next increase, so the new amount is measured first.
HOLD_DAYS = 3
QUALITY_DROP = 0.1  # drop of the mean quality score that reduces the amount
GROUP_MIN_POSTS = 3  # posts of a game/format/hook needed before it gets a bonus
CROWD_RATIO = 2.0  # a post this strong in its first day is not crowded out

#: Default posting window (local hours) until the channel's own data says better.
DEFAULT_WINDOW = (11, 21)
TIMEZONES = {Language.DE: "Europe/Berlin", Language.EN: "America/New_York"}


# --- data -------------------------------------------------------------------------


@dataclass(frozen=True)
class PostPerf:
    """Metrics of one post as far as the platform delivered them."""

    post_id: int
    published_at: datetime
    #: window -> values (views, engagement, retention); missing keys = not delivered
    windows: dict[MetricWindow, dict[str, float]]
    game: str | None = None
    video_format: str | None = None
    hook_type: str | None = None


@dataclass(frozen=True)
class Judged:
    post_id: int
    window: MetricWindow
    score: float  # relative to the baseline at that window, 1.0 = typical
    parts: dict[str, float]


@dataclass
class Assessment:
    judged: list[Judged]
    baselines: dict[str, dict[str, float]]  # window -> metric -> median
    waiting: int  # posts too young to judge
    recent: list[float]  # scores of the most recent judged posts
    recent_median: float | None
    above_share: float | None
    best_recent: float | None

    @property
    def enough_data(self) -> bool:
        return len(self.recent) >= min(RECENT_POSTS, MIN_BASELINE_POSTS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "judged": len(self.judged),
            "waiting": self.waiting,
            "baselines": self.baselines,
            "recent": [round(x, 2) for x in self.recent],
            "recent_median": _r(self.recent_median),
            "above_share": _r(self.above_share),
            "best_recent": _r(self.best_recent),
        }


@dataclass(frozen=True)
class Supply:
    ready: int  # approved videos waiting for this channel
    approved_per_day: float  # over the last 7 days
    quality_recent: float | None  # mean quality score, last 7 days
    quality_before: float | None  # mean quality score, the 21 days before

    def as_dict(self) -> dict[str, Any]:
        return {k: _r(v) if isinstance(v, float) else v for k, v in asdict(self).items()}


@dataclass(frozen=True)
class Bounds:
    min_posts: int
    max_posts: int
    interval_minutes: int
    window: tuple[int, int] = DEFAULT_WINDOW
    paused: bool = False

    @property
    def interval_cap(self) -> int:
        """Posts that fit into the posting window with the minimum interval."""
        minutes = (self.window[1] - self.window[0]) * 60
        if self.interval_minutes <= 0:
            return self.max_posts
        return minutes // self.interval_minutes + 1

    @property
    def upper(self) -> int:
        return max(0, min(self.max_posts, self.interval_cap))


@dataclass
class Decision:
    posts_per_day: int
    change: int
    reasons: list[str] = field(default_factory=list)
    #: Channel paused or not configured: the next active day starts fresh.
    inactive: bool = False


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


# --- assessment -------------------------------------------------------------------


def _engagement(values: dict[str, float]) -> float | None:
    views = values.get("views")
    actions = [values[k] for k in ("likes", "comments", "shares", "saves") if k in values]
    if not views or not actions:
        return None
    return sum(actions) / views


def _metrics(values: dict[str, float]) -> dict[str, float]:
    out = {}
    if values.get("views") is not None:
        out["views"] = float(values["views"])
    eng = _engagement(values)
    if eng is not None:
        out["engagement"] = eng
    for key in ("retention", "completion"):
        if values.get(key) is not None:
            out[key] = float(values[key])
    return out


def assess(posts: Sequence[PostPerf]) -> Assessment:
    """Score every post against the channel baseline at the same window.

    Posts are processed oldest first; the baseline for a post only uses posts
    published before it, so the history is judged the way it happened.
    """
    ordered = sorted(posts, key=lambda p: p.published_at)
    judged: list[Judged] = []
    waiting = 0
    history: dict[MetricWindow, list[dict[str, float]]] = {w: [] for w in MATURE_WINDOWS}
    for post in ordered:
        result: Judged | None = None
        for window in MATURE_WINDOWS:
            values = post.windows.get(window)
            if not values:
                continue
            earlier = history[window][-BASELINE_POSTS:]
            if result is None and len(earlier) >= MIN_BASELINE_POSTS:
                result = _judge(post.post_id, window, _metrics(values), earlier)
        for window in MATURE_WINDOWS:
            if post.windows.get(window):
                history[window].append(_metrics(post.windows[window]))
        if result is not None:
            judged.append(result)
        elif not any(post.windows.get(w) for w in MATURE_WINDOWS):
            waiting += 1
    baselines = {
        w.value: _medians(rows[-BASELINE_POSTS:])
        for w, rows in history.items()
        if len(rows) >= MIN_BASELINE_POSTS
    }
    recent = [j.score for j in judged[-RECENT_POSTS:]]
    return Assessment(
        judged=judged,
        baselines=baselines,
        waiting=waiting,
        recent=recent,
        recent_median=statistics.median(recent) if recent else None,
        above_share=sum(1 for s in recent if s >= 1.0) / len(recent) if recent else None,
        best_recent=max(recent) if recent else None,
    )


def _medians(rows: Iterable[dict[str, float]]) -> dict[str, float]:
    keys: dict[str, list[float]] = {}
    for row in rows:
        for k, v in row.items():
            keys.setdefault(k, []).append(v)
    return {k: round(statistics.median(v), 4) for k, v in keys.items() if v}


def _judge(
    post_id: int, window: MetricWindow, values: dict[str, float], earlier: list[dict[str, float]]
) -> Judged | None:
    base = _medians(earlier)
    parts = {}
    for key, value in values.items():
        b = base.get(key)
        if b:
            parts[key] = min(REL_CAP, value / b)
    if "views" not in parts:
        return None
    # views tell the reach, the others how well the video holds and activates viewers
    others = [v for k, v in parts.items() if k != "views"]
    score = (
        REACH_WEIGHT * parts["views"] + (1 - REACH_WEIGHT) * statistics.mean(others)
        if others
        else parts["views"]
    )
    return Judged(post_id, window, round(score, 3), {k: round(v, 3) for k, v in parts.items()})


# --- amount -----------------------------------------------------------------------


def decide_amount(
    previous: int | None,
    assessment: Assessment,
    supply: Supply,
    bounds: Bounds,
    days_since_change: int | None = None,
) -> Decision:
    """Posts per day for the next day. Damped, bounded and explained."""
    reasons: list[str] = []
    if bounds.paused:
        return Decision(0, -(previous or 0), ["Kanal ist pausiert"], inactive=True)
    if bounds.max_posts <= 0:
        return Decision(
            0, -(previous or 0), ["Höchstgrenze des Kanals ist 0 (nicht eingerichtet)"], True
        )

    if previous is None:
        base = max(bounds.min_posts, 1)
        reasons.append(f"Erste Strategie: vorsichtiger Start mit {base} pro Tag")
    else:
        base = previous
    target = base

    if previous is None:
        pass  # the first version only starts; changes need a measured amount first
    elif not assessment.enough_data:
        reasons.append(
            f"Zu wenig ausgewertete Videos ({len(assessment.recent)} von "
            f"{min(RECENT_POSTS, MIN_BASELINE_POSTS)} nötig, {assessment.waiting} noch zu jung)"
            " – keine Änderung"
        )
    else:
        med, share = assessment.recent_median or 0.0, assessment.above_share or 0.0
        best = assessment.best_recent or 0.0
        if med >= UP_RATIO and share >= SUPPORT_SHARE:
            target = base + 1
            reasons.append(
                f"Letzte Videos im Median {med:.2f}× über dem Kanalschnitt, "
                f"{share:.0%} darüber – mehr veröffentlichen"
            )
        elif med <= DOWN_RATIO:
            target = base - 1
            reasons.append(f"Letzte Videos im Median nur {med:.2f}× des Kanalschnitts – weniger")
        elif best >= VIRAL_RATIO:
            reasons.append(
                f"Einzelner Ausreißer ({best:.1f}×), aber nur {share:.0%} der letzten Videos über "
                "dem Schnitt – keine Erhöhung"
            )
        else:
            reasons.append(f"Leistung im üblichen Bereich (Median {med:.2f}×) – Menge bleibt")

    if (
        supply.quality_recent is not None
        and supply.quality_before is not None
        and supply.quality_before - supply.quality_recent >= QUALITY_DROP
    ):
        target = min(target, base - 1)
        reasons.append(
            f"Qualität gesunken ({supply.quality_before:.2f} → "
            f"{supply.quality_recent:.2f}) – weniger"
        )
    if target > base and days_since_change is not None and days_since_change < HOLD_DAYS:
        target = base
        reasons.append(
            f"Letzte Änderung vor {days_since_change} Tag(en) – erst messen, dann weiter erhöhen"
        )
    if target > base and supply.ready + supply.approved_per_day < target:
        target = base
        reasons.append(
            f"Nur {supply.ready} Videos bereit und {supply.approved_per_day:.1f} neue pro Tag – "
            "keine Erhöhung"
        )

    target = max(base - MAX_STEP, min(base + MAX_STEP, target))
    upper = bounds.upper
    # an active channel keeps at least one post a day; otherwise no new data could
    # ever show that it works again. Stopping a channel is the operator's pause.
    lower = min(max(bounds.min_posts, 1), upper)
    if target > upper:
        reasons.append(
            f"Begrenzt auf {upper} (Höchstgrenze {bounds.max_posts}, "
            f"Mindestabstand {bounds.interval_minutes} min)"
        )
    if target < lower:
        reasons.append(f"Mindestens {lower} pro Tag, solange der Kanal aktiv ist")
    target = max(lower, min(upper, target))
    return Decision(target, target - (previous if previous is not None else target), reasons)


# --- selection and timing ---------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    variant_id: int
    clip_id: int
    quality: float
    ready_since: datetime
    game: str | None = None
    video_format: str | None = None
    hook_type: str | None = None
    experiment: bool = False


def group_scores(posts: Sequence[PostPerf], assessment: Assessment) -> dict[str, dict[str, float]]:
    """Mean relative score per game, format and hook (only with enough posts)."""
    by_id = {j.post_id: j.score for j in assessment.judged}
    groups: dict[str, dict[str, list[float]]] = {"game": {}, "format": {}, "hook": {}}
    for p in posts:
        score = by_id.get(p.post_id)
        if score is None:
            continue
        for kind, key in (("game", p.game), ("format", p.video_format), ("hook", p.hook_type)):
            if key:
                groups[kind].setdefault(key, []).append(score)
    return {
        kind: {
            k: round(statistics.mean(v), 3) for k, v in rows.items() if len(v) >= GROUP_MIN_POSTS
        }
        for kind, rows in groups.items()
    }


def priority(c: Candidate, groups: dict[str, dict[str, float]]) -> tuple[float, list[str]]:
    """Quality first; proven games, formats and hooks get a bonus, weak ones a malus."""
    value, notes = c.quality, []
    for kind, key in (("game", c.game), ("format", c.video_format), ("hook", c.hook_type)):
        rel = groups.get(kind, {}).get(key or "")
        if rel is None:
            continue
        bonus = max(-0.15, min(0.15, (rel - 1.0) * 0.15))
        value += bonus
        if abs(bonus) >= 0.03:
            notes.append(f"{kind} {key} {rel:.2f}×")
    return round(value, 3), notes


def choose(
    candidates: Sequence[Candidate], slots: int, groups: dict[str, dict[str, float]]
) -> list[Candidate]:
    """Best candidates, one variant per clip, at least one test variant on bigger days."""
    if slots <= 0:
        return []
    ranked = sorted(candidates, key=lambda c: (-priority(c, groups)[0], c.ready_since))
    chosen: list[Candidate] = []
    clips: set[int] = set()
    for c in ranked:
        if c.clip_id in clips:
            continue
        chosen.append(c)
        clips.add(c.clip_id)
        if len(chosen) == slots:
            break
    if slots >= 2 and chosen and not any(c.experiment for c in chosen):
        test = next((c for c in ranked if c.experiment and c.clip_id not in clips), None)
        if test is not None:
            if len(chosen) == slots:
                chosen[-1] = test
            else:
                chosen.append(test)
    return chosen


def best_hours(posts: Sequence[PostPerf], assessment: Assessment, tz: ZoneInfo) -> list[int] | None:
    """Local hours sorted by the mean score of posts published then (enough data only)."""
    by_id = {j.post_id: j.score for j in assessment.judged}
    hours: dict[int, list[float]] = {}
    for p in posts:
        if p.post_id in by_id:
            hours.setdefault(p.published_at.astimezone(tz).hour, []).append(by_id[p.post_id])
    rated = {h: statistics.mean(v) for h, v in hours.items() if len(v) >= 2}
    if len(rated) < 2:
        return None
    return sorted(rated, key=lambda h: -rated[h])


def slot_times(
    day: date,
    count: int,
    bounds: Bounds,
    tz: ZoneInfo,
    now: datetime,
    taken: Sequence[datetime],
    preferred: Sequence[int] | None = None,
) -> list[datetime]:
    """Posting times for ``day``: inside the window, after ``now``, apart by the interval."""
    if count <= 0:
        return []
    start = datetime.combine(day, time(bounds.window[0]), tz)
    end = datetime.combine(day, time(bounds.window[1]), tz)
    earliest = max(start, (now + timedelta(minutes=15)).astimezone(tz))
    gap = timedelta(minutes=max(bounds.interval_minutes, 1))
    if earliest > end:
        return []
    # candidate grid every 15 minutes; preferred hours first, otherwise spread evenly
    grid: list[datetime] = []
    t = earliest.replace(minute=(earliest.minute // 15) * 15, second=0, microsecond=0)
    if t < earliest:
        t += timedelta(minutes=15)
    while t <= end:
        grid.append(t)
        t += timedelta(minutes=15)
    if not grid:
        return []
    if preferred:
        rank = {h: i for i, h in enumerate(preferred)}
        order = sorted(grid, key=lambda x: (rank.get(x.hour, len(rank)), x))
    else:
        step = max(1, len(grid) // count)
        spread = grid[step // 2 :: step]
        order = spread + [g for g in grid if g not in spread]
    chosen: list[datetime] = []
    busy = [x.astimezone(tz) for x in taken]
    for slot in order:
        if all(abs(slot - b) >= gap for b in (*busy, *chosen)):
            chosen.append(slot)
            if len(chosen) == count:
                break
    return sorted(x.astimezone(UTC) for x in chosen)


def timezone_for(channel: Channel) -> ZoneInfo:
    name = (channel.strategy or {}).get("timezone") or TIMEZONES.get(channel.language, "UTC")
    return ZoneInfo(str(name))


def window_for(channel: Channel) -> tuple[int, int]:
    w = (channel.strategy or {}).get("window")
    if isinstance(w, list) and len(w) == 2 and 0 <= int(w[0]) < int(w[1]) <= 24:
        return int(w[0]), int(w[1])
    return DEFAULT_WINDOW


# --- database ---------------------------------------------------------------------

_METRIC_FIELDS = {
    "views": "views",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "saves": "saves",
    "retention_pct": "retention",
    "completion_rate": "completion",
}


def load_history(
    session: Session, channel_id: int, limit: int = 200, include_mock: bool = True
) -> list[PostPerf]:
    """Published posts of the channel with their delivered metrics.

    In live mode test posts (synthetic numbers) are left out, so they never
    influence decisions about real posts."""
    where = [Post.channel_id == channel_id, Post.published_at.is_not(None)]
    if not include_mock:
        where.append(Post.is_mock.is_(False))
    rows = session.execute(
        select(Post, Variant)
        .join(Variant, Variant.id == Post.variant_id)
        .where(*where)
        .order_by(Post.published_at.desc())
        .limit(limit)
    ).all()
    if not rows:
        return []
    metrics: dict[int, dict[MetricWindow, dict[str, float]]] = {}
    for m in session.scalars(select(Metric).where(Metric.post_id.in_([p.id for p, _ in rows]))):
        values = {
            name: float(getattr(m, col))
            for col, name in _METRIC_FIELDS.items()
            if getattr(m, col) is not None
        }
        if values:
            metrics.setdefault(m.post_id, {})[m.measure_window] = values
    games = games_for_clips(session, [v.clip_id for _, v in rows])
    out = []
    for post, variant in rows:
        assert post.published_at is not None
        out.append(
            PostPerf(
                post_id=post.id,
                published_at=post.published_at,
                windows=metrics.get(post.id, {}),
                game=games.get(variant.clip_id),
                video_format=variant.video_format,
                hook_type=variant.hook_type,
            )
        )
    return out


def games_for_clips(session: Session, clip_ids: list[int]) -> dict[int, str]:
    rows = session.execute(
        select(Clip.id, Game.name)
        .join(Scene, Scene.id == Clip.scene_id)
        .join(GameplayFile, GameplayFile.id == Scene.gameplay_file_id)
        .join(Game, Game.id == GameplayFile.game_id)
        .where(Clip.id.in_(clip_ids))
    ).all()
    return {cid: name for cid, name in rows}


def load_supply(session: Session, channel_id: int, now: datetime) -> Supply:
    ready_n = int(
        session.scalar(
            select(func.count(Variant.id)).where(
                Variant.channel_id == channel_id,
                Variant.status == VideoStatus.READY_TO_PUBLISH,
            )
        )
        or 0
    )
    rows = session.execute(
        select(QualityCheck.checked_at, QualityCheck.score, QualityCheck.passed)
        .join(Variant, Variant.id == QualityCheck.variant_id)
        .where(
            Variant.channel_id == channel_id, QualityCheck.checked_at >= now - timedelta(days=28)
        )
    ).all()
    week = now - timedelta(days=7)
    recent = [s for at, s, _ in rows if at >= week and s is not None]
    before = [s for at, s, _ in rows if at < week and s is not None]
    approved = sum(1 for at, _, ok in rows if at >= week and ok)
    return Supply(
        ready=ready_n,
        approved_per_day=round(approved / 7, 2),
        quality_recent=statistics.mean(recent) if len(recent) >= 3 else None,
        quality_before=statistics.mean(before) if len(before) >= 3 else None,
    )


def days_since_change(session: Session, channel_id: int, today: date) -> int | None:
    """Days since the amount last changed (None = never changed)."""
    rows = session.execute(
        select(StrategyVersion.planned_for, StrategyVersion.posts_per_day)
        .where(StrategyVersion.channel_id == channel_id)
        .order_by(StrategyVersion.version.desc())
        .limit(60)
    ).all()
    for (day, amount), (_, before) in itertools.pairwise(rows):
        if amount != before:
            return (today - day).days
    return None


def latest_version(session: Session, channel_id: int) -> StrategyVersion | None:
    return session.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.channel_id == channel_id)
        .order_by(StrategyVersion.version.desc())
        .limit(1)
    )


def rollback(session: Session, channel: Channel, version: int, actor: str) -> StrategyVersion:
    """Restore an earlier version as a new one; it applies for the rest of the day."""
    old = session.scalar(
        select(StrategyVersion).where(
            StrategyVersion.channel_id == channel.id, StrategyVersion.version == version
        )
    )
    if old is None:
        raise LookupError(f"version {version} not found")
    latest = latest_version(session, channel.id)
    assert latest is not None
    today = datetime.now(UTC).astimezone(timezone_for(channel)).date()
    restored = StrategyVersion(
        channel_id=channel.id,
        version=latest.version + 1,
        planned_for=max(today, latest.planned_for),
        posts_per_day=old.posts_per_day,
        params=dict(old.params or {}),
        reasons=[f"Zurückgesetzt auf Version {old.version} (vorher Version {latest.version})"],
        inputs={"rolled_back_from": latest.version},
        created_by=actor,
        rolled_back_to=old.version,
    )
    session.add(restored)
    session.flush()
    return restored
