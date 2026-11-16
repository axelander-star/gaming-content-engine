"""AI layer (extension phase E3): one entry point for every text-model request.

Two tiers, chosen by the operator on 15.11.2026:

* ``text``      – short texts (titles, descriptions, hooks): ``AI_MODEL_TEXT``
                  (default Claude Haiku 5.5)
* ``reasoning`` – chat, ideas, planning: ``AI_MODEL_REASONING``
                  (default Claude Sonnet 5.5)

Two providers:

* ``mock``   – default. No network, no cost; the caller may pass ``mock`` to get
               useful domain data back, otherwise a short placeholder text.
* ``claude`` – the Claude API through the official ``anthropic`` SDK. Used only if
               *all* of these hold: the operator selected ``claude`` in the
               settings, ``ANTHROPIC_API_KEY`` is set on the server,
               ``PAID_API_CALLS_ENABLED=true``, no emergency stop, the EUR budget
               allows it, and the call fits under the monthly AI cap.

Hard cap: before a live call its worst-case cost (prompt size estimate plus
``max_tokens`` at the model's output price) is *reserved* under the monthly cap
inside a PostgreSQL advisory lock, so parallel calls cannot overrun it together.
After the call the real cost from the token usage replaces the reservation and is
booked into ``costs`` (category ``ai``) in EUR.

Every call (also mock and blocked ones) is a row in ``ai_calls``. This module
commits the session after reserving and after booking.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import AICallStatus, CostCategory
from models.ai import AICall
from models.control import Cost
from services import budget
from services.controls import effective_controls, get_operations

Tier = Literal["text", "reasoning"]
MOCK = "mock"
CLAUDE = "claude"
PROVIDERS = (MOCK, CLAUDE)

#: Advisory lock key that serialises the cap check of live calls.
_CAP_LOCK = 0x41_49_43_41_50  # "AICAP"

#: Prices in US dollars per million tokens: input, output, cache read, cache write.
#: Source: Anthropic price list, as of 03.11.2026. Unknown models are charged at
#: ``_FALLBACK_PRICE`` so that a surprise never undercounts.
PRICES_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10"), Decimal("0.10"), Decimal("2.50")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10"), Decimal("0.20"), Decimal("2.50")),
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
}
#: Claude Haiku 5.5 costs more above 100,000 prompt tokens.
_HAIKU_LONG = (Decimal("0.50"), Decimal("2.50"), Decimal("0.05"), Decimal("0.625"))
_FALLBACK_PRICE = (Decimal("5"), Decimal("25"), Decimal("0.50"), Decimal("6.25"))
#: Claude Sonnet 5.5 may decline a request for safety reasons; the API then retries it
#: on this model inside the same call (server-side fallback, same price).
_SONNET_FALLBACK = "claude-sonnet-5"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: Characters per token used for the prompt estimate (conservative: real text has more).
_CHARS_PER_TOKEN = 3
_MTOK = Decimal(1_000_000)
_USD = Decimal("0.000001")


class AIError(Exception):
    """Base class; ``code`` is a short machine-readable reason."""

    code = "error"


class AIBlockedError(AIError):
    """The call was not sent (switch, key, budget or monthly cap)."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class AIRefusedError(AIError):
    code = "refused"


class AIFailedError(AIError):
    code = "failed"


@dataclass(frozen=True)
class AIMessage:
    role: Literal["user", "assistant"]
    #: Plain text, or content blocks (tool use: the assistant's blocks unchanged,
    #: then a user message with ``tool_result`` blocks).
    content: str | list[dict[str, Any]]


