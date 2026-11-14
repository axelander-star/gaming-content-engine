"""Phase 8: Creative Director, Script & Hook, LLM adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import AgentContext
from agents.master import MasterOrchestratorAgent
from agents.registry import get_spec
from core.config import Settings, get_settings
from core.enums import (
    AgentRunStatus,
    CostCategory,
    Language,
    MaterialStatus,
    UserRole,
    VideoStatus,
)
from models import Cost, Script, User, Variant
from models.control import AgentRun
from services import creative, gates, llm, orchestrator
from services.controls import update_operations
from tests.conftest import login
from tests.factories import Chain, build_chain

ACTION = {"motion": 0.9, "audio": 0.8, "surprise": 0.9, "cuts": 0.3, "buildup": 0.7}
CALM = {"motion": 0.1, "audio": 0.2, "surprise": 0.0, "cuts": 0.0, "buildup": 0.1}


def editing_chain(db: Session, scores: dict[str, float] = ACTION, **kw: Any) -> Chain:
    chain = build_chain(db, **kw)
    chain.gameplay_file.status = MaterialStatus.ANALYZED
    chain.scene.scores = scores
    chain.clip.duration_s = 30.0
    chain.variant.status = VideoStatus.EDITING  # test setup: clip already rendered
    db.flush()
    return chain


def run(db: Session, agent: str, variant_id: int, settings: Settings | None = None) -> AgentRun:
    return orchestrator.run_agent(
        db, settings or get_settings(), agent, {"entity_type": "variants", "entity_id": variant_id}
    )


def variants_of(db: Session, chain: Chain) -> list[Variant]:
    return list(
        db.scalars(
            select(Variant)
            .where(Variant.clip_id == chain.clip.id, Variant.channel_id == chain.channel.id)
            .order_by(Variant.variant_label)
        )
    )


# --- concepts -------------------------------------------------------------------


def test_only_signal_backed_formats_are_chosen() -> None:
    ranked = creative.rank_concepts(ACTION, [], {})
    formats = {c.video_format for c in ranked}
    assert formats <= set(creative.SIGNAL_FORMATS)
    assert not formats & set(creative.CONTENT_FORMATS)  # e.g. "funny" is never promised
    assert ranked == sorted(ranked, key=lambda c: -c.score)
    assert creative.rank_concepts(CALM, [], {}) == []


def test_game_profile_and_performance_shift_the_ranking() -> None:
    plain = creative.rank_concepts(ACTION, [], {})[0]
    boosted = creative.rank_concepts(ACTION, ["storytelling"], {"storytelling": 1.0})[0]
    assert boosted.video_format == "storytelling" != plain.video_format
    assert boosted.components["game_profile"] == 1.0


def test_variants_really_differ() -> None:
    chosen = creative.choose_variants(creative.rank_concepts(ACTION, [], {}), 4)
    assert len(chosen) == 4
    assert len({c.hook_type for c in chosen}) == 4  # every variant has its own hook
    assert len({c.video_format for c in chosen}) >= 2  # and not only the first sentence
    assert not chosen[0].experiment and all(c.experiment for c in chosen[1:])


# --- scripts --------------------------------------------------------------------


def draft(language: Language, duration: float = 30.0, **kw: Any) -> creative.ScriptDraft:
    args: dict[str, Any] = {
        "language": language,
        "video_format": "surprise",
        "hook_type": "question",
        "game": "Valorant",
        "source_name": "Creator X",
        "duration_s": duration,
        "seed": "1:1:A",
    }
    return creative.write_script(**(args | kw))


def test_script_is_written_per_language_not_translated() -> None:
    de, en = draft(Language.DE), draft(Language.EN)
    assert de.hook != en.hook and de.title != en.title
    assert "Valorant" in de.hook and "Valorant" in en.hook
    assert "Gameplay: Creator X (lizenziert)" in de.description
    assert "Gameplay: Creator X (licensed)" in en.description
    assert "#Valorant" in de.description
    for d in (de, en):
        assert d.words <= d.word_budget
        assert len(d.title) <= creative.TITLE_MAX
        kinds = [b["kind"] for b in d.beats]
        assert kinds[0] == "hook" and kinds[-1] == "cta" and "payoff" in kinds
        starts = [b["start_s"] for b in d.beats]
        assert starts == sorted(starts) and d.beats[-1]["end_s"] == 30.0


def test_short_clip_drops_lines_but_keeps_hook_and_payoff() -> None:
    short = draft(Language.DE, duration=8.0)
    assert short.words <= short.word_budget
    kinds = [b["kind"] for b in short.beats]
    assert kinds[0] == "hook" and "setup" not in kinds


def test_wording_is_stable_per_seed() -> None:
    assert draft(Language.EN).hook == draft(Language.EN).hook
    hooks = {draft(Language.EN, seed=f"{i}:1:A").hook for i in range(12)}
    assert len(hooks) == 2  # both wordings get used across channels


# --- agents through the orchestrator -------------------------------------------


def test_creative_director_plans_variants_then_script_hook_writes(db: Session) -> None:
    chain = editing_chain(db)
    update_operations(db, None, {"creative_variants": 2})

    first = run(db, "creative_director", chain.variant.id)
    assert first.status == AgentRunStatus.SUCCEEDED, first.error
    a, b = variants_of(db, chain)
    assert (a.variant_label, b.variant_label) == ("A", "B")
    assert a.video_format and b.video_format and a.hook_type != b.hook_type
    assert b.status == VideoStatus.EDITING and b.concept["experiment"] is True
    assert a.status == VideoStatus.EDITING  # waits for the script

    # the concept step is done: the Creative Director may not run again
    again = run(db, "creative_director", a.id)
    assert again.status == AgentRunStatus.SKIPPED and again.output["gate"] == "wrong_step"

    for v in (a, b):
        result = run(db, "script_hook", v.id)
        assert result.status == AgentRunStatus.SUCCEEDED, result.error
        assert v.status == VideoStatus.LOCALIZATION
        script = db.scalar(select(Script).where(Script.variant_id == v.id))
        assert script is not None and script.source == "template" and script.version == 1
        assert script.hook_type == v.hook_type and script.language == v.language
        assert script.beats[0]["kind"] == "hook" and v.title == script.title
    assert a.title != b.title or a.hook_type != b.hook_type


def test_clips_api_shows_concept_and_script(
    db: Session, api: TestClient, make_user: Callable[..., User]
) -> None:
    make_user("viewer@example.com", UserRole.VIEWER)
    chain = editing_chain(db)
    assert run(db, "creative_director", chain.variant.id).status == AgentRunStatus.SUCCEEDED
    assert run(db, "script_hook", chain.variant.id).status == AgentRunStatus.SUCCEEDED
    h = login(api, "viewer@example.com")
    clip = next(
        c for c in api.get("/api/production/clips", headers=h).json() if c["id"] == chain.clip.id
    )
    a = next(v for v in clip["variants"] if v["label"] == "A")
    assert a["video_format"] and a["hook_type"] and a["concept"]["components"]
    assert a["script"]["hook"] and a["script"]["source"] == "template"
    assert a["script"]["beats"][0]["kind"] == "hook"


def test_master_dispatches_concept_before_script(db: Session) -> None:
    chain = editing_chain(db)
    submitted: list[tuple[str, dict[str, Any]]] = []
    run_row = AgentRun(agent_name="master")
    db.add(run_row)
    db.flush()
    ctx = AgentContext(db, get_settings(), run_row, "master")
    MasterOrchestratorAgent(submit=lambda n, p: submitted.append((n, p))).run(ctx, {})
    mine = [n for n, p in submitted if p["entity_id"] == chain.variant.id]
    assert mine == ["creative_director"]

    chain.variant.video_format, chain.variant.hook_type = "surprise", "question"
    db.flush()
    submitted.clear()
    MasterOrchestratorAgent(submit=lambda n, p: submitted.append((n, p))).run(ctx, {})
    mine = [n for n, p in submitted if p["entity_id"] == chain.variant.id]
    assert mine == ["script_hook"]
    spec = get_spec("creative_director")
    assert spec is not None
    payload = {"entity_type": "variants", "entity_id": chain.variant.id}
    assert gates.check(db, get_settings(), spec, payload).code == "wrong_step"


def test_variant_count_follows_operator_setting(db: Session) -> None:
    chain = editing_chain(db, language=Language.EN)
    update_operations(db, None, {"creative_variants": 1})
    assert run(db, "creative_director", chain.variant.id).status == AgentRunStatus.SUCCEEDED
    assert len(variants_of(db, chain)) == 1

    other = editing_chain(db, language=Language.EN)
    update_operations(db, None, {"creative_variants": 4})
    assert run(db, "creative_director", other.variant.id).status == AgentRunStatus.SUCCEEDED
    planned = variants_of(db, other)
    assert [v.variant_label for v in planned] == ["A", "B", "C", "D"]
    assert len({v.hook_type for v in planned}) == 4


def test_calm_scene_fails_without_inventing_a_format(db: Session) -> None:
    chain = editing_chain(db, scores=CALM)
    result = run(db, "creative_director", chain.variant.id)
    assert result.status == AgentRunStatus.FAILED
    assert "Kein automatisch wählbares Format" in (result.error or "")
    assert chain.variant.status == VideoStatus.FAILED
    assert chain.variant.retry_count >= get_settings().agent_max_retries


# --- LLM adapter -------------------------------------------------------------------


class FakeModel:
    name = "fake-llm"
    estimated_cost_eur = Decimal("0.01")

    def __init__(self) -> None:
        self.calls = 0

    def rewrite(
        self, draft: creative.ScriptDraft, language: Language, brief: str
    ) -> creative.ScriptDraft:
        self.calls += 1
        return replace(draft, title=f"{draft.title} (KI)")


@pytest.fixture
def fake_model() -> Iterator[FakeModel]:
    model = FakeModel()
    llm.PROVIDERS["fake"] = lambda _s: model
    try:
        yield model
    finally:
        llm.PROVIDERS.pop("fake", None)


def concept_chain(db: Session) -> Chain:
    chain = editing_chain(db)
    chain.variant.video_format, chain.variant.hook_type = "epic_scene", "bold_claim"
    db.flush()
    return chain


def test_mock_provider_uses_templates_without_cost(db: Session) -> None:
    assert llm.get_model("mock", get_settings()) is None
    chain = concept_chain(db)
    result = run(db, "script_hook", chain.variant.id)
    assert result.status == AgentRunStatus.SUCCEEDED
    assert db.scalar(select(Cost).where(Cost.agent_run_id == result.id)) is None


def test_unknown_provider_falls_back_to_templates(db: Session) -> None:
    update_operations(db, None, {"ai_provider": "nicht-angebunden"})
    chain = concept_chain(db)
    result = run(db, "script_hook", chain.variant.id)
    assert result.status == AgentRunStatus.SUCCEEDED
    script = db.scalar(select(Script).where(Script.variant_id == chain.variant.id))
    assert script is not None and script.source == "template"


def test_paid_model_is_not_called_while_paid_calls_are_disabled(
    db: Session, fake_model: FakeModel
) -> None:
    update_operations(db, None, {"ai_provider": "fake"})
    chain = concept_chain(db)
    result = run(db, "script_hook", chain.variant.id)
    assert result.status == AgentRunStatus.SUCCEEDED
    assert fake_model.calls == 0
    script = db.scalar(select(Script).where(Script.variant_id == chain.variant.id))
    assert script is not None and script.source == "template"


def test_paid_model_runs_only_after_budget_approval_and_is_booked(
    db: Session, fake_model: FakeModel
) -> None:
    update_operations(db, None, {"ai_provider": "fake", "monthly_budget_eur": 50})
    settings = get_settings().model_copy(update={"paid_api_calls_enabled": True})
    chain = concept_chain(db)
    result = run(db, "script_hook", chain.variant.id, settings)
    assert result.status == AgentRunStatus.SUCCEEDED, result.error
    assert fake_model.calls == 1
    script = db.scalar(select(Script).where(Script.variant_id == chain.variant.id))
    assert (
        script is not None and script.source == "fake-llm" and (script.title or "").endswith("(KI)")
    )
    cost = db.scalar(select(Cost).where(Cost.agent_run_id == result.id))
    assert cost is not None and cost.category == CostCategory.AI
    assert cost.amount_eur == Decimal("0.01")
