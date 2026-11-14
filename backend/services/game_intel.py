"""Game profiles for the Game Intelligence agent.

Rule-based and local: audience from the game categories, typical game modes,
video ideas from the formats of PROJECT_SPEC section 6, the current trend per
language and the performance of our own videos. No paid calls; an optional
LLM refinement can be added later behind the budget gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.catalog import CATEGORIES_BY_KEY, FORMATS_BY_KEY, audience_for
from core.enums import Language
from models.trends import Game, Trend
from services.trends import own_performance

PROFILE_VERSION = 1

IDEA_TEMPLATES: dict[str, tuple[str, str]] = {
    "funny_moments": ("Die lustigsten {g}-Momente der Woche", "Funniest {g} moments this week"),
    "unexpected_twist": ("Damit hat in {g} niemand gerechnet", "Nobody saw this coming in {g}"),
    "epic_scene": ("Der epischste Moment in {g}", "The most epic moment in {g}"),
    "near_miss": ("So knapp – fast geschafft in {g}", "So close – almost made it in {g}"),
    "surprise": ("Die größte Überraschung in {g}", "The biggest surprise in {g}"),
    "tips_tricks": ("Ein {g}-Trick, den kaum jemand kennt", "One {g} trick almost nobody knows"),
    "storytelling": ("Die Geschichte hinter diesem {g}-Moment", "The story behind this {g} moment"),
    "challenge": ("{g}-Challenge: Schaffst du das?", "{g} challenge: can you do it?"),
    "comparison": ("{g}: früher gegen heute", "{g}: then vs. now"),
    "short_analysis": ("Warum dieser Zug in {g} genial war", "Why this {g} play was genius"),
}

GENERIC_FORMATS = ("epic_scene", "funny_moments", "tips_tricks")
RISING_PCT = 20.0


def _latest_trend(session: Session, game_id: int, language: Language) -> Trend | None:
    return session.scalar(
        select(Trend)
        .where(Trend.game_id == game_id, Trend.language == language)
        .order_by(Trend.detected_at.desc(), Trend.id.desc())
        .limit(1)
    )


def _growth(trend: Trend | None) -> float | None:
    if trend is None:
        return None
    rates: list[float] = [
        float(s["growth_pct"])
        for s in (trend.metrics or {}).get("per_source", {}).values()
        if isinstance(s, dict) and s.get("growth_pct") is not None
    ]
    return round(sum(rates) / len(rates), 1) if rates else None


def _formats(categories: list[str]) -> list[str]:
    ordered: list[str] = []
    for key in categories:
        cat = CATEGORIES_BY_KEY.get(key)
        for fmt in cat.formats if cat else ():
            if fmt not in ordered:
                ordered.append(fmt)
    for fmt in GENERIC_FORMATS:
        if fmt not in ordered:
            ordered.append(fmt)
    return ordered[:4]


def _modes(categories: list[str]) -> list[str]:
    modes: list[str] = []
    for key in categories:
        cat = CATEGORIES_BY_KEY.get(key)
        for mode in cat.modes if cat else ():
            if mode not in modes:
                modes.append(mode)
    return modes


def build_profile(
    session: Session, game: Game, languages: list[Language], now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    categories = list(game.categories or [])
    key, label_de, label_en = audience_for(categories)
    secondary = [audience_for([c])[1] for c in categories[1:] if audience_for([c])[0] != key]

    trends: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    rising = False
    for lang in languages:
        trend = _latest_trend(session, game.id, lang)
        growth = _growth(trend)
        rising = rising or (growth is not None and growth >= RISING_PCT)
        trends[lang.value] = {
            "score": float(trend.score) if trend else None,
            "growth_pct": growth,
            "language_fit": (trend.metrics or {}).get("components", {}).get("language_fit")
            if trend
            else None,
            "detected_at": trend.detected_at.isoformat() if trend and trend.detected_at else None,
        }
        own = own_performance(session, lang)
        performance[lang.value] = (
            {"score": round(own[game.id], 3), "basis": "own_posts"}
            if game.id in own
            else {"score": None, "basis": "no_data"}
        )

    modes = _modes(categories)
    ideas = []
    for i, fmt in enumerate(_formats(categories)):
        title_de, title_en = IDEA_TEMPLATES[fmt]
        ideas.append(
            {
                "format": fmt,
                "format_label": FORMATS_BY_KEY[fmt].de,
                "title_de": title_de.format(g=game.name),
                "title_en": title_en.format(g=game.name),
                "mode": modes[i % len(modes)] if modes else None,
                "priority": "high" if rising and i == 0 else "normal",
            }
        )

    scores = [t["score"] for t in trends.values() if t["score"] is not None]
    own_scores = [p["score"] for p in performance.values() if p["score"] is not None]
    rating = round(sum(scores) / len(scores), 1) if scores else None
    if rating is not None and own_scores:
        # Own results count once our videos exist: 70 % trend, 30 % own performance.
        rating = round(0.7 * rating + 0.3 * 100 * sum(own_scores) / len(own_scores), 1)

    return {
        "version": PROFILE_VERSION,
        "method": "rules",
        "audience": {"key": key, "de": label_de, "en": label_en, "secondary": secondary},
        "categories": categories,
        "modes": modes,
        "video_ideas": ideas,
        "trend": trends,
        "channel_performance": performance,
        "rating": rating,
        "rising": rising,
        "rights_note": (
            game.publisher_policy_notes
            or "Publisher-Richtlinie noch nicht geprüft (Rights Agent, Phase 6)."
        ),
        "profiled_at": now.isoformat(),
    }
