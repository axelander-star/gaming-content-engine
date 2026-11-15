"""Chat assistant (extension phase E4): steer the plan in plain German.

The assistant works through a small set of tools. Every tool that changes
something leaves a :class:`ChatAction` with a snapshot to undo it.

Two modes:

* **mock** (default, free): a rule-based parser understands the common commands
  ("diese Woche GTA 6", "Mittwoch zusätzlich Ernährung", "Status").
* **claude**: Sonnet runs a tool loop through :mod:`services.ai`, so every round
  counts against the monthly AI cap.

There is deliberately **no tool that publishes**. Publishing stays with the
publishing page, the safety gates and the operator's approval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.registry import get_spec
from core.config import Settings
from core.enums import ChatActionStatus, ContentProjectStatus, UserRole
from models.access import User
from models.assistant import ChatAction, ChatMessage
from models.planning import ContentFocus, EditorialDay
from models.projects import DEFAULT_PROJECT_SLUG, ContentProject
from services import agent_control, ai, audit, planning
from services.controls import effective_controls
from services.planning import PlanningError, format_day

MAX_TEXT = 2000
MAX_ROUNDS = 4
MAX_TOOL_CALLS = 12
HISTORY_MESSAGES = 10

ADMIN_TOOLS = {"set_project_status", "start_research"}

# --- tool definitions (sent to Claude) -----------------------------------------------

_DATE = {"type": "string", "description": "Datum im Format JJJJ-MM-TT"}
_PROJECT = {"type": "string", "description": "Name des Themenbereichs, z. B. Gaming"}


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_overview",
        "Liest Themenbereiche, Redaktionsplan der laufenden und nächsten Woche, aktive "
        "Schwerpunkte und den Sicherheitsstatus. Ändert nichts.",
        {},
    ),
    _tool(
        "set_focus",
        "Setzt einen inhaltlichen Schwerpunkt (z. B. GTA 6) in einem Themenbereich für "
        "einen Zeitraum. Bestimmt nicht, wie viele Videos erscheinen.",
        {
            "project": _PROJECT,
            "topic": {"type": "string", "description": "Thema des Schwerpunkts"},
            "start_date": _DATE,
            "end_date": _DATE,
        },
    ),
    _tool(
        "plan_day",
        "Plant einen Themenbereich an einem Tag ein (add) oder nimmt ihn heraus (remove). "
        "Bestimmt nicht, wie viele Videos erscheinen.",
        {
            "date": _DATE,
            "project": _PROJECT,
            "change": {"type": "string", "enum": ["add", "remove"]},
            "note": {"type": "string", "description": "Kurze Notiz oder leerer Text"},
        },
    ),
    _tool(
        "set_project_status",
        "Pausiert einen Themenbereich oder setzt ihn fort. Pausierte Bereiche produzieren "
        "und veröffentlichen nichts. Nur für Admins.",
        {"project": _PROJECT, "status": {"type": "string", "enum": ["active", "paused"]}},
    ),
    _tool(
        "start_research",
        "Startet sofort Recherche und Ideenlabor für einen Themenbereich (bei Gaming "
        "zusätzlich die Trendrecherche). Neue Ideen landen im Ideenlabor. Nur für Admins.",
        {"project": _PROJECT},
    ),
    _tool(
        "list_ideas",
        "Liest die besten offenen Ideen aus dem Ideenlabor mit Bewertung. Ändert nichts. "
        "Leerer Text bei project bedeutet alle Themenbereiche.",
        {"project": {"type": "string", "description": "Themenbereich oder leerer Text"}},
    ),
]

TOOL_NAMES = {t["name"] for t in TOOLS}


# --- execution -----------------------------------------------------------------------


@dataclass
class Context:
    session: Session
    settings: Settings
    user: User
    message: ChatMessage
    redis: Redis | None = None
    actions: list[ChatAction] = field(default_factory=list)


@dataclass(frozen=True)
class Outcome:
    ok: bool
    #: Data for the model (JSON-able) and German text for the mock answer.
    data: dict[str, Any]
    text: str


class ToolError(Exception):
    """A tool call that cannot be carried out (German message)."""


def _parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(f"Ungültiges Datum „{value}“ (erwartet JJJJ-MM-TT)") from None


def _active_project(ctx: Context, name: Any) -> ContentProject:
    return planning.find_project(ctx.session, str(name or ""))


def _record(
    ctx: Context, tool: str, args: dict[str, Any], summary: str, *,
    undoable: bool = False, undo: dict[str, Any] | None = None,
    entity: tuple[str, int] | None = None,
) -> ChatAction:  # fmt: skip
    action = ChatAction(
        message_id=ctx.message.id,
        user_id=ctx.user.id,
        tool=tool,
        args=args,
        summary=summary[:500],
        status=ChatActionStatus.DONE,
        undoable=undoable,
        undo=undo or {},
    )
    ctx.session.add(action)
    ctx.session.flush()
    audit.record(
        ctx.session,
        f"assistant.{tool}",
        user_id=ctx.user.id,
        entity_type=entity[0] if entity else "chat_actions",
        entity_id=entity[1] if entity else action.id,
        after={"args": args, "action_id": action.id},
        message=summary[:500],
    )
    ctx.actions.append(action)
    return action


def _failed(ctx: Context, tool: str, args: dict[str, Any], error: str) -> None:
    action = ChatAction(
        message_id=ctx.message.id,
        user_id=ctx.user.id,
        tool=tool,
        args=args,
        summary=error[:500],
        status=ChatActionStatus.FAILED,
        error=error[:2000],
    )
    ctx.session.add(action)
    ctx.session.flush()
    ctx.actions.append(action)


def overview(session: Session, settings: Settings) -> dict[str, Any]:
    now = planning.today(settings)
    start = planning.week_start(now)
    end = start + timedelta(days=13)
    projects = session.scalars(
        select(ContentProject)
        .where(ContentProject.status != ContentProjectStatus.ARCHIVED)
        .order_by(ContentProject.priority, ContentProject.id)
    ).all()
    plan: dict[str, list[str]] = {}
    for entry in planning.plan_between(session, start, end):
        plan.setdefault(entry.day.isoformat(), []).append(entry.project)
    controls = effective_controls(session, settings)
    return {
        "today": now.isoformat(),
        "projects": [{"name": p.name, "status": p.status.value} for p in projects],
        "plan": plan,
        "focus": [
            {
                "project": f.project,
                "topic": f.topic,
                "from": f.starts_on.isoformat(),
                "to": f.ends_on.isoformat(),
            }
            for f in planning.focus_between(session, now, end)
        ],
        "emergency_stop": controls.emergency_stop,
        "publishing_mode": controls.publishing_mode,
        "ai_provider": ai.selected_provider(session),
    }


def _overview_text(data: dict[str, Any]) -> str:
    status_de = {"active": "aktiv", "paused": "pausiert"}
    lines = [
        "Themenbereiche: "
        + ", ".join(
            f"{p['name']} ({status_de.get(p['status'], p['status'])})" for p in data["projects"]
        )
    ]
    if data["plan"]:
        lines.append("Redaktionsplan:")
        for day, names in sorted(data["plan"].items()):
            lines.append(f"• {format_day(date.fromisoformat(day))}: {', '.join(names)}")
    else:
        lines.append("Für diese und nächste Woche ist noch nichts eingeplant.")
    if data["focus"]:
        lines.append("Schwerpunkte:")
        for f in data["focus"]:
            start = date.fromisoformat(f["from"]).strftime("%d.%m.")
            end = date.fromisoformat(f["to"]).strftime("%d.%m.")
            lines.append(f"• {f['project']}: {f['topic']} ({start}–{end})")
    if data["emergency_stop"]:
        lines.append("Achtung: Der Not-Aus ist aktiv.")
    lines.append(f"Veröffentlichungsmodus: {data['publishing_mode']}.")
    return "\n".join(lines)


def _get_overview(ctx: Context, args: dict[str, Any]) -> Outcome:
    data = overview(ctx.session, ctx.settings)
    return Outcome(True, data, _overview_text(data))


def _set_focus(ctx: Context, args: dict[str, Any]) -> Outcome:
    project = _active_project(ctx, args.get("project"))
    start = _parse_date(args.get("start_date"))
    end = _parse_date(args.get("end_date"))
    focus = planning.add_focus(
        ctx.session, ctx.settings, project, str(args.get("topic") or ""), start, end,
        None, ctx.user.id,
    )  # fmt: skip
    summary = (
        f"Schwerpunkt „{focus.topic}“ für {project.name} vom "
        f"{start.strftime('%d.%m.')} bis {end.strftime('%d.%m.%Y')} gesetzt"
    )
    action = _record(
        ctx, "set_focus", args, summary, undoable=True, undo={"focus_id": focus.id},
        entity=("content_focus", focus.id),
    )  # fmt: skip
    return Outcome(True, {"done": summary, "action_id": action.id}, summary)


def _plan_day(ctx: Context, args: dict[str, Any]) -> Outcome:
    project = _active_project(ctx, args.get("project"))
    day = _parse_date(args.get("date"))
    change = args.get("change")
    note = str(args.get("note") or "").strip() or None
    if change == "add":
        if project.status != ContentProjectStatus.ACTIVE:
            raise ToolError(f"{project.name} ist pausiert; erst fortsetzen, dann einplanen")
        entry = planning.add_day(ctx.session, ctx.settings, day, project, note, ctx.user.id)
        if entry is None:
            text = f"{project.name} war am {format_day(day)} schon eingeplant"
            return Outcome(True, {"unchanged": text}, text)
        summary = f"{project.name} am {format_day(day)} eingeplant"
        action = _record(
            ctx, "plan_day", args, summary, undoable=True,
            undo={"editorial_day_id": entry.id}, entity=("editorial_days", entry.id),
        )  # fmt: skip
        return Outcome(True, {"done": summary, "action_id": action.id}, summary)
    if change == "remove":
        removed = planning.remove_day(ctx.session, ctx.settings, day, project)
        if removed is None:
            text = f"{project.name} war am {format_day(day)} nicht eingeplant"
            return Outcome(True, {"unchanged": text}, text)
        summary = f"{project.name} am {format_day(day)} aus dem Plan genommen"
        action = _record(
            ctx, "plan_day", args, summary, undoable=True,
            undo={"day": day.isoformat(), "project_id": project.id, "note": removed.note},
        )  # fmt: skip
        return Outcome(True, {"done": summary, "action_id": action.id}, summary)
    raise ToolError("change muss add oder remove sein")


def _set_project_status(ctx: Context, args: dict[str, Any]) -> Outcome:
    project = _active_project(ctx, args.get("project"))
    try:
        new = ContentProjectStatus(str(args.get("status")))
    except ValueError:
        raise ToolError("status muss active oder paused sein") from None
    if new == ContentProjectStatus.ARCHIVED:
        raise ToolError("Archivieren geht nur auf der Seite Themenbereiche")
    old = project.status
    word = "fortgesetzt" if new == ContentProjectStatus.ACTIVE else "pausiert"
    if old == new:
        text = f"{project.name} ist bereits {word}"
        return Outcome(True, {"unchanged": text}, text)
    project.status = new
    ctx.session.flush()
    summary = f"Themenbereich {project.name} {word}"
    action = _record(
        ctx, "set_project_status", args, summary, undoable=True,
        undo={"project_id": project.id, "status": old.value},
        entity=("content_projects", project.id),
    )  # fmt: skip
    return Outcome(True, {"done": summary, "action_id": action.id}, summary)


def _start_research(ctx: Context, args: dict[str, Any]) -> Outcome:
    from services.orchestrator import submit

    project = _active_project(ctx, args.get("project"))
    if project.status != ContentProjectStatus.ACTIVE:
        raise ToolError(f"{project.name} ist pausiert")
    names = ["research", "idea_lab"]
    if project.slug == DEFAULT_PROJECT_SLUG:
        names.insert(0, "trend_research")
    for name in names:
        spec = get_spec(name)
        if spec is None or not spec.implemented:
            raise ToolError(f"Agent {name} ist nicht verfügbar")
    if effective_controls(ctx.session, ctx.settings).emergency_stop:
        raise ToolError("Der Not-Aus ist aktiv")
    paused = [n for n in names if not agent_control.is_enabled(ctx.session, n)]
    if paused:
        raise ToolError(f"Pausiert: {', '.join(paused)}")
    if ctx.redis is None:
        raise ToolError("Warteschlange nicht erreichbar")
    jobs = {}
    for name in names:
        payload: dict[str, Any] = {} if name == "trend_research" else {"project_id": project.id}
        jobs[name] = submit(name, payload, priority=True, connection=ctx.redis).id
    summary = f"Recherche und Ideenlabor für {project.name} gestartet"
    action = _record(ctx, "start_research", {**args, "jobs": jobs}, summary)
    return Outcome(True, {"done": summary, "action_id": action.id}, summary)


def _list_ideas(ctx: Context, args: dict[str, Any]) -> Outcome:
    from services.ideas import top_ideas

    name = str(args.get("project") or "").strip()
    project = _active_project(ctx, name) if name and _fold(name) != "alle" else None
    found = top_ideas(ctx.session, project.id if project else None, limit=5)
    data = {
        "ideas": [
            {"id": i.id, "title": i.title, "score": i.score, "format": i.format,
             "pitch": i.pitch[:300]}
            for i in found
        ]
    }  # fmt: skip
    where = f" für {project.name}" if project else ""
    if not found:
        return Outcome(True, data, f"Im Ideenlabor gibt es{where} gerade keine offenen Ideen.")
    lines = [f"Beste offene Ideen{where}:"]
    lines += [f"• {i.title} (Bewertung {i.score})" for i in found]
    lines.append("Übernehmen oder verwerfen kannst du sie im Ideenlabor.")
    return Outcome(True, data, "\n".join(lines))


_HANDLERS = {
    "get_overview": _get_overview,
    "set_focus": _set_focus,
    "plan_day": _plan_day,
    "set_project_status": _set_project_status,
    "start_research": _start_research,
    "list_ideas": _list_ideas,
}


def run_tool(ctx: Context, name: str, args: dict[str, Any]) -> Outcome:
    """Execute one tool call with role checks; failures become failed action cards."""
    args = dict(args or {})
    if name not in _HANDLERS:
        error = f"Unbekanntes Werkzeug {name}"
        _failed(ctx, name[:64], args, error)
        return Outcome(False, {"error": error}, error)
    if name in ADMIN_TOOLS and ctx.user.role != UserRole.ADMIN:
        error = "Dafür sind Admin-Rechte nötig"
        _failed(ctx, name, args, error)
        return Outcome(False, {"error": error}, error)
    try:
        with ctx.session.begin_nested():
            return _HANDLERS[name](ctx, args)
    except (ToolError, PlanningError) as exc:
        _failed(ctx, name, args, str(exc))
        return Outcome(False, {"error": str(exc)}, str(exc))


# --- undo ----------------------------------------------------------------------------


class UndoError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def undo(session: Session, settings: Settings, user: User, action_id: int) -> ChatAction:
    action = session.get(ChatAction, action_id)
    if action is None:
        raise UndoError(404, "Aktion nicht gefunden")
    if not action.undoable or action.status != ChatActionStatus.DONE:
        raise UndoError(409, "Diese Aktion kann nicht rückgängig gemacht werden")
    if action.tool in ADMIN_TOOLS and user.role != UserRole.ADMIN:
        raise UndoError(403, "Dafür sind Admin-Rechte nötig")
    data = action.undo
    if action.tool == "set_focus":
        focus = session.get(ContentFocus, data.get("focus_id"))
        if focus is not None:
            session.delete(focus)
    elif action.tool == "plan_day" and "editorial_day_id" in data:
        entry = session.get(EditorialDay, data["editorial_day_id"])
        if entry is not None:
            session.delete(entry)
    elif action.tool == "plan_day":
        day = date.fromisoformat(data["day"])
        exists = session.scalar(
            select(EditorialDay).where(
                EditorialDay.day == day, EditorialDay.content_project_id == data["project_id"]
            )
        )
        if exists is None and session.get(ContentProject, data["project_id"]) is not None:
            session.add(
                EditorialDay(
                    day=day,
                    content_project_id=data["project_id"],
                    note=data.get("note"),
                    created_by_user_id=user.id,
                )
            )
    elif action.tool == "set_project_status":
        project = session.get(ContentProject, data.get("project_id"))
        if project is None:
            raise UndoError(409, "Themenbereich gibt es nicht mehr")
        if project.status == ContentProjectStatus.ARCHIVED:
            raise UndoError(409, f"{project.name} wurde inzwischen archiviert")
        project.status = ContentProjectStatus(data["status"])
    else:  # pragma: no cover - guarded by ``undoable``
        raise UndoError(409, "Diese Aktion kann nicht rückgängig gemacht werden")
    action.status = ChatActionStatus.UNDONE
    action.undone_at = datetime.now(UTC)
    action.undone_by_user_id = user.id
    session.flush()
    audit.record(
        session,
        "assistant.undo",
        user_id=user.id,
        entity_type="chat_actions",
        entity_id=action.id,
        before={"tool": action.tool, "args": action.args},
        message=f"Rückgängig: {action.summary}",
    )
    return action


# --- mock mode: rule-based parser ----------------------------------------------------

_WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}  # fmt: skip
_PUBLISH = re.compile(r"ver(oe|ö)ffentlich|\bposte|\bposten\b|hochlad|\bupload|\blade .* hoch")
_REMOVE = re.compile(r"\b(kein|keine|keinen|ohne|streich\w*|entfern\w*|raus|nicht)\b")
_WEEK = re.compile(r"\b(diese|dieser|naechste|nächste|kommende)\s+woche\b")
_FILLER = re.compile(
    r"\b(diese|dieser|naechste|nächste|kommende|woche|bitte|mehr|vor allem|den|der|die|das|"
    r"fokus|schwerpunkt|auf|im|in|bei|fuer|für|mit|bereich|themenbereich|zum|thema|"
    r"setz\w*|plane?|mach\w*)\b",
    re.IGNORECASE,
)
_HELP = (
    "Ich verstehe zum Beispiel:\n"
    "• „Status“ – Überblick über Themenbereiche und Plan\n"
    "• „Diese Woche GTA 6“ – Schwerpunkt setzen\n"
    "• „Mittwoch zusätzlich Ernährung“ oder „Freitag kein Gaming“ – Plan ändern\n"
    "• „Ernährung pausieren“ / „Ernährung fortsetzen“\n"
    "• „Recherchiere für Ernährung“ – Recherche und Ideenlabor starten\n"
    "• „Zeig mir die Ideen“ – beste offene Ideen\n"
    "Veröffentlichen kann ich nicht; das bleibt bei dir."
)
REFUSE_PUBLISH = (
    "Veröffentlichen kann ich nicht. Videos gehen nur über die Seite Veröffentlichung, "
    "durch die Sicherheitsprüfungen und mit deiner Freigabe raus."
)


def _fold(text: str) -> str:
    return planning._norm(text)


def _mentioned_projects(session: Session, sentence: str) -> list[ContentProject]:
    folded = _fold(sentence)
    found = []
    for p in session.scalars(
        select(ContentProject)
        .where(ContentProject.status != ContentProjectStatus.ARCHIVED)
        .order_by(ContentProject.priority, ContentProject.id)
    ):
        names = {_fold(p.name), _fold(p.slug)}
        if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", folded) for n in names if n):
            found.append(p)
    return found


def _project_for_topic(session: Session, topic: str) -> ContentProject | None:
    folded = _fold(topic)
    for p in session.scalars(
        select(ContentProject)
        .where(ContentProject.status != ContentProjectStatus.ARCHIVED)
        .order_by(ContentProject.priority, ContentProject.id)
    ):
        if any(_fold(str(s)) and _fold(str(s)) in folded for s in p.subtopics or []):
            return p
    return session.scalar(select(ContentProject).where(ContentProject.slug == DEFAULT_PROJECT_SLUG))


def _days_in(sentence: str, today: date) -> list[date]:
    folded = _fold(sentence)
    days: list[date] = []
    next_week = bool(re.search(r"\b(naechste|kommende)\s+woche\b", folded))
    for word, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{word}s?\b", folded):
            if next_week:
                days.append(planning.week_start(today) + timedelta(days=7 + weekday))
            else:
                days.append(today + timedelta(days=(weekday - today.weekday()) % 7))
    if re.search(r"\bheute\b", folded):
        days.append(today)
    if re.search(r"\buebermorgen\b", folded):
        days.append(today + timedelta(days=2))
    elif re.search(r"\bmorgen\b", folded):
        days.append(today + timedelta(days=1))
    for d, m in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.?", sentence):
        try:
            candidate = date(today.year, int(m), int(d))
        except ValueError:
            continue
        if candidate < today - timedelta(days=planning.MAX_DAYS_BACK):
            candidate = candidate.replace(year=today.year + 1)
        days.append(candidate)
    return sorted(set(days))


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.", r"\1.\2", text)  # "18.11." ends no sentence
    parts = re.split(r"[\n;]+|(?<=[!?])\s+|(?<=\w)\.\s+(?=[A-ZÄÖÜ])", text)
    return [p.strip(" .,") for p in parts if p.strip(" .,")]


@dataclass(frozen=True)
class _Parsed:
    calls: list[tuple[str, dict[str, Any]]]
    replies: list[str]


def parse(session: Session, settings: Settings, text: str) -> _Parsed:
    """Turn a German instruction into tool calls (mock mode)."""
    today = planning.today(settings)
    calls: list[tuple[str, dict[str, Any]]] = []
    replies: list[str] = []
    for sentence in _sentences(text):
        folded = _fold(sentence)
        projects = _mentioned_projects(session, sentence)
        if _PUBLISH.search(folded) or _PUBLISH.search(sentence.lower()):
            replies.append(REFUSE_PUBLISH)
            continue
        if re.search(r"\bideen?\b", folded) and not re.search(r"recherch", folded):
            target = projects[0].name if projects else ""
            calls.append(("list_ideas", {"project": target}))
            continue
        if re.search(r"recherch|trends? (such|find)", folded):
            target = projects[0].name if projects else "Gaming"
            calls.append(("start_research", {"project": target}))
            continue
        if re.search(r"pausier|anhalten", folded):
            if not projects:
                replies.append("Welchen Themenbereich soll ich pausieren?")
            for p in projects:
                calls.append(("set_project_status", {"project": p.name, "status": "paused"}))
            continue
        if re.search(r"fortsetz|fortfuehr|reaktivier|aktivier|wieder (an|starten|aufnehm)", folded):
            if not projects:
                replies.append("Welchen Themenbereich soll ich fortsetzen?")
            for p in projects:
                calls.append(("set_project_status", {"project": p.name, "status": "active"}))
            continue
        days = _days_in(sentence, today)
        if days and projects:
            change = "remove" if _REMOVE.search(folded) else "add"
            for d in days:
                for p in projects:
                    calls.append(
                        ("plan_day",
                         {"date": d.isoformat(), "project": p.name, "change": change, "note": ""})
                    )  # fmt: skip
            continue
        if days:
            replies.append("Welcher Themenbereich soll an dem Tag laufen?")
            continue
        week = _WEEK.search(folded)
        if week:
            start = planning.week_start(today)
            if week.group(1) in ("naechste", "nächste", "kommende"):
                start += timedelta(days=7)
            topic = sentence
            for p in projects:
                topic = re.sub(re.escape(p.name), " ", topic, flags=re.IGNORECASE)
            topic = " ".join(_FILLER.sub(" ", topic).split()).strip(" :,-")
            if projects:
                project = projects[0]
                topic = topic or project.name
            else:
                found = _project_for_topic(session, topic) if topic else None
                if found is None or not topic:
                    replies.append("Welches Thema soll in der Woche im Mittelpunkt stehen?")
                    continue
                project = found
            calls.append(
                ("set_focus",
                 {"project": project.name, "topic": topic, "start_date": start.isoformat(),
                  "end_date": (start + timedelta(days=6)).isoformat()})
            )  # fmt: skip
            continue
        if re.search(r"status|ueberblick|uebersicht|\bplan\b|was steht an|was ist geplant", folded):
            calls.append(("get_overview", {}))
            continue
        replies.append(_HELP)
    if not calls and not replies:
        replies.append(_HELP)
    return _Parsed(calls, replies)


# --- live mode: Claude tool loop -----------------------------------------------------


def system_prompt(session: Session, settings: Settings, user: User) -> str:
    today = planning.today(settings)
    projects = session.scalars(
        select(ContentProject)
        .where(ContentProject.status != ContentProjectStatus.ARCHIVED)
        .order_by(ContentProject.priority, ContentProject.id)
    ).all()
    listing = ", ".join(f"{p.name} ({p.status.value})" for p in projects)
    return (
        "Du bist der Assistent einer privaten KI-Content-Plattform. Du steuerst den "
        "Redaktionsplan mit den Werkzeugen und antwortest kurz auf Deutsch.\n"
        f"Heute ist {format_day(today)} (Zeitzone {settings.timezone}). "
        "Wochen beginnen am Montag.\n"
        f"Themenbereiche: {listing}.\n"
        f"Rolle des Nutzers: {user.role.value}.\n"
        "Regeln:\n"
        "- Du kannst nichts veröffentlichen und nichts hochladen. Bitten darum lehnst du ab "
        "und verweist auf die Seite Veröffentlichung und die Freigabe des Nutzers.\n"
        "- Wie viele Videos ein Kanal bekommt, entscheidet der Publishing-Strategie-Agent "
        "anhand der Daten. Du legst nur Themen, Tage und Schwerpunkte fest.\n"
        "- Inhalte eines Themenbereichs gehören nur auf dessen Kanäle.\n"
        "- Wenn etwas unklar ist, frag kurz nach statt zu raten.\n"
        "- Nenne nach Änderungen in einem Satz, was du getan hast."
    )


def _history(session: Session, user: User, before_id: int) -> list[ai.AIMessage]:
    rows = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user.id, ChatMessage.id < before_id)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_MESSAGES)
        )
    )[::-1]
    messages: list[ai.AIMessage] = []
    for row in rows:
        if not row.text.strip():
            continue
        role: Literal["user", "assistant"] = "user" if row.role == "user" else "assistant"
        if not messages and role != "user":
            continue
        if messages and messages[-1].role == role:
            messages[-1] = ai.AIMessage(role, f"{messages[-1].content}\n\n{row.text}")
        else:
            messages.append(ai.AIMessage(role, row.text))
    if messages and messages[-1].role == "user":
        messages.pop()  # an unanswered message; the new one follows
    return messages


def _live(ctx: Context, text: str) -> tuple[str, list[int]]:
    """Run the tool loop; returns the answer and the ai_call ids."""
    system = system_prompt(ctx.session, ctx.settings, ctx.user)
    messages = [*_history(ctx.session, ctx.user, ctx.message.id), ai.AIMessage("user", text)]
    call_ids: list[int] = []
    tool_calls = 0
    answer = ""
    for _ in range(MAX_ROUNDS):
        result = ai.generate(
            ctx.session,
            ctx.settings,
            ai.AIRequest(
                purpose="chat",
                tier="reasoning",
                messages=messages,
                system=system,
                max_tokens=2000,
                tools=TOOLS,
                user_id=ctx.user.id,
            ),
        )
        call_ids.append(result.call_id)
        answer = result.text.strip()
        uses = result.tool_uses
        if not uses or result.stop_reason != "tool_use":
            break
        messages.append(ai.AIMessage("assistant", result.content))
        results = []
        for use in uses:
            tool_calls += 1
            if tool_calls > MAX_TOOL_CALLS:
                outcome = Outcome(False, {"error": "Zu viele Aktionen in einer Nachricht"}, "")
            else:
                outcome = run_tool(ctx, str(use.get("name")), dict(use.get("input") or {}))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use["id"],
                    "content": json.dumps(outcome.data, ensure_ascii=False, default=str),
                    **({} if outcome.ok else {"is_error": True}),
                }
            )
        ctx.session.commit()
        messages.append(ai.AIMessage("user", results))
    else:
        answer = answer or "Ich habe die Schritte ausgeführt, bin aber nicht ganz fertig geworden."
    return answer, call_ids


# --- entry points --------------------------------------------------------------------


@dataclass(frozen=True)
class Exchange:
    question: ChatMessage
    answer: ChatMessage
    actions: list[ChatAction]


def _mock_answer(ctx: Context, text: str) -> str:
    parsed = parse(ctx.session, ctx.settings, text)
    lines = []
    carded = 0
    for name, args in parsed.calls[:MAX_TOOL_CALLS]:
        before = len(ctx.actions)
        outcome = run_tool(ctx, name, args)
        if len(ctx.actions) > before:
            carded += 1  # the action card already says what happened
            continue
        lines.append(outcome.text if outcome.ok else f"Nicht ausgeführt: {outcome.text}")
    lines.extend(parsed.replies)
    if carded and not lines:
        lines.append("Erledigt." if carded == 1 else f"Erledigt: {carded} Änderungen.")
    return "\n".join(lines)


def send(
    session: Session, settings: Settings, user: User, text: str, redis: Redis | None = None
) -> Exchange:
    """Handle one chat message from ``user``; commits."""
    text = text.strip()[:MAX_TEXT]
    question = ChatMessage(user_id=user.id, role="user", text=text)
    session.add(question)
    session.flush()
    answer = ChatMessage(user_id=user.id, role="assistant", text="", provider=ai.MOCK)
    session.add(answer)
    session.flush()
    ctx = Context(session, settings, user, answer, redis)

    if ai.selected_provider(session) == ai.CLAUDE:
        try:
            reply, call_ids = _live(ctx, text)
            answer.provider = ai.CLAUDE
            answer.ai_call_ids = call_ids
        except ai.AIBlockedError as exc:
            if ctx.actions:
                reply = f"Abgebrochen: {exc.reason}."
            else:
                reply = (
                    f"Claude ist gerade nicht verfügbar ({exc.reason}). "
                    "Ich habe die einfache Befehlserkennung genutzt.\n" + _mock_answer(ctx, text)
                )
        except (ai.AIRefusedError, ai.AIFailedError) as exc:
            answer.provider = ai.CLAUDE
            reply = f"Das hat nicht geklappt: {exc}."
    else:
        reply = _mock_answer(ctx, text)

    answer.text = reply or "Erledigt."
    session.flush()
    session.commit()
    return Exchange(question, answer, ctx.actions)


def messages(session: Session, user: User, limit: int = 50) -> list[ChatMessage]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    ).all()
    return list(rows)[::-1]


def actions_for(session: Session, message_ids: list[int]) -> dict[int, list[ChatAction]]:
    out: dict[int, list[ChatAction]] = {}
    if not message_ids:
        return out
    for action in session.scalars(
        select(ChatAction).where(ChatAction.message_id.in_(message_ids)).order_by(ChatAction.id)
    ):
        out.setdefault(action.message_id, []).append(action)
    return out
