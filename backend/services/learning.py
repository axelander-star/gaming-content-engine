"""Learning from results (PROJECT_SPEC sections 6 and 12, Phase 14).

The Learning Agent looks at all judged posts (score = performance relative to the
own channel at the same age, :func:`services.strategy.assess`) and asks per game,
format and hook: does this group perform clearly and consistently better or
worse than usual?

Rules against learning too early:

* a group needs ``MIN_SAMPLES`` judged posts on at least ``MIN_DAYS`` different
  days; one viral video moves the median, not the decision,
* "clearly": median at least ``UP`` (or at most ``DOWN``) and at least
  ``SUPPORT`` of the posts on the same side,
* the factor is bounded to 0.8–1.2 and changes the ranking, it never blocks.

Controlled testing: a change becomes a ``trial`` version. After ``TRIAL_DAYS`` and
at least ``MIN_TRIAL_POSTS`` judged posts published during the trial, it is
compared with the baseline before the trial; kept if not worse than
``KEEP_RATIO``, otherwise rolled back. Every version is stored; an admin can go
back to any of them.

Consumers: the Publishing Strategy Agent (selection order, where the channel has
no own group numbers yet) and the Creative Director (format choice).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.analytics import LearningVersion
from models.channels import Channel
from services import strategy

KINDS = ("game", "format", "hook")
MIN_SAMPLES = 8
MIN_DAYS = 3
UP = 1.15
DOWN = 0.85
SUPPORT = 0.6
MIN_WEIGHT, MAX_WEIGHT = 0.8, 1.2
CHANGE = 0.05  # smaller differences to the current weights are no new version
TRIAL_DAYS = 7
MIN_TRIAL_POSTS = 6
MAX_TRIAL_DAYS = 21
KEEP_RATIO = 0.95
BASELINE_DAYS = 28

TRIAL, ACTIVE, ROLLED_BACK, SUPERSEDED = "trial", "active", "rolled_back", "superseded"


@dataclass(frozen=True)
class Sample:
    post_id: int
    published_at: datetime
    score: float
    groups: dict[str, str | None]


def collect(session: Session, include_mock: bool) -> list[Sample]:
    """Judged posts of all channels."""
    out: list[Sample] = []
    for channel_id in session.scalars(select(Channel.id)).all():
        posts = strategy.load_history(session, channel_id, include_mock=include_mock)
        if not posts:
            continue
        by_id = {p.post_id: p for p in posts}
        for j in strategy.assess(posts).judged:
            p = by_id[j.post_id]
            out.append(
                Sample(
                    j.post_id,
                    p.published_at,
                    j.score,
                    {"game": p.game, "format": p.video_format, "hook": p.hook_type},
                )
            )
    return out


def group_stats(samples: list[Sample]) -> dict[str, dict[str, dict[str, Any]]]:
    groups: dict[str, dict[str, list[Sample]]] = {k: {} for k in KINDS}
    for s in samples:
        for kind in KINDS:
            key = s.groups.get(kind)
            if key:
                groups[kind].setdefault(key, []).append(s)
    out: dict[str, dict[str, dict[str, Any]]] = {k: {} for k in KINDS}
    for kind, rows in groups.items():
        for key, items in rows.items():
            scores = [i.score for i in items]
            out[kind][key] = {
                "n": len(items),
                "days": len({i.published_at.date() for i in items}),
                "median": round(statistics.median(scores), 3),
                "above": round(sum(1 for x in scores if x > 1.0) / len(scores), 2),
                "below": round(sum(1 for x in scores if x < 1.0) / len(scores), 2),
            }
    return out


def derive(
    stats: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Weights for groups with enough, consistent evidence, plus the reasons."""
    weights: dict[str, dict[str, float]] = {k: {} for k in KINDS}
    reasons: list[str] = []
    labels = {"game": "Spiel", "format": "Format", "hook": "Hook"}
    for kind in KINDS:
        for key, st in sorted(stats.get(kind, {}).items()):
            if st["n"] < MIN_SAMPLES or st["days"] < MIN_DAYS:
                continue
            median = float(st["median"])
            if median >= UP and st["above"] >= SUPPORT:
                w = min(MAX_WEIGHT, median)
                reasons.append(
                    f"{labels[kind]} {key} läuft besser: Median {median:.2f}× "
                    f"bei {st['n']} Videos, {int(st['above'] * 100)} % über dem Schnitt"
                )
            elif median <= DOWN and st["below"] >= SUPPORT:
                w = max(MIN_WEIGHT, median)
                reasons.append(
                    f"{labels[kind]} {key} läuft schwächer: Median {median:.2f}× "
                    f"bei {st['n']} Videos, {int(st['below'] * 100)} % unter dem Schnitt"
                )
            else:
                continue
            weights[kind][key] = round(w, 3)
    return weights, reasons


def changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    for kind in KINDS:
        a, b = old.get(kind) or {}, new.get(kind) or {}
        for key in set(a) | set(b):
            if abs(float(a.get(key, 1.0)) - float(b.get(key, 1.0))) >= CHANGE:
                return True
    return False


