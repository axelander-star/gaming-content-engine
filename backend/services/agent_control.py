"""Pause and resume individual agents (PROJECT_SPEC section 15, "Pausieren einzelner Agenten")."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.control import AgentState
from services import audit


def get_state(session: Session, agent_name: str) -> AgentState | None:
    return session.scalar(select(AgentState).where(AgentState.agent_name == agent_name))


def is_enabled(session: Session, agent_name: str) -> bool:
    state = get_state(session, agent_name)
    return state is None or state.is_enabled


def enabled_map(session: Session) -> dict[str, bool]:
    """All stored switches; agents without a row are enabled."""
    return {s.agent_name: s.is_enabled for s in session.scalars(select(AgentState))}


def set_enabled(
    session: Session,
    agent_name: str,
    enabled: bool,
    user_id: int | None,
    note: str | None = None,
) -> AgentState:
    """Pause (``enabled=False``) or resume an agent. Audited; caller commits."""
    state = get_state(session, agent_name)
    before = True if state is None else state.is_enabled
    if state is None:
        state = AgentState(agent_name=agent_name)
        session.add(state)
    state.is_enabled = enabled
    state.updated_by_user_id = user_id
    state.note = note
    audit.record(
        session,
        "agent.resume" if enabled else "agent.pause",
        user_id=user_id,
        entity_type="agent_states",
        before={"agent": agent_name, "is_enabled": before},
        after={"agent": agent_name, "is_enabled": enabled},
        message=note,
    )
    session.flush()
    return state
