"""Adapter for text models (LLM) used by the Script & Hook Agent (Phase 8).

Default is ``mock``: scripts come from the rule-based templates in
``services.creative`` and cost nothing. A live provider is added by registering a
factory in ``PROVIDERS`` once the operator has chosen one and approved a budget
(decision of 14.11.2026: templates first, provider later). Every live call must be
authorised by the budget service before it is made and booked afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from core.config import Settings
from core.enums import Language
from services.creative import ScriptDraft

MOCK = "mock"


class LLMNotConfiguredError(Exception):
    """The operator selected a provider that has no adapter or no credentials."""


class TextModel(Protocol):
    name: str
    #: Upper bound of one rewrite, asked from the budget service before the call.
    estimated_cost_eur: Decimal

    def rewrite(self, draft: ScriptDraft, language: Language, brief: str) -> ScriptDraft:
        """Improve wording of a template draft; must keep the beat timing and limits."""
        ...


#: Live providers by operator setting ``ai_provider``. Empty until one is approved.
PROVIDERS: dict[str, Callable[[Settings], TextModel]] = {}


def get_model(provider: str, settings: Settings) -> TextModel | None:
    """``None`` means: use the free templates."""
    if provider == MOCK:
        return None
    factory = PROVIDERS.get(provider)
    if factory is None:
        raise LLMNotConfiguredError(f"KI-Anbieter '{provider}' ist nicht angebunden")
    return factory(settings)