@dataclass
class AIRequest:
    purpose: str
    tier: Tier
    messages: list[AIMessage]
    system: str = ""
    max_tokens: int = 1024
    #: Answer used in mock mode; without it the mock returns a short placeholder.
    mock: Callable[[AIRequest], str] | None = None
    content_project_id: int | None = None
    agent_run_id: int | None = None
    user_id: int | None = None
    #: Lower effort for short texts and chat keeps thinking and cost small.
    effort: Literal["low", "medium", "high"] = "low"
    #: Client tools (JSON schema definitions). The AI layer never runs them; the
    #: caller executes ``tool_use`` blocks and sends results in the next request.
    tools: list[dict[str, Any]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    model: str
    call_id: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    #: Response content blocks as dicts (text, tool_use, thinking …).
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


@dataclass(frozen=True)
class AIStatus:
    provider: str
    live: bool
    reason: str | None
    key_configured: bool
    paid_calls_enabled: bool
    cap_usd: Decimal
    cap_max_usd: Decimal
    spent_usd: Decimal
    reserved_usd: Decimal
    remaining_usd: Decimal
    model_text: str
    model_reasoning: str


# --- prices and estimates ---------------------------------------------------------


def _q(value: Decimal) -> Decimal:
    return value.quantize(_USD, rounding=ROUND_HALF_UP)


def prices_for(model: str, input_tokens: int = 0) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if model == "claude-haiku-5-5" and input_tokens > 100_000:
        return _HAIKU_LONG
    return PRICES_USD_PER_MTOK.get(model, _FALLBACK_PRICE)


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    prompt = input_tokens + cache_read_tokens + cache_write_tokens
    p_in, p_out, p_read, p_write = prices_for(model, prompt)
    total = (
        Decimal(input_tokens) * p_in
        + Decimal(output_tokens) * p_out
        + Decimal(cache_read_tokens) * p_read
        + Decimal(cache_write_tokens) * p_write
    ) / _MTOK
    return _q(total)


#: One image block costs at most about this many tokens (images are scaled to 1568 px).
_IMAGE_TOKENS = 1600


def _chars(content: str | list[dict[str, Any]]) -> int:
    if isinstance(content, str):
        return len(content)
    images = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "image")
    rest = [b for b in content if not (isinstance(b, dict) and b.get("type") == "image")]
    return len(json.dumps(rest)) + images * _IMAGE_TOKENS * _CHARS_PER_TOKEN


def prompt_chars(req: AIRequest) -> int:
    tools = len(json.dumps(req.tools)) if req.tools else 0
    return len(req.system) + tools + sum(_chars(m.content) for m in req.messages)


def estimate_input_tokens(req: AIRequest) -> int:
    # message framing adds a few tokens per message
    return prompt_chars(req) // _CHARS_PER_TOKEN + 16 * (len(req.messages) + 1)


def model_for(settings: Settings, tier: Tier) -> str:
    return settings.ai_model_text if tier == "text" else settings.ai_model_reasoning


def worst_case_usd(settings: Settings, req: AIRequest) -> Decimal:
    """Upper bound of one call: estimated prompt plus every allowed output token."""
    return cost_usd(model_for(settings, req.tier), estimate_input_tokens(req), req.max_tokens)


# --- cap and status ---------------------------------------------------------------


def _month_start(now: datetime | None = None) -> datetime:
    return budget.month_start(now)


def month_usage(session: Session, now: datetime | None = None) -> tuple[Decimal, Decimal]:
    """(booked cost, open reservations) of live calls this month, in US dollars."""
    start = _month_start(now)
    spent = session.scalar(
        select(func.coalesce(func.sum(AICall.cost_usd), 0)).where(
            AICall.created_at >= start, AICall.status != AICallStatus.RESERVED
        )
    )
    reserved = session.scalar(
        select(func.coalesce(func.sum(AICall.estimated_usd), 0)).where(
            AICall.created_at >= start, AICall.status == AICallStatus.RESERVED
        )
    )
    return Decimal(spent or 0), Decimal(reserved or 0)


#: A reservation older than this belongs to a call that never finished (crash).
STALE_AFTER_SECONDS = 30 * 60


