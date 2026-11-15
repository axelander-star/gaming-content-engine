"""AI layer (extension phase E3): mock default, live conditions, hard monthly cap.

No test talks to the Claude API: live calls go to a fake client.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AICallStatus, CostCategory, UserRole
from models import Cost
from models.access import User
from models.ai import AICall
from services import ai
from services.controls import update_operations
from tests.conftest import login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


class FakeMessages:
    def __init__(self, owner: FakeClient) -> None:
        self.owner = owner

    def create(self, **params: Any) -> Any:
        self.owner.calls.append(params)
        if self.owner.error is not None:
            raise self.owner.error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.owner.text)],
            usage=SimpleNamespace(
                input_tokens=self.owner.input_tokens,
                output_tokens=self.owner.output_tokens,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            stop_reason=self.owner.stop_reason,
            model=params["model"],
            _request_id="req_test",
        )


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = "Antwort von Claude"
        self.input_tokens = 1000
        self.output_tokens = 200
        self.stop_reason = "end_turn"
        self.error: Exception | None = None
        self.messages = FakeMessages(self)
        self.beta = SimpleNamespace(messages=FakeMessages(self))


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClient]:
    client = FakeClient()
    monkeypatch.setattr(ai, "client_factory", lambda _s: client)
    yield client


def live_settings(**extra: Any) -> Settings:
    return get_settings().model_copy(
        update={
            "paid_api_calls_enabled": True,
            "anthropic_api_key": SecretStr("sk-test-not-real"),
            **extra,
        }
    )


def request(tier: ai.Tier = "text", **kw: Any) -> ai.AIRequest:
    return ai.AIRequest(
        purpose=kw.pop("purpose", "title"),
        tier=tier,
        messages=[ai.AIMessage("user", kw.pop("prompt", "Schreibe einen Titel."))],
        max_tokens=kw.pop("max_tokens", 500),
        **kw,
    )


def use_claude(db: Session, **ops: Any) -> None:
    update_operations(db, None, {"ai_provider": "claude", "monthly_budget_eur": 50, **ops})
    db.flush()


# --- prices --------------------------------------------------------------------------


def test_cost_follows_the_price_list() -> None:
    assert ai.cost_usd("claude-haiku-5-5", 100_000, 0) == Decimal("0.010000")
    assert ai.cost_usd("claude-haiku-5-5", 0, 1_000_000) == Decimal("0.500000")
    assert ai.cost_usd("claude-sonnet-5-5", 1000, 200) == Decimal("0.004000")
    # Haiku is dearer above 100,000 prompt tokens
    assert ai.cost_usd("claude-haiku-5-5", 200_000, 0) == Decimal("0.100000")
    # unknown model: charged high, never low
    assert ai.cost_usd("claude-unknown", 1_000_000, 0) == Decimal("5.000000")


def test_worst_case_covers_every_output_token() -> None:
    settings = get_settings()
    req = request(max_tokens=1000)
    assert ai.worst_case_usd(settings, req) >= ai.cost_usd("claude-haiku-5-5", 0, 1000)


# --- mock ----------------------------------------------------------------------------


def test_mock_is_default_and_free(db: Session, fake_client: FakeClient) -> None:
    result = ai.generate(db, get_settings(), request())
    assert result.provider == "mock"
    assert result.cost_usd == 0
    assert "[Testantwort]" in result.text
    assert fake_client.calls == []
    call = db.get(AICall, result.call_id)
    assert call is not None and call.status == AICallStatus.SUCCEEDED and call.provider == "mock"
    assert db.scalar(select(Cost).where(Cost.category == CostCategory.AI)) is None


def test_mock_uses_caller_data(db: Session) -> None:
    req = request(mock=lambda r: f"Mock für {r.purpose}")
    assert ai.generate(db, get_settings(), req).text == "Mock für title"


def test_request_limits_are_checked(db: Session) -> None:
    settings = get_settings()
    with pytest.raises(ValueError, match="max_tokens"):
        ai.generate(db, settings, request(max_tokens=20_000))
    with pytest.raises(ValueError, match="characters"):
        ai.generate(db, settings, request(prompt="x" * (settings.ai_max_input_chars + 1)))


# --- conditions for live calls -------------------------------------------------------


def test_claude_without_key_is_blocked_not_mocked(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    settings = get_settings().model_copy(update={"paid_api_calls_enabled": True})
    with pytest.raises(ai.AIBlockedError) as exc:
        ai.generate(db, settings, request())
    assert exc.value.code == "no_key"
    assert fake_client.calls == []
    blocked = db.scalars(select(AICall).where(AICall.status == AICallStatus.BLOCKED)).all()
    assert len(blocked) == 1


def test_paid_calls_switch_blocks_live_calls(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    settings = live_settings(paid_api_calls_enabled=False)
    with pytest.raises(ai.AIBlockedError) as exc:
        ai.generate(db, settings, request())
    assert exc.value.code == "paid_calls_off"
    assert fake_client.calls == []


def test_emergency_stop_blocks_live_calls(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    with pytest.raises(ai.AIBlockedError) as exc:
        ai.generate(db, live_settings(emergency_stop=True), request())
    assert exc.value.code == "emergency_stop"
    assert fake_client.calls == []


def test_eur_budget_blocks_live_calls(db: Session, fake_client: FakeClient) -> None:
    use_claude(db, monthly_budget_eur=0)
    with pytest.raises(ai.AIBlockedError) as exc:
        ai.generate(db, live_settings(), request())
    assert exc.value.code == "budget"
    assert fake_client.calls == []


# --- live calls (fake client) --------------------------------------------------------


def test_live_text_call_is_booked(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    result = ai.generate(db, live_settings(), request(content_project_id=None))
    assert result.provider == "claude"
    assert result.text == "Antwort von Claude"
    assert result.cost_usd == ai.cost_usd("claude-haiku-5-5", 1000, 200)
    params = fake_client.calls[0]
    assert params["model"] == "claude-haiku-5-5"
    assert params["output_config"] == {"effort": "low"}
    call = db.get(AICall, result.call_id)
    assert call is not None and call.status == AICallStatus.SUCCEEDED
    assert call.estimated_usd >= call.cost_usd
    assert call.request_id == "req_test"
    cost = db.get(Cost, call.cost_id)
    assert cost is not None and cost.category == CostCategory.AI
    assert cost.amount_eur == (call.cost_usd * Decimal("0.92")).quantize(Decimal("0.0001"))


def test_reasoning_tier_uses_sonnet_with_fallback(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    ai.generate(db, live_settings(), request("reasoning", purpose="chat"))
    params = fake_client.calls[0]
    assert params["model"] == "claude-sonnet-5-5"
    assert params["fallbacks"] == [{"model": "claude-sonnet-5"}]
    assert params["betas"] == ["server-side-fallback-2026-07-01"]


def test_refusal_is_reported_and_booked(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    fake_client.stop_reason = "refusal"
    with pytest.raises(ai.AIRefusedError):
        ai.generate(db, live_settings(), request())
    call = db.scalars(select(AICall).order_by(AICall.id.desc())).first()
    assert call is not None and call.status == AICallStatus.REFUSED and call.cost_usd > 0


def test_api_error_marks_call_failed(db: Session, fake_client: FakeClient) -> None:
    use_claude(db)
    fake_client.error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    with pytest.raises(ai.AIFailedError, match="nicht erreichbar"):
        ai.generate(db, live_settings(), request())
    call = db.scalars(select(AICall).order_by(AICall.id.desc())).first()
    assert call is not None and call.status == AICallStatus.FAILED and call.cost_usd == 0
    _spent, reserved = ai.month_usage(db)
    assert reserved == 0


# --- the hard monthly cap ------------------------------------------------------------


def test_cap_never_above_server_maximum(db: Session) -> None:
    update_operations(db, None, {"ai_monthly_cap_usd": 500})
    assert ai.cap_usd(db, get_settings()) == Decimal("20.000000")
    update_operations(db, None, {"ai_monthly_cap_usd": 5})
    assert ai.cap_usd(db, get_settings()) == Decimal("5.000000")


def test_call_that_could_exceed_the_cap_is_not_sent(db: Session, fake_client: FakeClient) -> None:
    use_claude(db, ai_monthly_cap_usd=0.01)
    settings = live_settings()
    # Sonnet with 1,000 output tokens may cost up to 1 cent, plus the prompt: too much
    with pytest.raises(ai.AIBlockedError) as exc:
        ai.generate(db, settings, request("reasoning", max_tokens=1000))
    assert exc.value.code == "cap"
    assert fake_client.calls == []
    # a small Haiku call still fits
    ai.generate(db, settings, request("text", max_tokens=200))
    assert len(fake_client.calls) == 1


def test_spent_and_reserved_count_against_the_cap(db: Session, fake_client: FakeClient) -> None:
    use_claude(db, ai_monthly_cap_usd=1)
    db.add(
        AICall(
            purpose="chat",
            tier="reasoning",
            provider="claude",
            model="claude-sonnet-5-5",
            status=AICallStatus.SUCCEEDED,
            cost_usd=Decimal("0.70"),
        )
    )
    db.add(
        AICall(
            purpose="chat",
            tier="reasoning",
            provider="claude",
            model="claude-sonnet-5-5",
            status=AICallStatus.RESERVED,
            estimated_usd=Decimal("0.29"),
        )
    )
    db.flush()
    st = ai.status(db, live_settings())
    assert st.live is True
    assert st.remaining_usd == Decimal("0.010000")
    with pytest.raises(ai.AIBlockedError):
        ai.generate(db, live_settings(), request("reasoning", max_tokens=2000))


def test_stale_reservation_is_closed_with_its_estimate(db: Session) -> None:
    old = AICall(
        purpose="chat",
        tier="reasoning",
        provider="claude",
        model="claude-sonnet-5-5",
        status=AICallStatus.RESERVED,
        estimated_usd=Decimal("0.05"),
        created_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db.add(old)
    db.flush()
    assert ai.expire_stale_reservations(db) == 1
    assert old.status == AICallStatus.FAILED and old.cost_usd == Decimal("0.05")


# --- API -----------------------------------------------------------------------------


def test_status_usage_and_test_call(api: TestClient, make_user: MakeUser, db: Session) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    st = api.get("/api/ai/status").json()
    assert st["provider"] == "mock"
    assert st["live"] is False
    assert st["key_configured"] is False
    assert Decimal(st["cap_usd"]) == Decimal(20)
    assert st["model_text"] == "claude-haiku-5-5"
    assert st["model_reasoning"] == "claude-sonnet-5-5"

    r = api.post("/api/ai/test", headers=headers, json={"prompt": "Hallo", "tier": "reasoning"})
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "mock"
    assert Decimal(r.json()["cost_usd"]) == 0

    usage = api.get("/api/ai/usage").json()
    assert usage["recent"][0]["purpose"] == "test"
    assert usage["by_purpose"][0]["key"] == "test"
    assert api.get("/api/ai/status").json()["calls_this_month"] == 1


def test_claude_selected_without_key_answers_409(
    api: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    r = api.patch("/api/settings/operations", headers=headers, json={"ai_provider": "claude"})
    assert r.status_code == 200
    r = api.post("/api/ai/test", headers=headers, json={"prompt": "Hallo"})
    assert r.status_code == 409
    assert "Schlüssel" in r.json()["detail"]
    st = api.get("/api/ai/status").json()
    assert st["provider"] == "claude" and st["live"] is False and st["blocked_this_month"] == 1


def test_cap_above_maximum_is_refused(api: TestClient, make_user: MakeUser) -> None:
    make_user()
    headers = login(api, "admin@example.com")
    r = api.patch("/api/settings/operations", headers=headers, json={"ai_monthly_cap_usd": 25})
    assert r.status_code == 422
    r = api.patch("/api/settings/operations", headers=headers, json={"ai_monthly_cap_usd": 10})
    assert r.status_code == 200
    assert Decimal(api.get("/api/ai/status").json()["cap_usd"]) == Decimal(10)


def test_only_admins_send_test_calls(api: TestClient, make_user: MakeUser) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    headers = login(api, "op@example.com")
    assert api.post("/api/ai/test", headers=headers, json={"prompt": "x"}).status_code == 403
    assert api.get("/api/ai/status").status_code == 200
