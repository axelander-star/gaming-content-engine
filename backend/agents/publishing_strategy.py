"""Agent 14: Publishing Strategy (PROJECT_SPEC sections 3, 6 and 12, Phase 11).

Runs per channel (payload ``{"sweep": true, "channel_id": …}``, dispatched by the
master at most every ``strategy_interval_minutes``):

1. Once per local day it decides how many posts the channel gets
   (:func:`services.strategy.decide_amount`) and stores the decision as a new
   strategy version with reasons and inputs. A version made earlier the same day,
   by the agent or by an operator's rollback, is kept.
2. It takes back planned posts that no longer qualify (quality below the
   minimum, rights no longer valid, channel paused or not allowed to publish, or
   more planned than the amount allows).
3. It picks the best waiting videos (quality, proven games/formats/hooks, one
   variant per clip, a test variant on bigger days) and plans them at times
   inside the posting window with the minimum interval. Each planned post is a
   ``publishing_jobs`` row; the variant moves to ``SCHEDULED``.

Nothing is published here. Publishing is the Publishing Agent's job (Phase 12/13)
and stays in mock mode until the operator enables live publishing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, AgentResult, PermanentError
from core.config import Settings
from core.enums import ChannelAuthStatus, PublishingJobStatus, PublishingMode, VideoStatus
from models.channels import Channel
from models.production import Variant
from models.publishing import PublishingJob, StrategyVersion
from services import gates, strategy, workflow
from services.controls import effective_controls, get_operations

ACTIVE_JOBS = (
    PublishingJobStatus.PENDING,
    PublishingJobStatus.SCHEDULED,
    PublishingJobStatus.RUNNING,
    PublishingJobStatus.SUCCEEDED,
)
ACTOR = "publishing_strategy"


def bounds_for(session: Session, channel: Channel) -> strategy.Bounds:
    ops = get_operations(session)
    return strategy.Bounds(
        min_posts=channel.min_posts_per_day,
        max_posts=channel.max_posts_per_day,
        interval_minutes=max(channel.min_interval_minutes, ops.min_publish_interval_minutes),
        window=strategy.window_for(channel),
        paused=channel.is_paused or channel.platform.is_paused,
    )


def publish_block(session: Session, settings: Settings, channel: Channel) -> str | None:
    """Why nothing may be planned for this channel right now (None = allowed)."""
    if channel.is_paused or channel.platform.is_paused:
        return "Kanal oder Plattform pausiert"
    controls = effective_controls(session, settings)
    if controls.emergency_stop:
        return "Not-Aus aktiv"
    if settings.publishing_mode == "live":
        if not controls.publishing_allowed:
            return "Automatische Veröffentlichung ist gesperrt"
        if channel.auth_status != ChannelAuthStatus.AUTHORIZED:
            return f"Kanal nicht autorisiert ({channel.auth_status.value})"
    return None


class PublishingStrategyAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        channel = s.get(Channel, int(payload.get("channel_id") or 0))
        if channel is None:
            raise PermanentError("Kanal fehlt")
        now = _now(payload)
        tz = strategy.timezone_for(channel)
        today = now.astimezone(tz).date()
        bounds = bounds_for(s, channel)

        posts = strategy.load_history(s, channel.id)
        assessment = strategy.assess(posts)
        groups = strategy.group_scores(posts, assessment)
        version = self._version(ctx, channel, today, now, bounds, posts, assessment, groups)
        amount = 0 if bounds.paused else min(version.posts_per_day, bounds.upper)

        block = publish_block(s, settings, channel)
        minimum = get_operations(s).min_quality_score
        start, end = _day(today, tz)
        jobs = list(
            s.scalars(
                select(PublishingJob)
                .where(
                    PublishingJob.channel_id == channel.id,
                    PublishingJob.status.in_(ACTIVE_JOBS),
                    PublishingJob.scheduled_for >= start,
                    PublishingJob.scheduled_for < end,
                )
                .order_by(PublishingJob.scheduled_for)
            )
        )
        unscheduled = self._take_back(s, jobs, now, amount, minimum, block)
        jobs = [j for j in jobs if j.status != PublishingJobStatus.CANCELLED]

        planned: list[dict[str, Any]] = []
        held: list[dict[str, Any]] = []
        slots = max(0, amount - len(jobs))
        if block is None and slots > 0:
            planned, held = self._plan(ctx, channel, jobs, slots, minimum, today, tz, now, bounds,
                                       version, groups)  # fmt: skip

        info = {
            "channel_id": channel.id,
            "day": today.isoformat(),
            "strategy_version": version.version,
            "posts_per_day": version.posts_per_day,
            "effective_amount": amount,
            "already_planned": len(jobs),
            "planned": planned,
            "unscheduled": unscheduled,
            "held": held,
            "blocked": block,
        }
        if planned or unscheduled:
            text = (
                f"{channel.name}: {amount} pro Tag (Version {version.version}), "
                f"{len(jobs)} schon geplant, {len(planned)} neu geplant"
                + (f", {len(unscheduled)} zurückgenommen" if unscheduled else "")
                + (f", {len(held)} zurückgehalten" if held else "")
                + (f". Gesperrt: {block}" if block else "")
                + "."
            )
            ctx.decide("publishing_plan", info, text, entity_type="channels", entity_id=channel.id)
        return AgentResult(output=info)

    # --- amount ---------------------------------------------------------------------

    def _version(
        self,
        ctx: AgentContext,
        channel: Channel,
        today: date,
        now: datetime,
        bounds: strategy.Bounds,
        posts: list[strategy.PostPerf],
        assessment: strategy.Assessment,
        groups: dict[str, dict[str, float]],
    ) -> StrategyVersion:
        s = ctx.session
        latest = strategy.latest_version(s, channel.id)
        if latest is not None and latest.planned_for >= today:
            return latest  # one decision per day (damping); also keeps a rollback
        supply = strategy.load_supply(s, channel.id, now)
        # after a pause or without bounds the channel starts again cautiously
        active = latest is not None and not (latest.params or {}).get("inactive")
        previous = latest.posts_per_day if latest is not None and active else None
        since = strategy.days_since_change(s, channel.id, today)
        decision = strategy.decide_amount(previous, assessment, supply, bounds, since)
        preferred = strategy.best_hours(posts, assessment, strategy.timezone_for(channel))
        version = StrategyVersion(
            channel_id=channel.id,
            version=(latest.version + 1) if latest else 1,
            planned_for=today,
            posts_per_day=decision.posts_per_day,
            params={
                "window": list(bounds.window),
                "interval_minutes": bounds.interval_minutes,
                "preferred_hours": preferred,
                "groups": groups,
                "inactive": decision.inactive,
            },
            reasons=decision.reasons,
            inputs={
                "assessment": assessment.as_dict(),
                "supply": supply.as_dict(),
                "bounds": {
                    "min": bounds.min_posts,
                    "max": bounds.max_posts,
                    "upper": bounds.upper,
                    "paused": bounds.paused,
                },
                "previous": previous,
                "days_since_change": since,
            },
            created_by=ACTOR,
        )
        s.add(version)
        s.flush()
        ctx.decide(
            "strategy_version",
            {
                "version": version.version,
                "posts_per_day": decision.posts_per_day,
                "change": decision.change,
            },
            f"{channel.name}: {decision.posts_per_day} Veröffentlichung(en) pro Tag"
            f" ({decision.change:+d}). " + " ".join(r.rstrip(".") + "." for r in decision.reasons),
            inputs=version.inputs,
            entity_type="channels",
            entity_id=channel.id,
        )
        return version

    # --- take back ------------------------------------------------------------------

    def _take_back(
        self,
        s: Session,
        jobs: list[PublishingJob],
        now: datetime,
        amount: int,
        minimum: float,
        block: str | None,
    ) -> list[dict[str, Any]]:
        out = []
        keep = 0
        for job in jobs:
            if job.status != PublishingJobStatus.SCHEDULED or job.scheduled_for is None:
                keep += 1  # running or done: counts for today, cannot be taken back
                continue
            if job.scheduled_for <= now:
                keep += 1
                continue
            variant = s.get(Variant, job.variant_id)
            assert variant is not None
            reason = block
            if reason is None and (variant.quality_score or 0.0) < minimum:
                reason = f"Qualitätswert {variant.quality_score} unter Minimum {minimum}"
            if reason is None:
                source = gates.source_file(s, variant)
                problem = "Quellmaterial fehlt" if source is None else gates.rights_check(s, source)
                reason = f"Rechte: {problem}" if problem else None
            if reason is None and keep >= amount:
                reason = f"Mehr geplant als die Tagesmenge {amount}"
            if reason is None:
                keep += 1
                continue
            job.status = PublishingJobStatus.CANCELLED
            job.last_error = reason
            if variant.status == VideoStatus.SCHEDULED:
                workflow.transition(s, variant, VideoStatus.READY_TO_PUBLISH, actor=ACTOR)
            out.append({"variant_id": variant.id, "job_id": job.id, "reason": reason})
        return out

    # --- plan -----------------------------------------------------------------------

    def _plan(
        self,
        ctx: AgentContext,
        channel: Channel,
        jobs: list[PublishingJob],
        slots: int,
        minimum: float,
        today: date,
        tz: Any,
        now: datetime,
        bounds: strategy.Bounds,
        version: StrategyVersion,
        groups: dict[str, dict[str, float]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        s, settings = ctx.session, ctx.settings
        busy_clips = {s.get(Variant, j.variant_id).clip_id for j in jobs}  # type: ignore[union-attr]
        held: list[dict[str, Any]] = []
        candidates: list[strategy.Candidate] = []
        rows = s.scalars(
            select(Variant)
            .where(
                Variant.channel_id == channel.id,
                Variant.status == VideoStatus.READY_TO_PUBLISH,
            )
            .order_by(Variant.updated_at, Variant.id)
            .limit(200)
        ).all()
        games = strategy.games_for_clips(s, [v.clip_id for v in rows])
        for v in rows:
            if (v.quality_score or 0.0) < minimum:
                held.append({"variant_id": v.id, "reason": "Qualitätswert unter Minimum"})
                continue
            source = gates.source_file(s, v)
            problem = "Quellmaterial fehlt" if source is None else gates.rights_check(s, source)
            if problem:
                held.append({"variant_id": v.id, "reason": f"Rechte: {problem}"})
                continue
            if v.clip_id in busy_clips:
                held.append({"variant_id": v.id, "reason": "Andere Clip-Variante heute geplant"})
                continue
            candidates.append(
                strategy.Candidate(
                    variant_id=v.id,
                    clip_id=v.clip_id,
                    quality=v.quality_score or 0.0,
                    ready_since=v.updated_at or now,
                    game=games.get(v.clip_id),
                    video_format=v.video_format,
                    hook_type=v.hook_type,
                    experiment=bool((v.concept or {}).get("experiment")),
                )
            )
        chosen = strategy.choose(candidates, slots, groups)
        preferred = (version.params or {}).get("preferred_hours")
        times = strategy.slot_times(
            today,
            len(chosen),
            bounds,
            tz,
            now,
            [j.scheduled_for for j in jobs if j.scheduled_for],
            preferred,
        )
        planned = []
        mode = PublishingMode(settings.publishing_mode)
        for cand, when in zip(chosen, times, strict=False):
            variant = s.get(Variant, cand.variant_id)
            assert variant is not None
            prior = s.scalar(
                select(func.count(PublishingJob.id)).where(PublishingJob.variant_id == variant.id)
            )
            value, notes = strategy.priority(cand, groups)
            decision = ctx.decide(
                "scheduled",
                {"variant_id": variant.id, "at": when.isoformat(), "priority": value},
                f"Variante {variant.variant_label} ({variant.language.value}) für "
                f"{when.astimezone(tz):%d.%m. %H:%M} geplant: Qualität {cand.quality:.2f}"
                + (f", {', '.join(notes)}" if notes else "")
                + (", Testvariante" if cand.experiment else "")
                + ".",
                entity_type="variants",
                entity_id=variant.id,
            )
            s.flush()
            s.add(
                PublishingJob(
                    variant_id=variant.id,
                    channel_id=channel.id,
                    status=PublishingJobStatus.SCHEDULED,
                    mode=mode,
                    scheduled_for=when,
                    idempotency_key=f"pub-v{variant.id}-c{channel.id}-{(prior or 0) + 1}",
                    decided_by_decision_id=decision.id,
                )
            )
            workflow.transition(s, variant, VideoStatus.SCHEDULED, actor=ACTOR)
            planned.append({"variant_id": variant.id, "at": when.isoformat(), "priority": value})
        if len(times) < len(chosen):
            for cand in chosen[len(times) :]:
                held.append({"variant_id": cand.variant_id, "reason": "Kein freier Zeitpunkt mehr"})
        chosen_ids = {c.variant_id for c in chosen}
        rest = [c for c in candidates if c.variant_id not in chosen_ids]
        held += [{"variant_id": c.variant_id, "reason": "Tagesmenge erreicht"} for c in rest]
        return planned, held


def _now(payload: dict[str, Any]) -> datetime:
    """Planning time; tests and simulations may pass ``now`` (ISO 8601)."""
    raw = payload.get("now")
    if isinstance(raw, str):
        value = datetime.fromisoformat(raw)
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _day(day: date, tz: Any) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)