def expire_stale_reservations(session: Session, now: datetime | None = None) -> int:
    """Close reservations of calls that never finished.

    Whether the API billed such a call is unknown, so the reserved worst case is
    kept as its cost: the cap may overcount, never undercount.
    """
    now = now or datetime.now(UTC)
    stale = session.scalars(
        select(AICall).where(
            AICall.status == AICallStatus.RESERVED,
            AICall.created_at < now - timedelta(seconds=STALE_AFTER_SECONDS),
        )
    ).all()
    for call in stale:
        call.status = AICallStatus.FAILED
        call.cost_usd = call.estimated_usd
        call.error = "Aufruf nicht abgeschlossen; reservierte Kosten werden angerechnet"
        call.finished_at = now
    return len(stale)


def cap_usd(session: Session, settings: Settings) -> Decimal:
    """Effective monthly cap: the operator's value, never above the server maximum."""
    chosen = Decimal(str(get_operations(session).ai_monthly_cap_usd))
    return _q(min(chosen, Decimal(str(settings.ai_monthly_cap_usd_max))))


def selected_provider(session: Session) -> str:
    provider = get_operations(session).ai_provider
    return provider if provider in PROVIDERS else MOCK


def _live_problem(session: Session, settings: Settings) -> tuple[str, str] | None:
    """Why a live call cannot happen right now (code, German reason) – or ``None``."""
    if selected_provider(session) != CLAUDE:
        return ("mock", "KI-Anbieter ist auf Test (Mock) gestellt")
    if not settings.anthropic_api_key.get_secret_value():
        return ("no_key", "Kein Claude-API-Schlüssel auf dem Server hinterlegt")
    controls = effective_controls(session, settings)
    if controls.emergency_stop:
        return ("emergency_stop", "Not-Aus ist aktiv")
    if not controls.paid_api_calls_enabled:
        return ("paid_calls_off", "Kostenpflichtige API-Aufrufe sind gesperrt")
    return None


def status(session: Session, settings: Settings) -> AIStatus:
    spent, reserved = month_usage(session)
    cap = cap_usd(session, settings)
    problem = _live_problem(session, settings)
    return AIStatus(
        provider=selected_provider(session),
        live=problem is None,
        reason=None if problem is None else problem[1],
        key_configured=bool(settings.anthropic_api_key.get_secret_value()),
        paid_calls_enabled=effective_controls(session, settings).paid_api_calls_enabled,
        cap_usd=cap,
        cap_max_usd=_q(Decimal(str(settings.ai_monthly_cap_usd_max))),
        spent_usd=_q(spent),
        reserved_usd=_q(reserved),
        remaining_usd=_q(max(Decimal(0), cap - spent - reserved)),
        model_text=settings.ai_model_text,
        model_reasoning=settings.ai_model_reasoning,
    )


# --- providers --------------------------------------------------------------------


@dataclass(frozen=True)
class _Reply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_id: str | None = None
    content: tuple[dict[str, Any], ...] = ()
    stop_reason: str = "end_turn"


def _block_dict(block: Any) -> dict[str, Any]:
    if hasattr(block, "to_dict"):
        return dict(block.to_dict())
    return dict(vars(block))


def _mock_reply(req: AIRequest, model: str) -> _Reply:
    if req.mock is not None:
        answer = req.mock(req)
    else:
        last = req.messages[-1].content if req.messages else ""
        last_text = last if isinstance(last, str) else json.dumps(last)
        answer = f"[Testantwort] {req.purpose}: {' '.join(last_text.split())[:160]}"
    return _Reply(
        text=answer,
        model=model,
        input_tokens=estimate_input_tokens(req),
        output_tokens=max(1, len(answer) // _CHARS_PER_TOKEN),
        content=({"type": "text", "text": answer},),
    )


#: Builds the SDK client; replaced in tests so no request ever leaves the machine.
ClientFactory = Callable[[Settings], Any]


def _default_client(settings: Settings) -> Any:
    import anthropic  # imported lazily: mock mode needs no SDK

    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.ai_request_timeout_s,
        max_retries=2,
    )


client_factory: ClientFactory = _default_client


