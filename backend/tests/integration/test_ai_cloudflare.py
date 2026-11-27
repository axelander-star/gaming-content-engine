"""Free AI provider ``cloudflare`` (Workers AI text model, HTTP mocked)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AICallStatus, Language, PlatformCode
from models import ContentProject, Cost
from models.ai import AICall
from services import ai, channel_setup
from services.controls import update_operations
from services.seed import seed_base_data

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(
        update={
            "cloudflare_ai_account_id": "acc1",
            "cloudflare_ai_token": SecretStr("tok"),
            "trend_sources_mode": "mock",
        }
    )


@pytest.fixture
def cf(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"requests": [], "status": 200, "answer": "Hallo"}

    def handler(req: httpx.Request) -> httpx.Response:
        state["requests"].append(req)
        if state["status"] != 200:
            return httpx.Response(
                state["status"], json={"success": False, "errors": [{"message": state["error"]}]}
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "response": state["answer"],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 40},
                },
            },
        )

    monkeypatch.setattr(
        ai, "http_client_factory", lambda _s: httpx.Client(transport=httpx.MockTransport(handler))
    )
    yield state


def req() -> ai.AIRequest:
    return ai.AIRequest(
        purpose="title",
        tier="text",
        system="Sei kurz.",
        messages=[ai.AIMessage("user", "Schreibe einen Titel.")],
        max_tokens=300,
    )


def test_cloudflare_call_is_free_and_logged(
    db: Session, settings: Settings, cf: dict[str, Any]
) -> None:
    update_operations(db, None, {"ai_provider": "cloudflare"})
    db.flush()
    result = ai.generate(db, settings, req())
    assert result.text == "Hallo" and result.provider == "cloudflare"
    sent = cf["requests"][0]
    assert str(sent.url) == (
        "https://api.cloudflare.com/client/v4/accounts/acc1/ai/run/"
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    assert sent.headers["authorization"] == "Bearer tok"
    body = json.loads(sent.content)
    assert body["messages"][0] == {"role": "system", "content": "Sei kurz."}
    assert body["max_tokens"] == 300
    call = db.get(AICall, result.call_id)
    assert call is not None and call.status == AICallStatus.SUCCEEDED
    assert call.input_tokens == 120 and call.cost_usd == 0
    assert db.scalars(select(Cost)).all() == []  # nothing booked
    st = ai.status(db, settings)
    assert st.live and st.model_text.startswith("@cf/")


def test_cloudflare_quota_and_missing_token(
    db: Session, settings: Settings, cf: dict[str, Any]
) -> None:
    update_operations(db, None, {"ai_provider": "cloudflare"})
    db.flush()
    cf["status"], cf["error"] = 429, "daily free allocation of 10,000 neurons used"
    with pytest.raises(ai.AIFailedError, match="Tageskontingent"):
        ai.generate(db, settings, req())
    no_key = settings.model_copy(update={"cloudflare_ai_token": SecretStr("")})
    with pytest.raises(ai.AIBlockedError) as err:
        ai.generate(db, no_key, req())
    assert err.value.code == "no_key"


def test_channel_texts_come_from_cloudflare(
    db: Session, settings: Settings, cf: dict[str, Any]
) -> None:
    seed_base_data(db)
    project = ContentProject(slug="fakten", name="Krasse Fakten", languages=["de"])
    db.add(project)
    update_operations(db, None, {"ai_provider": "cloudflare"})
    db.flush()
    cf["answer"] = json.dumps(
        {
            "display_name": "Faktenbombe",
            "alternatives": [{"name": "Hirnfutter", "reason": "Neugier-Lücke"}],
            "handles": ["faktenbombe"],
            "bio": "Wusstest du das? Jeden Tag ein Fakt, der dich umhaut.",
            "tagline": "Täglich ein Aha",
        }
    )
    texts = channel_setup.write_texts(db, settings, project, PlatformCode.YOUTUBE, Language.DE)
    assert texts.display_name == "Faktenbombe" and texts.source == "cloudflare"


def test_own_idea_reaches_the_ai(db: Session, settings: Settings, cf: dict[str, Any]) -> None:
    seed_base_data(db)
    project = ContentProject(slug="fakten", name="Krasse Fakten", languages=["de"])
    db.add(project)
    db.flush()
    task = channel_setup.prepare_one(db, settings, project, PlatformCode.YOUTUBE, Language.DE)
    update_operations(db, None, {"ai_provider": "cloudflare"})
    db.flush()
    cf["answer"] = json.dumps(
        {
            "display_name": "Hirnexplosion",
            "alternatives": [],
            "handles": ["hirnexplosion"],
            "bio": "Boom.",
            "tagline": "x",
        }
    )
    channel_setup.research_again(db, settings, task, part="name", idea="was mit Gehirn")
    prompt = json.loads(cf["requests"][-1].content)["messages"][-1]["content"]
    assert "was mit Gehirn" in prompt
    assert task.display_name == "Hirnexplosion"


def test_assistant_uses_free_model_while_provider_is_test(
    db: Session, settings: Settings, cf: dict[str, Any]
) -> None:
    """prefer_free: with Cloudflare set up (IMAGE_AI_MODE=cloudflare), the channel
    assistant writes real texts although the operator setting is still "mock"."""
    update_operations(db, None, {"ai_provider": "mock"})
    db.flush()
    free = ai.AIRequest(**{**req().__dict__, "prefer_free": True})
    assert ai.generate(db, settings, free).provider == "mock"  # image AI mode off
    on = settings.model_copy(update={"image_ai_mode": "cloudflare"})
    assert ai.generate(db, on, free).provider == "cloudflare"
    assert ai.generate(db, on, req()).provider == "mock"  # others stay on test
