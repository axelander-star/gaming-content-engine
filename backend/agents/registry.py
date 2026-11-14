"""Registry of all 18 agents from PROJECT_SPEC section 6.

Each entry describes the agent (for the dashboard), the phase in which it is
implemented, how it can cause costs, and its pipeline stage. Agents whose
``factory`` is ``None`` are not implemented yet; the orchestrator never runs
them and records that the stage is waiting for that phase.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from agents.base import Agent, CostKind, Stage


@dataclass(frozen=True)
class AgentSpec:
    name: str
    number: int
    title: str
    description: str
    phase: int
    cost_kind: CostKind
    stage: Stage | None = None
    factory: Callable[[], Agent] | None = None
    #: Production agents count against ``max_daily_production_jobs``.
    production: bool = False

    @property
    def implemented(self) -> bool:
        return self.factory is not None


def _master() -> Agent:
    from agents.master import MasterOrchestratorAgent

    return MasterOrchestratorAgent()


def _budget() -> Agent:
    from agents.budget_cost import BudgetCostAgent

    return BudgetCostAgent()


def _trend_research() -> Agent:
    from agents.trend_research import TrendResearchAgent

    return TrendResearchAgent()


def _game_intelligence() -> Agent:
    from agents.game_intelligence import GameIntelligenceAgent

    return GameIntelligenceAgent()


def _gameplay_analysis() -> Agent:
    from agents.gameplay_analysis import GameplayAnalysisAgent

    return GameplayAnalysisAgent()


def _clip_production() -> Agent:
    from agents.clip_production import ClipProductionAgent

    return ClipProductionAgent()


def _material_scout() -> Agent:
    from agents.material_scout import MaterialScoutAgent

    return MaterialScoutAgent()


def _rights_license() -> Agent:
    from agents.rights_license import RightsLicenseAgent

    return RightsLicenseAgent()


def _creative_director() -> Agent:
    from agents.creative_director import CreativeDirectorAgent

    return CreativeDirectorAgent()


def _script_hook() -> Agent:
    from agents.script_hook import ScriptHookAgent

    return ScriptHookAgent()


GF, V = "gameplay_files", "variants"

_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec("master", 1, "Master Orchestrator",
              "Steuert alle Agenten, verteilt Aufträge, prüft Freigaben und protokolliert.",
              4, CostKind.LOCAL, factory=_master),
    AgentSpec("trend_research", 2, "Trend Research",
              "Erkennt Gaming-Trends und bewertet ihr Potenzial.", 5, CostKind.FREE_API,
              factory=_trend_research),
    AgentSpec("game_intelligence", 3, "Game Intelligence",
              "Sammelt Spieleinformationen, Zielgruppen und Videoideen.", 5, CostKind.PAID,
              factory=_game_intelligence),
    AgentSpec("material_scout", 4, "Material Scout",
              "Findet freigegebenes Gameplay und dokumentiert Quellen.", 6, CostKind.LOCAL,
              stage=Stage(GF, "DISCOVERED"), factory=_material_scout),
    AgentSpec("rights_license", 5, "Rights & License",
              "Prüft Lizenzen und verhindert Verarbeitung ohne Freigabe.", 6, CostKind.LOCAL,
              stage=Stage(GF, "RIGHTS_PENDING"), factory=_rights_license),
    AgentSpec("gameplay_analysis", 6, "Gameplay Analysis",
              "Erkennt interessante Szenen und erzeugt Zeitmarken.", 7, CostKind.LOCAL,
              stage=Stage(GF, "RIGHTS_APPROVED"), production=True, factory=_gameplay_analysis),
    AgentSpec("clip_production", 7, "Clip Production",
              "Schneidet Szenen und erzeugt das Hochformat.", 7, CostKind.LOCAL,
              stage=Stage(V, "SCENE_SELECTED"), production=True, factory=_clip_production),
    AgentSpec("creative_director", 8, "Creative Director",
              "Entwickelt Konzepte, Formate und Varianten.", 8, CostKind.PAID,
              stage=Stage(V, "EDITING", step="concept"), production=True,
              factory=_creative_director),
    AgentSpec("script_hook", 9, "Script & Hook",
              "Schreibt Hooks, Voiceover-Texte, Titel und Beschreibungen.", 8, CostKind.PAID,
              stage=Stage(V, "EDITING", step="script"), production=True, factory=_script_hook),
    AgentSpec("localization", 10, "Localization",
              "Erstellt eigenständige deutsche und englische Fassungen.", 9, CostKind.PAID,
              stage=Stage(V, "LOCALIZATION"), production=True),
    AgentSpec("voice", 11, "Voice",
              "Erzeugt KI-Stimmen mit kommerziellen Nutzungsrechten.", 9, CostKind.PAID,
              stage=Stage(V, "VOICEOVER"), production=True),
    AgentSpec("subtitle", 12, "Subtitle",
              "Erstellt und synchronisiert Untertitel.", 9, CostKind.LOCAL,
              stage=Stage(V, "SUBTITLES"), production=True),
    AgentSpec("quality_control", 13, "Quality Control",
              "Prüft Technik, Rechte und Duplikate vor der Freigabe.", 10, CostKind.LOCAL,
              stage=Stage(V, "QUALITY_CHECK"), production=True),
    AgentSpec("publishing_strategy", 14, "Publishing Strategy",
              "Bestimmt pro Kanal Menge, Auswahl und Zeitpunkt der Veröffentlichungen.",
              11, CostKind.LOCAL, stage=Stage(V, "READY_TO_PUBLISH")),
    AgentSpec("publishing", 15, "Publishing",
              "Veröffentlicht über offizielle APIs autorisierter Kanäle.", 12, CostKind.FREE_API,
              stage=Stage(V, "SCHEDULED")),
    AgentSpec("analytics", 16, "Analytics",
              "Ruft Statistiken ab und erkennt starke und schwache Videos.", 14,
              CostKind.FREE_API, stage=Stage(V, "ANALYTICS_PENDING")),
    AgentSpec("learning", 17, "Learning",
              "Leitet aus ausreichend Daten kontrollierte Strategieänderungen ab.", 14,
              CostKind.LOCAL),
    AgentSpec("budget_cost", 18, "Budget & Cost",
              "Überwacht Kosten und Budgetstufen, begrenzt teure Aufgaben.", 4, CostKind.LOCAL,
              factory=_budget),
)  # fmt: skip

_registry: dict[str, AgentSpec] = {s.name: s for s in _SPECS}


def all_specs() -> list[AgentSpec]:
    return sorted(_registry.values(), key=lambda s: s.number)


def get_spec(name: str) -> AgentSpec | None:
    return _registry.get(name)


def stage_specs() -> list[AgentSpec]:
    """Agents that own a pipeline stage, in pipeline order."""
    return [s for s in all_specs() if s.stage is not None]


@contextmanager
def override(
    name: str, factory: Callable[[], Agent] | None, **changes: object
) -> Iterator[AgentSpec]:
    """Temporarily replace an agent implementation (tests and simulations).

    ``factory=None`` simulates an agent that is not implemented yet.
    """
    original = _registry[name]
    patched = replace(original, factory=factory, **changes)  # type: ignore[arg-type]
    _registry[name] = patched
    try:
        yield patched
    finally:
        _registry[name] = original