def _claude_reply(settings: Settings, req: AIRequest, model: str) -> _Reply:
    import anthropic

    client = client_factory(settings)
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": req.max_tokens,
        "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        "output_config": {"effort": req.effort},
    }
    if req.system:
        params["system"] = req.system
    if req.tools:
        params["tools"] = req.tools
    try:
        if model == "claude-sonnet-5-5":
            response = client.beta.messages.create(
                **params,
                betas=[_FALLBACK_BETA],
                fallbacks=[{"model": _SONNET_FALLBACK}],
            )
        else:
            response = client.messages.create(**params)
    except anthropic.AuthenticationError as exc:
        raise AIFailedError("Claude-API-Schlüssel ungültig") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIFailedError("Claude-API-Schlüssel hat keine Berechtigung") from exc
    except anthropic.RateLimitError as exc:
        raise AIFailedError("Claude-API: Ratenlimit erreicht, später erneut versuchen") from exc
    except anthropic.APIStatusError as exc:
        raise AIFailedError(f"Claude-API-Fehler {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIFailedError("Claude-API nicht erreichbar") from exc

    usage = response.usage
    reply = _Reply(
        text="".join(b.text for b in response.content if getattr(b, "type", None) == "text"),
        model=str(response.model or model),
        input_tokens=int(usage.input_tokens or 0),
        output_tokens=int(usage.output_tokens or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        request_id=getattr(response, "_request_id", None),
        content=tuple(_block_dict(b) for b in response.content),
        stop_reason=str(response.stop_reason or "end_turn"),
    )
    if response.stop_reason == "refusal":
        raise _RefusalError(reply)
    return reply


class _RefusalError(Exception):
    def __init__(self, reply: _Reply) -> None:
        super().__init__("refusal")
        self.reply = reply


# --- entry point ------------------------------------------------------------------


def _record_blocked(
    session: Session, req: AIRequest, provider: str, model: str, code: str, reason: str
) -> AIBlockedError:
    session.add(
        AICall(
            purpose=req.purpose,
            tier=req.tier,
            provider=provider,
            model=model,
            status=AICallStatus.BLOCKED,
            error=f"{code}: {reason}",
            finished_at=datetime.now(UTC),
            content_project_id=req.content_project_id,
            agent_run_id=req.agent_run_id,
            user_id=req.user_id,
        )
    )
    session.commit()
    return AIBlockedError(code, reason)


def _validate(settings: Settings, req: AIRequest) -> None:
    if not req.messages or req.messages[-1].role != "user":
        raise ValueError("the last message must come from the user")
    if not 1 <= req.max_tokens <= 16_000:
        raise ValueError("max_tokens must be between 1 and 16000")
    if prompt_chars(req) > settings.ai_max_input_chars:
        raise ValueError(f"prompt longer than {settings.ai_max_input_chars} characters")


def generate(session: Session, settings: Settings, req: AIRequest) -> AIResult:
    """Run one request through the selected provider, within budget and cap.

    Raises :class:`AIBlockedError` if a live call is not allowed (and never falls
    back to mock silently while ``claude`` is selected), :class:`AIRefusedError`
    if the model declined, :class:`AIFailedError` on API errors.
    """
    _validate(settings, req)
    model = model_for(settings, req.tier)
    provider = selected_provider(session)

    if provider == MOCK:
        reply = _mock_reply(req, model)
        call = AICall(
            purpose=req.purpose,
            tier=req.tier,
            provider=MOCK,
            model=model,
            status=AICallStatus.SUCCEEDED,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            finished_at=datetime.now(UTC),
            duration_ms=0,
            content_project_id=req.content_project_id,
            agent_run_id=req.agent_run_id,
            user_id=req.user_id,
        )
        session.add(call)
        session.commit()
        return AIResult(
            reply.text,
            MOCK,
            model,
            call.id,
            reply.input_tokens,
            reply.output_tokens,
            Decimal(0),
            list(reply.content),
            reply.stop_reason,
        )

    problem = _live_problem(session, settings)
    if problem is not None:
        raise _record_blocked(session, req, provider, model, *problem)

    estimate = worst_case_usd(settings, req)
    eur_estimate = estimate * Decimal(str(settings.eur_per_usd))
    decision = budget.authorize_paid_call(session, settings, eur_estimate)
    if not decision.allowed:
        raise _record_blocked(session, req, provider, model, "budget", decision.reason)

    # Reserve the worst case under the monthly cap; the lock makes check+insert atomic.
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CAP_LOCK})
    expire_stale_reservations(session)
    spent, reserved = month_usage(session)
    cap = cap_usd(session, settings)
    if spent + reserved + estimate > cap:
        raise _record_blocked(
            session,
            req,
            provider,
            model,
            "cap",
            f"KI-Monatsgrenze {cap} $ erreicht (verbraucht {_q(spent)} $, "
            f"reserviert {_q(reserved)} $, dieser Aufruf bis {estimate} $)",
        )
    call = AICall(
        purpose=req.purpose,
        tier=req.tier,
        provider=provider,
        model=model,
        status=AICallStatus.RESERVED,
        estimated_usd=estimate,
        content_project_id=req.content_project_id,
        agent_run_id=req.agent_run_id,
        user_id=req.user_id,
    )
    session.add(call)
    session.commit()  # releases the lock; the reservation now counts for everyone

    started = time.monotonic()
    try:
        reply = _claude_reply(settings, req, model)
    except _RefusalError as refusal:
        _book(session, settings, call, refusal.reply, AICallStatus.REFUSED, started)
        raise AIRefusedError("Claude hat die Anfrage abgelehnt") from None
    except AIFailedError as exc:
        call.status = AICallStatus.FAILED
        call.error = str(exc)[:2000]
        call.finished_at = datetime.now(UTC)
        call.duration_ms = int((time.monotonic() - started) * 1000)
        session.commit()
        raise
    _book(session, settings, call, reply, AICallStatus.SUCCEEDED, started)
    return AIResult(
        reply.text,
        provider,
        reply.model,
        call.id,
        reply.input_tokens,
        reply.output_tokens,
        call.cost_usd,
        list(reply.content),
        reply.stop_reason,
    )