def mean_score(samples: list[Sample], start: datetime, end: datetime) -> tuple[float | None, int]:
    scores = [s.score for s in samples if start <= s.published_at < end]
    return (round(statistics.mean(scores), 3) if scores else None), len(scores)


# --- versions -----------------------------------------------------------------------


def current(session: Session) -> LearningVersion | None:
    """The version that applies now: a running trial, else the active one."""
    trial = session.scalar(
        select(LearningVersion)
        .where(LearningVersion.status == TRIAL)
        .order_by(LearningVersion.version.desc())
        .limit(1)
    )
    if trial is not None:
        return trial
    return session.scalar(
        select(LearningVersion)
        .where(LearningVersion.status == ACTIVE)
        .order_by(LearningVersion.version.desc())
        .limit(1)
    )


def active(session: Session) -> LearningVersion | None:
    return session.scalar(
        select(LearningVersion)
        .where(LearningVersion.status == ACTIVE)
        .order_by(LearningVersion.version.desc())
        .limit(1)
    )


def weights(session: Session) -> dict[str, dict[str, float]]:
    v = current(session)
    return {k: dict((v.weights or {}).get(k) or {}) for k in KINDS} if v else {k: {} for k in KINDS}


def next_number(session: Session) -> int:
    return int(session.scalar(select(func.coalesce(func.max(LearningVersion.version), 0))) or 0) + 1


def start_trial(
    session: Session,
    new_weights: dict[str, dict[str, float]],
    reasons: list[str],
    stats: dict[str, Any],
    samples: list[Sample],
    now: datetime,
    created_by: str = "learning",
) -> LearningVersion:
    baseline, n = mean_score(samples, now - timedelta(days=BASELINE_DAYS), now)
    version = LearningVersion(
        version=next_number(session),
        created_at=now,
        status=TRIAL,
        weights=new_weights,
        reasons=reasons,
        evidence={"groups": stats, "baseline": baseline, "baseline_posts": n},
        trial_until=now + timedelta(days=TRIAL_DAYS),
        created_by=created_by,
    )
    session.add(version)
    session.flush()
    return version


def evaluate(
    session: Session, trial: LearningVersion, samples: list[Sample], now: datetime
) -> str | None:
    """Decide a finished trial: ``active``, ``rolled_back`` or ``None`` (wait)."""
    assert trial.trial_until is not None
    if now < trial.trial_until:
        return None
    score, n = mean_score(samples, trial.created_at, now)
    baseline = (trial.evidence or {}).get("baseline")
    info: dict[str, Any] = {
        "trial_score": score,
        "trial_posts": n,
        "baseline": baseline,
        "decided_at": now.isoformat(),
    }
    if n < MIN_TRIAL_POSTS:
        if now < trial.created_at + timedelta(days=MAX_TRIAL_DAYS):
            return None
        info["result"] = "zu wenige Daten im Testzeitraum – vorsichtshalber zurückgenommen"
        outcome = ROLLED_BACK
    elif baseline is None or (score is not None and score >= baseline * KEEP_RATIO):
        info["result"] = "übernommen: nicht schlechter als vorher"
        outcome = ACTIVE
    else:
        info["result"] = "zurückgenommen: schlechter als vorher"
        outcome = ROLLED_BACK
    trial.evaluation = info
    if outcome == ACTIVE:
        previous = active(session)
        if previous is not None:
            previous.status = SUPERSEDED
    trial.status = outcome
    session.flush()
    return outcome


def rollback(
    session: Session, version: int, user_id: int, now: datetime | None = None
) -> LearningVersion:
    """Make the weights of ``version`` apply again (as a new active version)."""
    target = session.scalar(select(LearningVersion).where(LearningVersion.version == version))
    if target is None:
        raise LookupError(version)
    for v in session.scalars(
        select(LearningVersion).where(LearningVersion.status.in_([TRIAL, ACTIVE]))
    ):
        v.status = ROLLED_BACK if v.status == TRIAL else SUPERSEDED
    restored = LearningVersion(
        version=next_number(session),
        created_at=now or datetime.now(UTC),
        status=ACTIVE,
        weights=target.weights,
        reasons=[f"Von Hand auf Version {version} zurückgesetzt", *(target.reasons or [])],
        evidence=target.evidence,
        created_by=f"user:{user_id}",
        rolled_back_to=version,
    )
    session.add(restored)
    session.flush()
    return restored


# --- consumers ----------------------------------------------------------------------


def merge_groups(
    channel_groups: dict[str, dict[str, float]], learned: dict[str, dict[str, float]]
) -> dict[str, dict[str, float]]:
    """Channel numbers win; learned factors fill groups the channel has no data for."""
    out = {k: dict(v) for k, v in learned.items()}
    for kind, rows in channel_groups.items():
        out.setdefault(kind, {}).update(rows)
    return out


def format_performance(learned: dict[str, dict[str, float]]) -> dict[str, float]:
    """Format factors (0.8–1.2) as 0..1 for the Creative Director (1.0 → 0.5)."""
    return {
        key: round((w - MIN_WEIGHT) / (MAX_WEIGHT - MIN_WEIGHT), 3)
        for key, w in (learned.get("format") or {}).items()
    }
