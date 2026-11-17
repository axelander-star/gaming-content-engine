"""Ausbau A9: sponsor inbox sorts inquiries, flags risks, prices and drafts; sends nothing."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import Language, MetricWindow, PublishingJobStatus, PublishingMode, UserRole
from models import User
from models.analytics import Metric
from models.marketing import OutgoingMail
from models.publishing import Post, PublishingJob
from services import sponsors
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

PAID_DE = (
    "Hallo, wir sind ein Hersteller von Gaming-Headsets und suchen eine bezahlte "
    "Kooperation für ein Short. Habt ihr ein Mediakit und eure Preise?"
)
PAID_EN = (
    "Hi there, we would love a paid partnership with your gaming channel. What is your "
    "rate for one sponsored short? Budget is available."
)


def test_categories_and_flags() -> None:
    assert sponsors.classify(PAID_DE) == ("sponsoring", [])
    assert (
        sponsors.classify("We can send you our new mouse for a review, for free.")[0]
        == "product_test"
    )
    cat, flags = sponsors.classify("Join our affiliate program, 10% commission on every sale")
    assert cat == "affiliate"
    cat, flags = sponsors.classify("Paid collaboration with our online casino, slots and betting")
    assert cat == "sponsoring" and any("Glücksspiel" in f for f in flags)
    assert any(
        "Krypto" in f for f in sponsors.classify("Promote our crypto token airdrop, paid")[1]
    )
    cat, flags = sponsors.classify("Collaboration! Just pay the registration fee upfront.")
    assert cat == "spam" and "Vorabzahlung verlangt" in flags
    assert sponsors.classify("We offer cheap backlinks and SEO for your website")[0] == "spam"
    assert sponsors.classify("Kurze Frage zu deinem letzten Video")[0] == "other"


def test_brand_from_sender() -> None:
    assert sponsors.brand_of("Lisa <lisa@hyper-gear.com>", "") == (
        "Hyper Gear",
        "lisa@hyper-gear.com",
    )
    assert sponsors.brand_of("Max Muster <max@gmail.com>", "") == ("Max Muster", "max@gmail.com")
    assert sponsors.brand_of("", "Kontakt: info@clickmaus.de bitte")[0] == "Clickmaus"


def _views(db: Session, values: list[int]) -> int:
    project_id = 0
    for v in values:
        chain = build_chain(db)
        job = PublishingJob(
            variant_id=chain.variant.id,
            channel_id=chain.channel.id,
            status=PublishingJobStatus.SUCCEEDED,
            mode=PublishingMode.MOCK,
            scheduled_for=datetime.now(UTC),
            idempotency_key=f"s-{chain.variant.id}",
        )
        db.add(job)
        db.flush()
        post = Post(
            publishing_job_id=job.id,
            variant_id=chain.variant.id,
            channel_id=chain.channel.id,
            external_post_id=f"s-{chain.variant.id}",
            published_at=datetime.now(UTC),
            is_mock=True,
        )
        db.add(post)
        db.flush()
        db.add(
            Metric(
                post_id=post.id,
                measure_window=MetricWindow.H48,
                views=v,
                measured_at=datetime.now(UTC),
            )
        )
        db.flush()
        project_id = chain.channel.content_project_id
    return project_id


def test_price_from_own_reach_with_minimum(db: Session) -> None:
    build_chain(db)
    empty = sponsors.suggest_price(db, None)
    assert empty.per_post == Decimal("50.00") and empty.basis["median_views"] is None
    project_id = _views(db, [10_000, 20_000, 30_000])
    price = sponsors.suggest_price(db, project_id)
    assert price.basis["median_views"] == 20_000
    assert price.per_post == Decimal("300.00")  # 20 × 15 €
    assert price.low == Decimal("200.00") and price.high == Decimal("500.00")
    assert price.bundle == Decimal("810.00")  # 3 × 300 − 10 %


def test_add_drafts_reply_in_language_and_sends_nothing(db: Session) -> None:
    settings = get_settings()
    _views(db, [10_000])
    de = sponsors.add(db, settings, PAID_DE, "Lisa <lisa@hyper-gear.com>", "Kooperation")
    assert de.category == "sponsoring" and de.language == Language.DE and de.status == "new"
    assert de.brand == "Hyper Gear" and de.content_project_id is not None
    assert "150 €" in de.draft and "Anzeige" in de.draft
    assert de.draft_source in {"mock", "template"}
    en = sponsors.add(db, settings, PAID_EN, "deals@brand.io")
    assert en.language == Language.EN and "150 EUR" in en.draft and "ad" in en.draft
    spam = sponsors.add(
        db, settings, "Buy followers now, guest post with backlink for SEO", "x@y.ru"
    )
    assert spam.category == "spam" and spam.status == "archived" and spam.draft == ""
    assert db.scalars(select(OutgoingMail)).all() == []  # nothing is ever sent
    with pytest.raises(sponsors.SponsorError):
        sponsors.add(db, settings, "zu kurz")


def test_ai_answer_without_the_price_falls_back_to_template(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()

    class Fake:
        text, provider = (
            "Klingt super, wir machen das gern, meld dich einfach jederzeit bei uns!",
            "claude",
        )

    monkeypatch.setattr("services.ai.generate", lambda *a, **k: Fake())
    inq = sponsors.add(db, settings, PAID_DE, "a@firma-x.de")
    assert inq.draft_source == "template" and "50 €" in inq.draft


def test_api_inbox_update_redraft_and_rights(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    build_chain(db)
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    db.commit()
    login(api, "viewer@example.com")
    assert api.get("/api/sponsors").status_code == 403
    h = login(api, "op@example.com")
    r = api.post(
        "/api/sponsors",
        json={"sender": "Lisa <lisa@hyper-gear.com>", "subject": "Kooperation", "body": PAID_DE},
        headers=h,
    )
    assert r.status_code == 201, r.text
    inq = r.json()
    assert inq["category_label"] == "Bezahlte Kooperation" and inq["price_eur"] == 50.0
    assert api.post("/api/sponsors", json={"body": "kurz"}, headers=h).status_code == 422
    box = api.get("/api/sponsors").json()
    assert box["counts"]["new"] == 1 and box["inquiries"][0]["brand"] == "Hyper Gear"
    edited = api.patch(
        f"/api/sponsors/{inq['id']}", json={"draft": "Eigener Text", "status": "replied"}, headers=h
    ).json()
    assert edited["draft"] == "Eigener Text" and edited["draft_source"] == "manual"
    assert (
        api.patch(f"/api/sponsors/{inq['id']}", json={"status": "kaputt"}, headers=h).status_code
        == 422
    )
    again = api.post(f"/api/sponsors/{inq['id']}/redraft", headers=h).json()
    assert again["draft"] != "Eigener Text"
    assert (
        api.patch(f"/api/sponsors/{inq['id']}", json={"status": "won"}, headers=h).json()["status"]
        == "won"
    )
    assert api.delete(f"/api/sponsors/{inq['id']}", headers=h).status_code == 204