def _book(
    session: Session,
    settings: Settings,
    call: AICall,
    reply: _Reply,
    final: AICallStatus,
    started: float,
) -> None:
    """Replace the reservation with the real cost and book it into the EUR costs."""
    usd = cost_usd(
        reply.model,
        reply.input_tokens,
        reply.output_tokens,
        reply.cache_read_tokens,
        reply.cache_write_tokens,
    )
    call.status = final
    call.model = reply.model[:64]
    call.input_tokens = reply.input_tokens
    call.output_tokens = reply.output_tokens
    call.cache_read_tokens = reply.cache_read_tokens
    call.cache_write_tokens = reply.cache_write_tokens
    call.cost_usd = usd
    call.request_id = reply.request_id
    call.finished_at = datetime.now(UTC)
    call.duration_ms = int((time.monotonic() - started) * 1000)
    if usd > 0:
        cost = Cost(
            category=CostCategory.AI,
            provider="anthropic",
            amount_eur=(usd * Decimal(str(settings.eur_per_usd))).quantize(Decimal("0.0001")),
            quantity=Decimal(reply.input_tokens + reply.output_tokens),
            unit="tokens",
            agent_run_id=call.agent_run_id,
            description=f"{call.purpose} · {reply.model}",
        )
        session.add(cost)
        session.flush()
        call.cost_id = cost.id
    session.commit()


__all__ = [
    "CLAUDE",
    "MOCK",
    "PRICES_USD_PER_MTOK",
    "AIBlockedError",
    "AIError",
    "AIFailedError",
    "AIMessage",
    "AIRefusedError",
    "AIRequest",
    "AIResult",
    "AIStatus",
    "cap_usd",
    "cost_usd",
    "expire_stale_reservations",
    "generate",
    "month_usage",
    "status",
    "worst_case_usd",
]
