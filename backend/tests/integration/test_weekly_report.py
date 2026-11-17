"""Ausbau A10: weekly report by e-mail (mock outbox by default)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import MetricWindow, PublishingJobStatus, PublishingMode, UserRole
from models import User
from models.analytics import Metric
from models.marketing import OutgoingMail
from models.publishing import Post, PublishingJob
from models.sponsors import SponsorInquiry
from services import sponsors, weekly_report
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

# Monday 23.11.2026, 09:00 in Berlin
MONDAY = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)


def _post(db: Session, title: str, views: int, at: datetime) -> None:
    chain = build_chain(db)
    chain.variant.title = title
    job = PublishingJob(
        variant_id=chain.variant.id,
        channel_id=chain.channel.id,
        status=PublishingJobStatus.SUCCEEDED,
        mode=PublishingMode.MOCK,
        scheduled_for=at,
        idempotency_key=f"r-{chain.variant.id}",
    )
    db.add(job)
    db.flush()
    post = Post(
        publishing_job_id=job.id,
        variant_id=chain.variant.id,
        channel_id=chain.channel.id,
        external_post_id=f"r-{chain.variant.id}",
        published_at=at,
        is_mock=True,
        url=f"https://youtu.be/{chain.variant.id}",
    )
    db.add(post)
    db.flush()
    db.add(Metric(post_id=post.id, measure_window=MetricWindow.H48, views=views, measured_at=at))
    db.flush()


def test_report_sums_week_compares_and_lists_todos(db: Session) -> None:
    settings = get_settings()
    _post(db, "Clutch A", 5000, MONDAY - timedelta(days=2))
    _post(db, "Clutch B", 1000, MONDAY - timedelta(days=3))
    _post(db, "Alt", 2000, MONDAY - timedelta(days=10))
    sponsors.add(
        db, settings, "Wir möchten eine bezahlte Kooperation mit eurem Kanal.", "a@marke.de"
    )
    report = weekly_report.build(db, settings, MONDAY)
    text = report.text
    assert report.subject == "Wochenbericht KW 47: 16.11.–22.11.2026"
    assert "Kurz: 2 Beiträge, 6.000 Aufrufe (+200 % zur Vorwoche)." in text
    assert text.index("Clutch A") < text.index("Clutch B")
    assert "1 neue Sponsorenanfragen (Sponsoren)" in text
    assert "Testbetrieb" in text and "Nächste Woche im Plan" in text
    assert "Alt (" not in text  # last week's post is not among the best of this week


def test_sent_once_per_week_at_the_set_time(db: Session) -> None:
    settings = get_settings().model_copy(update={"report_email": "chef@example.com"})
    early = MONDAY - timedelta(hours=2)  # Monday 07:00 local
    assert weekly_report.maybe_send(db, settings, early) is None
    mail = weekly_report.maybe_send(db, settings, MONDAY)
    assert mail is not None and mail.status == "mock" and mail.to_address == "chef@example.com"
    assert weekly_report.maybe_send(db, settings, MONDAY + timedelta(hours=3)) is None
    next_week = weekly_report.maybe_send(db, settings, MONDAY + timedelta(days=7))
    assert next_week is not None
    off = settings.model_copy(update={"report_enabled": False})
    assert weekly_report.maybe_send(db, off, MONDAY + timedelta(days=14)) is None


def test_without_recipient_it_stays_in_the_outbox(db: Session) -> None:
    settings = get_settings().model_copy(
        update={
            "report_email": "",
            "mail_mode": "smtp",
            "smtp_host": "smtp.example",
            "mail_from": "x@example.com",
        }
    )
    mail = weekly_report.send(db, settings, MONDAY)
    assert mail.status == "mock" and mail.error == "Kein Empfänger eingetragen"


def test_api_preview_and_send(api: TestClient, db: Session, make_user: Callable[..., User]) -> None:
    build_chain(db)
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    db.commit()
    login(api, "viewer@example.com")
    assert api.get("/api/reports/weekly").status_code == 403
    h = login(api, "op@example.com")
    preview = api.get("/api/reports/weekly").json()
    assert preview["subject"].startswith("Wochenbericht KW")
    assert preview["schedule"] == "Montags um 8 Uhr" and preview["last_sent_at"] is None
    sent = api.post("/api/reports/weekly/send", headers=h)
    assert sent.status_code == 201 and sent.json()["kind"] == "weekly_report"
    assert api.get("/api/reports/weekly").json()["last_sent_at"] is not None
    assert db.scalar(select(OutgoingMail).where(OutgoingMail.kind == "weekly_report")) is not None
    assert db.scalar(select(SponsorInquiry)) is None
