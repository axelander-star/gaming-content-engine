"""Fixed cost items (server, domain, subscriptions) and the live cost summary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AICallStatus, UserRole
from models import User
from models.ai import AICall
from models.fixed_costs import FixedCost
from services import budget, costs, fixed_costs
from services.controls import update_operations
from tests.conftest import login


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return get_settings().model_copy(update={"media_root": str(tmp_path / "media")})


def _item(**kw: object) -> FixedCost:
    data: dict[str, object] = {
        "name": "x",
        "category": "server",
        "amount": Decimal("10"),
        "currency": "EUR",
        "interval": "month",
        "in_budget": True,
        "is_active": True,
    }
    data.update(kw)
    return FixedCost(**data)


def test_monthly_conversion(settings: Settings) -> None:
    s = settings.model_copy(update={"eur_per_usd": 0.9})
    assert fixed_costs.monthly_eur(_item(amount=Decimal("20"), currency="USD"), s) == Decimal(
        "18.0000"
    )
    assert fixed_costs.monthly_eur(_item(amount=Decimal("12"), interval="year"), s) == Decimal(
        "1.0000"
    )


def test_accrued_share_of_month() -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    assert fixed_costs.accrued(Decimal("30"), start, start) == Decimal("0")
    half = datetime(2026, 11, 16, tzinfo=UTC)
    assert fixed_costs.accrued(Decimal("30"), start, half) == Decimal("15.0000")
    dec = datetime(2026, 12, 1, tzinfo=UTC)
    assert fixed_costs.accrued(Decimal("31"), dec, datetime(2027, 1, 1, tzinfo=UTC)) == Decimal(
        "31.0000"
    )


def test_env_fallback_until_items_exist(db: Session, settings: Settings) -> None:
    s = settings.model_copy(update={"server_monthly_eur": 13.33})
    t = fixed_costs.totals(db, s)
    assert t.from_env and t.in_budget_eur == Decimal("13.33")
    assert fixed_costs.seed_defaults(db, s) == len(fixed_costs.DEFAULTS)
    assert fixed_costs.seed_defaults(db, s) == 0  # only once
    t = fixed_costs.totals(db, s)
    assert not t.from_env
    # Contabo counts in the budget, Claude Pro (20 USD) only in the total.
    assert t.in_budget_eur == Decimal("13.3300")
    expected_all = Decimal("13.33") + Decimal("20") * Decimal(str(s.eur_per_usd))
    assert t.all_eur == expected_all.quantize(Decimal("0.0001"))
    pro = next(i for i in t.items if i["category"] == "subscription")
    assert pro["in_budget"] is False and pro["currency"] == "USD"
    domain = next(i for i in t.items if i["category"] == "domain")
    assert domain["missing_price"] is True


def test_deleting_all_items_does_not_bring_back_env_values(db: Session, settings: Settings) -> None:
    s = settings.model_copy(update={"server_monthly_eur": 99.0})
    fixed_costs.seed_defaults(db, s)
    for item in db.scalars(select(FixedCost)).all():
        db.delete(item)
    db.flush()
    t = fixed_costs.totals(db, s)
    assert not t.from_env and t.all_eur == 0
    assert fixed_costs.seed_defaults(db, s) == 0


def test_only_budget_items_drive_the_budget(db: Session, settings: Settings) -> None:
    update_operations(db, None, {"monthly_budget_eur": 50})
    db.add_all(
        [
            _item(name="Server", amount=Decimal("10")),
            _item(name="Abo", category="subscription", amount=Decimal("40"), in_budget=False),
            _item(name="Alt", amount=Decimal("100"), is_active=False),
        ]
    )
    db.flush()
    status = budget.budget_status(db, settings)
    assert status.spent_eur >= Decimal("10") and status.spent_eur < Decimal("40")
    data = costs.summary(db, settings, None)
    assert data["costs"]["fixed"] == 50.0 and data["costs"]["fixed_in_budget"] == 10.0
    assert 0 <= data["costs"]["accrued"] <= data["costs"]["total"]
    assert data["as_of"]


def test_summary_counts_ai_tokens_today(db: Session, settings: Settings) -> None:
    db.add_all(
        [
            AICall(
                purpose="ideas",
                tier="text",
                provider="mock",
                model="m",
                status=AICallStatus.SUCCEEDED,
                input_tokens=100,
                output_tokens=50,
            ),
            AICall(
                purpose="chat",
                tier="reasoning",
                provider="claude",
                model="m",
                status=AICallStatus.SUCCEEDED,
                input_tokens=1000,
                output_tokens=200,
                cost_usd=Decimal("0.004"),
            ),
        ]
    )
    db.flush()
    data = costs.summary(db, settings, None)
    today = data["ai"]["today"]
    assert today["calls"] >= 2 and today["live_calls"] >= 1
    assert today["input_tokens"] >= 1100 and today["output_tokens"] >= 250
    assert today["cost_usd"] >= 0.004 and today["last_call_at"]
    assert data["ai"]["month"]["calls"] >= today["calls"]


def test_fixed_costs_api(
    db: Session, settings: Settings, api: TestClient, make_user: Callable[..., User]
) -> None:
    api.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    make_user("viewer@example.com", UserRole.VIEWER)
    make_user("admin@example.com", UserRole.ADMIN)
    db.commit()
    hv = login(api, "viewer@example.com")
    assert api.get("/api/costs/fixed", headers=hv).status_code == 200
    body = {"name": "Domain", "category": "domain", "amount": "6.00", "interval": "year"}
    assert api.post("/api/costs/fixed", json=body, headers=hv).status_code == 403
    ha = login(api, "admin@example.com")
    res = api.post("/api/costs/fixed", json=body, headers=ha)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["monthly_eur"] == 0.5
    listed = api.get("/api/costs/fixed", headers=ha).json()
    # the starting list was created together with the first own item
    assert len(listed["items"]) == len(fixed_costs.DEFAULTS) + 1 and not listed["from_env"]
    res = api.patch(
        f"/api/costs/fixed/{created['id']}",
        json={"amount": "12.00", "in_budget": False},
        headers=ha,
    )
    assert res.status_code == 200 and res.json()["monthly_eur"] == 1.0
    assert res.json()["in_budget"] is False
    bad = api.post("/api/costs/fixed", json={**body, "amount": "-1"}, headers=ha)
    assert bad.status_code == 422
    assert api.delete(f"/api/costs/fixed/{created['id']}", headers=ha).status_code == 204
    assert api.delete(f"/api/costs/fixed/{created['id']}", headers=ha).status_code == 404
    summary = api.get("/api/costs/summary", headers=hv).json()
    assert len(summary["fixed"]["items"]) == len(fixed_costs.DEFAULTS)
