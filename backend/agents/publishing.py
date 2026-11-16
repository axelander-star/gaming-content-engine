"""Agent 15: Publishing (PROJECT_SPEC sections 6, 11 and 15, Phase 12).

Works on variants in ``SCHEDULED`` whose planned time has come. For the variant's
planned job it

* publishes through the mock adapter unless publishing is live *and* the job was
  planned in live mode (a job planned as a test stays a test),
* in live mode only for an authorized channel with live publishing allowed
  (``AUTO_PUBLISH_ENABLED``, ``PUBLISHING_MODE=live``, dashboard switches, no
  emergency stop); otherwise the video waits,
* uses the platform's official API (YouTube since Phase 12; TikTok, Instagram and
  Facebook since Phase 13),
* is idempotent: a job that already has a post is only completed, and a job is
  marked ``running`` (committed) before the upload starts, so a crash cannot lead
  to a second upload.

Temporary problems (quota, 5xx, network) put the job back with a later time;
an expired connection marks the channel ``expired``; a restricted one (e.g. an
unaudited TikTok app) ``connected_restricted``; a permanent error marks the job
failed and notifies the operator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from agents.base import (
    Agent,
    AgentContext,
    AgentResult,
    AgentSkipError,
    PermanentError,
    ProviderUnavailableError,
)
from agents.gameplay_analysis import local_file
from agents.publishing_strategy import publish_block
from core.enums import (
    ChannelAuthStatus,
    NotificationLevel,
    PublishingJobStatus,
    PublishingMode,
    VideoStatus,
)
from models.access import Notification
from models.channels import Channel
from models.production import Variant
from models.publishing import Post, PublishingJob
from services import campaigns, platform, publishers, workflow
from services.queue import get_redis
from services.sources.base import QuotaExceededError

ACTOR = "publishing"
RETRY_AFTER = timedelta(minutes=30)


class ChannelBlockedError(AgentSkipError):
    gate = "channel"


class PublishLaterError(AgentSkipError):
    gate = "retry_later"


class PublishingAgent(Agent):
    def run(self, ctx: AgentContext, payload: dict[str, Any]) -> AgentResult:
        s, settings = ctx.session, ctx.settings
        variant = s.get(Variant, int(payload["entity_id"]))
        assert variant is not None  # guaranteed by the gate
        channel = s.get(Channel, variant.channel_id)
        assert channel is not None
        now = datetime.now(UTC)
        job = s.scalar(
            select(PublishingJob)
            .where(
                PublishingJob.variant_id == variant.id,
                PublishingJob.status.in_(
                    [PublishingJobStatus.SCHEDULED, PublishingJobStatus.RUNNING]
                ),
            )
            .order_by(PublishingJob.id.desc())
            .limit(1)
        )
        if job is None:
            workflow.transition(s, variant, VideoStatus.READY_TO_PUBLISH, actor=ACTOR)
            return AgentResult(output={"reason": "no planned job", "variant_id": variant.id})
        post = s.scalar(select(Post).where(Post.publishing_job_id == job.id))
        if post is not None:  # published before, the run that did it did not finish
            return self._done(ctx, variant, job, post, resumed=True)
        if job.status == PublishingJobStatus.RUNNING:
            raise PermanentError(
                f"Auftrag #{job.id} lief schon ohne Ergebnis; bitte auf der Plattform prüfen, "
                "bevor er neu geplant wird (keine doppelte Veröffentlichung)"
            )
        if job.scheduled_for and job.scheduled_for > now:
            return AgentResult(output={"waiting_until": job.scheduled_for.isoformat()})

        live = job.mode == PublishingMode.LIVE and settings.publishing_mode == "live"
        publisher: publishers.Publisher | None
        if live:
            block = publish_block(s, settings, channel)
            if block:
                job.last_error = block
                s.commit()
                raise ChannelBlockedError(block)
            publisher = publishers.live_publisher(channel.platform.code, get_redis())
            if publisher is None:
                job.last_error = f"{channel.platform.name}: keine Live-Anbindung"
                s.commit()
                raise ProviderUnavailableError(job.last_error)
        else:
            publisher = publishers.MockPublisher()
        if not variant.storage_uri:
            raise PermanentError("Keine fertige Videodatei")
        path = local_file(settings, variant.storage_uri)

        job.status = PublishingJobStatus.RUNNING
        job.attempts += 1
        s.commit()  # durable before the upload: a crash can never cause a second post
        try:
            result = publisher.publish(s, settings, channel, variant, path)
        except (QuotaExceededError, platform.TransientError) as exc:
            job.status = PublishingJobStatus.SCHEDULED
            job.scheduled_for = now + RETRY_AFTER * job.attempts
            job.last_error = str(exc)[:1000]
            s.commit()
            raise PublishLaterError(str(exc)) from exc
        except (platform.AuthExpiredError, platform.RestrictedError) as exc:
            expired = isinstance(exc, platform.AuthExpiredError)
            job.status = PublishingJobStatus.SCHEDULED
            job.last_error = str(exc)[:1000]
            channel.auth_status = (
                ChannelAuthStatus.EXPIRED if expired else ChannelAuthStatus.CONNECTED_RESTRICTED
            )
            what = "Verbindung abgelaufen" if expired else "Veröffentlichung eingeschränkt"
            self._notify(s, f"{channel.name}: {what}", str(exc))
            s.commit()
            raise ChannelBlockedError(str(exc)) from exc
        except (platform.PlatformError, platform.NotConfiguredError) as exc:
            job.status = PublishingJobStatus.FAILED
            job.last_error = str(exc)[:1000]
            self._notify(s, f"Veröffentlichung von Variante #{variant.id} fehlgeschlagen", str(exc))
            s.commit()
            raise PermanentError(str(exc)) from exc

        post = Post(
            publishing_job_id=job.id,
            variant_id=variant.id,
            channel_id=channel.id,
            content_project_id=variant.content_project_id,
            external_post_id=result.external_id,
            url=result.url,
            published_at=datetime.now(UTC),
            is_mock=result.is_mock,
        )
        s.add(post)
        s.flush()
        return self._done(ctx, variant, job, post, privacy=result.privacy)

    def _done(
        self,
        ctx: AgentContext,
        variant: Variant,
        job: PublishingJob,
        post: Post,
        resumed: bool = False,
        privacy: str | None = None,
    ) -> AgentResult:
        s = ctx.session
        job.status = PublishingJobStatus.SUCCEEDED
        job.last_error = None
        if variant.status == VideoStatus.SCHEDULED:
            workflow.transition(s, variant, VideoStatus.PUBLISHED, actor=ACTOR)
        # Campaign clip: the operator submits the link by hand within the window.
        submission = campaigns.on_published(s, variant, post)
        info = {
            "variant_id": variant.id,
            "job_id": job.id,
            "post_id": post.id,
            "external_id": post.external_post_id,
            "url": post.url,
            "mock": post.is_mock,
            "privacy": privacy,
            "resumed": resumed,
            "campaign_submission_id": submission.id if submission else None,
        }
        ctx.decide(
            "published",
            info,
            (
                "Testveröffentlichung (Mock), nichts wurde hochgeladen"
                if post.is_mock
                else f"Hochgeladen als {post.external_post_id} ({privacy})"
            )
            + (" – Abschluss eines früheren Laufs" if resumed else "")
            + ".",
            entity_type="variants",
            entity_id=variant.id,
        )
        return AgentResult(output=info)

    @staticmethod
    def _notify(s: Any, title: str, body: str) -> None:
        s.add(Notification(level=NotificationLevel.WARNING, title=title[:200], body=body[:2000]))
