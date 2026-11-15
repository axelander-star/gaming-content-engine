"""Chat assistant and editorial week plan (extension phase E4)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis import Redis

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import ChatActionStatus
from models.assistant import ChatAction, ChatMessage
from services import assistant, planning
from services.queue import get_redis

router = APIRouter(prefix="/assistant", tags=["assistant"], dependencies=[Depends(csrf_protect)])
planning_router = APIRouter(
    prefix="/planning", tags=["planning"], dependencies=[Depends(csrf_protect)]
)


class ChatActionOut(BaseModel):
    id: int
    created_at: datetime
    tool: str
    args: dict[str, Any]
    summary: str
    status: ChatActionStatus
    undoable: bool
    error: str | None
    undone_at: datetime | None


class ChatMessageOut(BaseModel):
    id: int
    created_at: datetime
    role: str
    text: str
    provider: str | None
    actions: list[ChatActionOut]


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=assistant.MAX_TEXT)


class ChatExchangeOut(BaseModel):
    question: ChatMessageOut
    answer: ChatMessageOut


def _action(a: ChatAction) -> ChatActionOut:
    return ChatActionOut(
        id=a.id,
        created_at=a.created_at,
        tool=a.tool,
        args=a.args,
        summary=a.summary,
        status=a.status,
        undoable=a.undoable and a.status == ChatActionStatus.DONE,
        error=a.error,
        undone_at=a.undone_at,
    )


def _message(m: ChatMessage, actions: list[ChatAction]) -> ChatMessageOut:
    return ChatMessageOut(
        id=m.id,
        created_at=m.created_at,
        role=m.role,
        text=m.text,
        provider=m.provider,
        actions=[_action(a) for a in actions],
    )


@router.get("/messages", response_model=list[ChatMessageOut])
def list_messages(
    user: Viewer, db: DbSession, limit: int = Query(default=50, ge=1, le=200)
) -> list[ChatMessageOut]:
    """The current user's chat history, oldest first."""
    rows = assistant.messages(db, user, limit)
    actions = assistant.actions_for(db, [m.id for m in rows])
    return [_message(m, actions.get(m.id, [])) for m in rows]


@router.post("/messages", response_model=ChatExchangeOut)
def send_message(
    body: ChatIn,
    user: Operator,
    db: DbSession,
    settings: AppSettings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> ChatExchangeOut:
    exchange = assistant.send(db, settings, user, body.text, redis)
    db.refresh(exchange.question)
    db.refresh(exchange.answer)
    return ChatExchangeOut(
        question=_message(exchange.question, []),
        answer=_message(exchange.answer, exchange.actions),
    )


@router.post("/actions/{action_id}/undo", response_model=ChatActionOut)
def undo_action(
    action_id: int, user: Operator, db: DbSession, settings: AppSettings
) -> ChatActionOut:
    action = db.get(ChatAction, action_id)
    if action is None or action.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Aktion nicht gefunden")
    try:
        done = assistant.undo(db, settings, user, action_id)
    except assistant.UndoError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc
    db.commit()
    db.refresh(done)
    return _action(done)


# --- editorial week plan -------------------------------------------------------------


class PlanProjectOut(BaseModel):
    id: int
    name: str
    note: str | None


class PlanDayOut(BaseModel):
    day: date
    weekday: str
    is_today: bool
    projects: list[PlanProjectOut]


class FocusOut(BaseModel):
    id: int
    project_id: int
    project: str
    topic: str
    starts_on: date
    ends_on: date


class WeekPlanOut(BaseModel):
    start: date
    end: date
    today: date
    days: list[PlanDayOut]
    focus: list[FocusOut]


@planning_router.get("/week", response_model=WeekPlanOut)
def week_plan(
    _: Viewer,
    db: DbSession,
    settings: AppSettings,
    start: date | None = None,
) -> WeekPlanOut:
    today = planning.today(settings)
    first = planning.week_start(start or today)
    last = first + timedelta(days=6)
    by_day: dict[date, list[PlanProjectOut]] = {}
    for entry in planning.plan_between(db, first, last):
        by_day.setdefault(entry.day, []).append(
            PlanProjectOut(id=entry.project_id, name=entry.project, note=entry.note)
        )
    days = [first + timedelta(days=i) for i in range(7)]
    return WeekPlanOut(
        start=first,
        end=last,
        today=today,
        days=[
            PlanDayOut(
                day=d,
                weekday=planning.WEEKDAYS_DE[d.weekday()],
                is_today=d == today,
                projects=by_day.get(d, []),
            )
            for d in days
        ],
        focus=[
            FocusOut(
                id=f.id,
                project_id=f.project_id,
                project=f.project,
                topic=f.topic,
                starts_on=f.starts_on,
                ends_on=f.ends_on,
            )
            for f in planning.focus_between(db, first, last)
        ],
    )
