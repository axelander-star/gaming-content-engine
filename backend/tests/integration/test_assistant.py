"""Chat assistant (extension phase E4): tools in mock mode, undo, roles, live loop.

No test talks to the Claude API: the live loop runs against a fake client.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.enums import AICallStatus, ChatActionStatus, ContentProjectStatus, UserRole
from models.access import User
from models.ai import AICall
from models.assistant import ChatAction
from models.planning import ContentFocus, EditorialDay
from models.projects import ContentProject
from models.research import Idea
from services import ai, assistant, planning
from services.controls import update_operations
from services.seed import seed_base_data
from tests.conftest import login

pytestmark = pytest.mark.integration

MakeUser = Callable[..., User]


@pytest.fixture
def projects(db: Session) -> dict[str, ContentProject]:
    seed_base_data(db)
    gaming = db.scalar(select(ContentProject).where(ContentProject.slug == "gaming"))
    assert gaming is not None
    gaming.subtopics = ["GTA", "Gaming-News"]
    food = ContentProject(
        slug="ernaehrung", name="Ernährung", languages=["de"], subtopics=["Rezepte"], priority=200
    )
    db.add(food)
    db.flush()
    return {"gaming": gaming, "food": food}


def _today() -> date:
    return planning.today(get_settings())


def _next(weekday: int) -> date:
    today = _today()
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _chat(api: TestClient, headers: dict[str, str], text: str) -> dict[str, Any]:
    r = api.post("/api/assistant/messages", json={"text": text}, headers=headers)
    assert r.status_code == 200, r.text
    answer: dict[str, Any] = r.json()["answer"]
    return answer


def _admin(api: TestClient, make_user: MakeUser) -> dict[str, str]:
    make_user()
    return login(api, "admin@example.com")


# --- roles and safety ----------------------------------------------------------------


def test_chat_needs_operator(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    assert api.get("/api/assistant/messages").status_code == 401
    make_user(role=UserRole.VIEWER, email="viewer@example.com")
    headers = login(api, "viewer@example.com")
    assert api.get("/api/assistant/messages").status_code == 200
    r = api.post("/api/assistant/messages", json={"text": "Status"}, headers=headers)
    assert r.status_code == 403
    assert api.get("/api/planning/week").status_code == 200


def test_no_tool_can_publish() -> None:
    for tool in assistant.TOOLS:
        assert not any(w in tool["name"] for w in ("publish", "post", "upload"))
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False


def test_publish_request_is_refused(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    answer = _chat(api, headers, "Veröffentliche das GTA-Video jetzt auf YouTube")
    assert "Veröffentlichen kann ich nicht" in answer["text"]
    assert answer["actions"] == []
    assert db.scalars(select(ChatAction)).all() == []


def test_unknown_text_gets_help(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    answer = _chat(api, headers, "Wie wird das Wetter?")
    assert "Ich verstehe zum Beispiel" in answer["text"]
    assert answer["provider"] == "mock"


# --- tools in mock mode --------------------------------------------------------------


def test_overview(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    answer = _chat(api, headers, "Status")
    assert "Themenbereiche: Gaming (aktiv), Ernährung (aktiv)" in answer["text"]
    assert answer["actions"] == []


def test_focus_this_week_and_undo(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    answer = _chat(api, headers, "Diese Woche GTA 6")
    [action] = answer["actions"]
    assert action["tool"] == "set_focus" and action["undoable"] is True
    focus = db.scalars(select(ContentFocus)).one()
    monday = planning.week_start(_today())
    assert (focus.topic, focus.content_project_id) == ("GTA 6", projects["gaming"].id)
    assert (focus.starts_on, focus.ends_on) == (monday, monday + timedelta(days=6))

    week = api.get("/api/planning/week").json()
    assert [f["topic"] for f in week["focus"]] == ["GTA 6"]

    r = api.post(f"/api/assistant/actions/{action['id']}/undo", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "undone" and r.json()["undoable"] is False
    assert db.scalars(select(ContentFocus)).all() == []
    again = api.post(f"/api/assistant/actions/{action['id']}/undo", headers=headers)
    assert again.status_code == 409


def test_focus_next_week_for_named_project(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    _chat(api, headers, "Nächste Woche Schwerpunkt Meal Prep bei Ernährung")
    focus = db.scalars(select(ContentFocus)).one()
    assert focus.content_project_id == projects["food"].id
    assert focus.topic == "Meal Prep"
    assert focus.starts_on == planning.week_start(_today()) + timedelta(days=7)


def test_plan_day_add_remove_and_undo(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    wednesday = _next(2)
    answer = _chat(api, headers, "Mittwoch zusätzlich Ernährung")
    [added] = answer["actions"]
    assert added["tool"] == "plan_day" and added["args"]["date"] == wednesday.isoformat()
    entry = db.scalars(select(EditorialDay)).one()
    assert (entry.day, entry.content_project_id) == (wednesday, projects["food"].id)

    again = _chat(api, headers, "Mittwoch zusätzlich Ernährung")
    assert again["actions"] == [] and "schon eingeplant" in again["text"]

    removed = _chat(api, headers, "Mittwoch keine Ernährung")["actions"][0]
    assert "aus dem Plan genommen" in removed["summary"]
    assert db.scalars(select(EditorialDay)).all() == []

    r = api.post(f"/api/assistant/actions/{removed['id']}/undo", headers=headers)
    assert r.status_code == 200, r.text
    assert db.scalars(select(EditorialDay)).one().day == wednesday

    week = api.get("/api/planning/week", params={"start": wednesday.isoformat()}).json()
    day = next(d for d in week["days"] if d["day"] == wednesday.isoformat())
    assert [p["name"] for p in day["projects"]] == ["Ernährung"]
    assert day["weekday"] == "Mittwoch"


def test_plan_several_days_and_projects_with_dates(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    target = _today() + timedelta(days=10)
    answer = _chat(api, headers, f"Am {target.strftime('%d.%m.')} Gaming und Ernährung")
    assert len(answer["actions"]) == 2
    assert {e.day for e in db.scalars(select(EditorialDay))} == {target}


def test_plan_day_needs_a_project_and_a_sane_date(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    assert "Welcher Themenbereich" in _chat(api, headers, "Mittwoch bitte mehr")["text"]
    far = _today() + timedelta(days=200)
    answer = _chat(api, headers, f"Am {far.strftime('%d.%m.')} Gaming")
    [failed] = answer["actions"]
    assert failed["status"] == "failed" and "Tage voraus" in failed["error"]


def test_paused_project_cannot_be_planned(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    projects["food"].status = ContentProjectStatus.PAUSED
    answer = _chat(api, headers, "Freitag Ernährung")
    assert answer["actions"][0]["status"] == "failed"
    assert "pausiert" in answer["actions"][0]["error"]


def test_project_status_is_admin_only_and_undoable(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    op = login(api, "op@example.com")
    answer = _chat(api, op, "Ernährung pausieren")
    assert answer["actions"][0]["status"] == "failed"
    assert "Admin" in answer["actions"][0]["error"]
    db.refresh(projects["food"])
    assert projects["food"].status == ContentProjectStatus.ACTIVE

    api.cookies.clear()
    admin = _admin(api, make_user)
    [action] = _chat(api, admin, "Ernährung pausieren")["actions"]
    db.refresh(projects["food"])
    assert projects["food"].status == ContentProjectStatus.PAUSED
    r = api.post(f"/api/assistant/actions/{action['id']}/undo", headers=admin)
    assert r.status_code == 200, r.text
    db.refresh(projects["food"])
    assert projects["food"].status == ContentProjectStatus.ACTIVE


def test_undo_only_own_actions(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    admin = _admin(api, make_user)
    [action] = _chat(api, admin, "Diese Woche GTA 6")["actions"]
    api.cookies.clear()
    make_user(role=UserRole.OPERATOR, email="op@example.com")
    op = login(api, "op@example.com")
    r = api.post(f"/api/assistant/actions/{action['id']}/undo", headers=op)
    assert r.status_code == 404


def test_start_research(
    api: TestClient,
    make_user: MakeUser,
    projects: dict[str, ContentProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted: list[tuple[str, dict[str, Any]]] = []

    def fake_submit(name: str, payload: dict[str, Any], **_: Any) -> Any:
        submitted.append((name, payload))
        return SimpleNamespace(id=f"job-{len(submitted)}")

    monkeypatch.setattr("services.orchestrator.submit", fake_submit)
    headers = _admin(api, make_user)
    [action] = _chat(api, headers, "Starte eine Trendrecherche")["actions"]
    assert action["status"] == "done" and action["undoable"] is False
    gaming_id = projects["gaming"].id
    assert submitted == [
        ("trend_research", {}),
        ("research", {"project_id": gaming_id}),
        ("idea_lab", {"project_id": gaming_id}),
    ]
    assert action["args"]["jobs"]["idea_lab"] == "job-3"

    submitted.clear()
    [food] = _chat(api, headers, "Recherchiere für Ernährung")["actions"]
    assert food["status"] == "done"
    assert [n for n, _ in submitted] == ["research", "idea_lab"]

    projects["food"].status = ContentProjectStatus.PAUSED
    [failed] = _chat(api, headers, "Recherchiere für Ernährung")["actions"]
    assert failed["status"] == "failed" and "pausiert" in failed["error"]


def test_list_ideas_in_chat(
    api: TestClient, make_user: MakeUser, db: Session, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    assert "keine offenen Ideen" in _chat(api, headers, "Zeig mir die Ideen")["text"]
    db.add(
        Idea(
            content_project_id=projects["food"].id, title="Meal Prep in 5 Minuten",
            pitch="Test", format="short", trend_score=90, fit_score=70, effort_score=30,
            rights_risk=15, score=78, reasoning="Test", provider="mock",
        )
    )  # fmt: skip
    db.flush()
    answer = _chat(api, headers, "Welche Ideen gibt es für Ernährung?")
    assert "Meal Prep in 5 Minuten (Bewertung 78)" in answer["text"]
    assert answer["actions"] == []


def test_history_is_per_user(
    api: TestClient, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    headers = _admin(api, make_user)
    _chat(api, headers, "Diese Woche GTA 6")
    history = api.get("/api/assistant/messages").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["actions"][0]["tool"] == "set_focus"
    api.cookies.clear()
    make_user(role=UserRole.VIEWER, email="viewer@example.com")
    login(api, "viewer@example.com")
    assert api.get("/api/assistant/messages").json() == []


# --- parser --------------------------------------------------------------------------


def test_parser_splits_sentences(db: Session, projects: dict[str, ContentProject]) -> None:
    parsed = assistant.parse(db, get_settings(), "Diese Woche GTA 6. Freitag kein Gaming")
    assert [c[0] for c in parsed.calls] == ["set_focus", "plan_day"]
    assert parsed.calls[1][1]["change"] == "remove"
    assert parsed.calls[1][1]["date"] == _next(4).isoformat()


# --- live mode (fake client) ---------------------------------------------------------


class FakeLoopClient:
    """Answers with a tool call first, then with text."""

    def __init__(self, responses: list[list[SimpleNamespace]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params: Any) -> Any:
        self.calls.append(params)
        content = self.responses.pop(0)
        uses_tool = any(b.type == "tool_use" for b in content)
        return SimpleNamespace(
            content=content,
            usage=SimpleNamespace(
                input_tokens=1500,
                output_tokens=100,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            stop_reason="tool_use" if uses_tool else "end_turn",
            model=params["model"],
            _request_id="req_test",
        )


def _live_settings() -> Settings:
    return get_settings().model_copy(
        update={"paid_api_calls_enabled": True, "anthropic_api_key": SecretStr("sk-test-not-real")}
    )


def test_live_tool_loop(
    db: Session,
    make_user: MakeUser,
    projects: dict[str, ContentProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    friday = _next(4)
    client = FakeLoopClient(
        [
            [
                SimpleNamespace(type="text", text="Ich plane das ein."),
                SimpleNamespace(
                    type="tool_use",
                    id="toolu_1",
                    name="plan_day",
                    input={
                        "date": friday.isoformat(),
                        "project": "Ernährung",
                        "change": "add",
                        "note": "",
                    },
                ),
            ],
            [SimpleNamespace(type="text", text="Freitag ist jetzt Ernährung eingeplant.")],
        ]
    )
    monkeypatch.setattr(ai, "client_factory", lambda _s: client)
    update_operations(db, None, {"ai_provider": "claude", "monthly_budget_eur": 50})
    db.flush()
    user = make_user()

    exchange = assistant.send(db, _live_settings(), user, "Freitag bitte Ernährung")

    assert exchange.answer.provider == "claude"
    assert exchange.answer.text == "Freitag ist jetzt Ernährung eingeplant."
    assert [a.tool for a in exchange.actions] == ["plan_day"]
    assert db.scalars(select(EditorialDay)).one().day == friday
    assert len(client.calls) == 2
    first, second = client.calls
    assert first["model"] == "claude-sonnet-5-5"
    assert [t["name"] for t in first["tools"]] == [t["name"] for t in assistant.TOOLS]
    assert planning.format_day(_today()) in first["system"]
    assert first["system"] == second["system"]  # frozen within a turn
    # the assistant's blocks go back unchanged, followed by the tool result
    assert second["messages"][1]["content"][1]["id"] == "toolu_1"
    result = second["messages"][2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert "is_error" not in result
    calls = db.scalars(select(AICall).where(AICall.purpose == "chat")).all()
    assert len(calls) == 2 and all(c.status == AICallStatus.SUCCEEDED for c in calls)
    assert sorted(exchange.answer.ai_call_ids) == sorted(c.id for c in calls)


def test_live_history_is_text_only(
    db: Session,
    make_user: MakeUser,
    projects: dict[str, ContentProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeLoopClient(
        [
            [SimpleNamespace(type="text", text="Hallo!")],
            [SimpleNamespace(type="text", text="Noch da.")],
        ]
    )
    monkeypatch.setattr(ai, "client_factory", lambda _s: client)
    update_operations(db, None, {"ai_provider": "claude", "monthly_budget_eur": 50})
    db.flush()
    user = make_user()
    assistant.send(db, _live_settings(), user, "Hallo")
    assistant.send(db, _live_settings(), user, "Bist du noch da?")
    messages = client.calls[1]["messages"]
    assert messages == [
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": "Hallo!"},
        {"role": "user", "content": "Bist du noch da?"},
    ]


def test_live_tool_errors_go_back_to_the_model(
    db: Session,
    make_user: MakeUser,
    projects: dict[str, ContentProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeLoopClient(
        [
            [
                SimpleNamespace(
                    type="tool_use",
                    id="toolu_9",
                    name="set_project_status",
                    input={"project": "Ernährung", "status": "paused"},
                )
            ],
            [SimpleNamespace(type="text", text="Das darf nur ein Admin.")],
        ]
    )
    monkeypatch.setattr(ai, "client_factory", lambda _s: client)
    update_operations(db, None, {"ai_provider": "claude", "monthly_budget_eur": 50})
    db.flush()
    op = make_user(role=UserRole.OPERATOR, email="op@example.com")
    exchange = assistant.send(db, _live_settings(), op, "Pausiere Ernährung")
    assert exchange.actions[0].status == ChatActionStatus.FAILED
    result = client.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "Admin" in result["content"]
    assert projects["food"].status == ContentProjectStatus.ACTIVE


def test_live_blocked_falls_back_to_rules_and_says_so(
    db: Session, make_user: MakeUser, projects: dict[str, ContentProject]
) -> None:
    update_operations(db, None, {"ai_provider": "claude"})
    db.flush()
    user = make_user()
    exchange = assistant.send(db, get_settings(), user, "Diese Woche GTA 6")
    assert "Claude ist gerade nicht verfügbar" in exchange.answer.text
    assert exchange.answer.provider == "mock"
    assert [a.tool for a in exchange.actions] == ["set_focus"]
    blocked = db.scalars(select(AICall).where(AICall.status == AICallStatus.BLOCKED)).all()
    assert len(blocked) == 1
