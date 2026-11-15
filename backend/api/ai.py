"""AI layer: status, monthly cap, usage and a test call (extension phase E3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from core.enums import AICallStatus
from models.ai import AICall
from models.projects import ContentProject
from services import ai, audit, budget

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(csrf_protect)])


class AIStatusOut(BaseModel):
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
    used_pct: float
    model_text: str
    model_reasoning: str
    prices: dict[str, dict[str, Decimal]]
    calls_this_month: int
    blocked_this_month: int


class UsageGroup(BaseModel):
    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class AICallOut(BaseModel):
    id: int
    created_at: datetime
    purpose: str
    tier: str
    provider: str
    model: str
    status: AICallStatus
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    estimated_usd: Decimal
    duration_ms: int | None
    error: str | None
    content_project: str | None


class AIUsageOut(BaseModel):
    by_purpose: list[UsageGroup]
    by_model: list[UsageGroup]
    recent: list[AICallOut]


class TestIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    tier: ai.Tier = "text"


class TestOut(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    call_id: int


@router.get("/status", response_model=AIStatusOut)
def ai_status(_: Viewer, db: DbSession, settings: AppSettings) -> AIStatusOut:
    st = ai.status(db, settings)
    start = budget.month_start()
    counts = dict(
        db.execute(
            select(AICall.status, func.count(AICall.id))
            .where(AICall.created_at >= start)
            .group_by(AICall.status)
        ).all()
    )
    used = st.spent_usd + st.reserved_usd
    return AIStatusOut(
        provider=st.provider,
        live=st.live,
        reason=st.reason,
        key_configured=st.key_configured,
        paid_calls_enabled=st.paid_calls_enabled,
        cap_usd=st.cap_usd,
        cap_max_usd=st.cap_max_usd,
        spent_usd=st.spent_usd,
        reserved_usd=st.reserved_usd,
        remaining_usd=st.remaining_usd,
        used_pct=round(float(used / st.cap_usd * 100), 1) if st.cap_usd > 0 else 100.0,
        model_text=st.model_text,
        model_reasoning=st.model_reasoning,
        prices={
            model: {
                "input": ai.prices_for(model)[0],
                "output": ai.prices_for(model)[1],
            }
            for model in (st.model_text, st.model_reasoning)
        },
        calls_this_month=int(sum(counts.values())),
        blocked_this_month=int(counts.get(AICallStatus.BLOCKED, 0)),
    )


def _groups(db: DbSession, column: object) -> list[UsageGroup]:
    rows = db.execute(
        select(
            column,  # type: ignore[call-overload]
            func.count(AICall.id),
            func.coalesce(func.sum(AICall.input_tokens), 0),
            func.coalesce(func.sum(AICall.output_tokens), 0),
            func.coalesce(func.sum(AICall.cost_usd), 0),
        )
        .where(AICall.created_at >= budget.month_start())
        .group_by(column)
        .order_by(func.sum(AICall.cost_usd).desc(), func.count(AICall.id).desc())
    ).all()
    return [
        UsageGroup(
            key=str(key), calls=int(n), input_tokens=int(i), output_tokens=int(o), cost_usd=c
        )
        for key, n, i, o, c in rows
    ]


@router.get("/usage", response_model=AIUsageOut)
def ai_usage(_: Viewer, db: DbSession, limit: int = Query(default=20, ge=1, le=200)) -> AIUsageOut:
    rows = db.execute(
        select(AICall, ContentProject.name)
        .outerjoin(ContentProject, ContentProject.id == AICall.content_project_id)
        .order_by(AICall.created_at.desc(), AICall.id.desc())
        .limit(limit)
    ).all()
    return AIUsageOut(
        by_purpose=_groups(db, AICall.purpose),
        by_model=_groups(db, AICall.model),
        recent=[
            AICallOut(
                id=c.id,
                created_at=c.created_at,
                purpose=c.purpose,
                tier=c.tier,
                provider=c.provider,
                model=c.model,
                status=c.status,
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                cost_usd=c.cost_usd,
                estimated_usd=c.estimated_usd,
                duration_ms=c.duration_ms,
                error=c.error,
                content_project=project,
            )
            for c, project in rows
        ],
    )


@router.post("/test", response_model=TestOut)
def ai_test(body: TestIn, admin: Admin, db: DbSession, settings: AppSettings) -> TestOut:
    """Send one short prompt through the AI layer (mock or, if enabled, Claude)."""
    req = ai.AIRequest(
        purpose="test",
        tier=body.tier,
        messages=[ai.AIMessage("user", body.prompt)],
        system="Antworte kurz auf Deutsch.",
        max_tokens=300,
        user_id=admin.id,
    )
    try:
        result = ai.generate(db, settings, req)
    except ai.AIBlockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    except ai.AIRefusedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ai.AIFailedError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    audit.record(
        db,
        "ai.test",
        user_id=admin.id,
        entity_type="ai_calls",
        entity_id=result.call_id,
        after={
            "provider": result.provider,
            "model": result.model,
            "cost_usd": str(result.cost_usd),
        },
    )
    db.commit()
    return TestOut(
        text=result.text,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        call_id=result.call_id,
    )
