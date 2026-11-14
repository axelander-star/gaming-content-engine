"""Static domain knowledge shared by several agents.

* Video formats from PROJECT_SPEC section 6 (Creative Director).
* Game categories with the audience they speak to and typical game modes.

This is curated, versioned knowledge (no external calls). Later phases may
refine it from own performance data (Learning agent).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoFormat:
    key: str
    de: str
    en: str


VIDEO_FORMATS: tuple[VideoFormat, ...] = (
    VideoFormat("funny_moments", "Lustige Gaming-Momente", "Funny gaming moments"),
    VideoFormat("unexpected_twist", "Unerwartete Wendung", "Unexpected twist"),
    VideoFormat("epic_scene", "Epische Szene", "Epic scene"),
    VideoFormat("near_miss", "Knapp gescheitert", "Near miss"),
    VideoFormat("surprise", "Überraschung", "Surprise"),
    VideoFormat("tips_tricks", "Tipps und Tricks", "Tips and tricks"),
    VideoFormat("storytelling", "Storytelling", "Storytelling"),
    VideoFormat("challenge", "Challenge-Clip", "Challenge clip"),
    VideoFormat("comparison", "Vergleich", "Comparison"),
    VideoFormat("short_analysis", "Kurze Spielanalyse", "Short game analysis"),
)
FORMATS_BY_KEY = {f.key: f for f in VIDEO_FORMATS}


@dataclass(frozen=True)
class Category:
    key: str
    audience: str  # audience segment key
    audience_de: str
    audience_en: str
    modes: tuple[str, ...]
    formats: tuple[str, ...]  # best-fitting video formats, most suitable first


CATEGORIES: tuple[Category, ...] = (
    Category("shooter", "action", "Shooter- und Action-Fans", "Shooter and action fans",
             ("Ranked", "Team Deathmatch", "Search & Destroy"),
             ("epic_scene", "near_miss", "tips_tricks", "funny_moments")),
    Category("battle_royale", "action", "Shooter- und Action-Fans", "Shooter and action fans",
             ("Solo", "Duo", "Squad"),
             ("near_miss", "epic_scene", "unexpected_twist", "challenge")),
    Category("rpg", "story", "Story- und Rollenspiel-Fans", "Story and RPG fans",
             ("Kampagne", "Bosskampf", "Builds"),
             ("storytelling", "short_analysis", "tips_tricks", "epic_scene")),
    Category("strategy", "strategy", "Strategie- und Taktik-Fans", "Strategy and tactics fans",
             ("Ranked", "Kampagne", "Koop"),
             ("short_analysis", "tips_tricks", "comparison", "unexpected_twist")),
    Category("moba", "strategy", "Strategie- und Taktik-Fans", "Strategy and tactics fans",
             ("Ranked", "ARAM", "Turnier"),
             ("epic_scene", "short_analysis", "near_miss", "tips_tricks")),
    Category("sports", "sports", "Sport- und Rennspiel-Fans", "Sports and racing fans",
             ("Karriere", "Online-Liga", "Ultimate Team"),
             ("epic_scene", "funny_moments", "comparison", "challenge")),
    Category("racing", "sports", "Sport- und Rennspiel-Fans", "Sports and racing fans",
             ("Zeitfahren", "Online-Rennen", "Drift"),
             ("near_miss", "epic_scene", "challenge", "comparison")),
    Category("horror", "horror", "Horror- und Thriller-Fans", "Horror and thriller fans",
             ("Kampagne", "Koop", "Versus"),
             ("surprise", "funny_moments", "storytelling", "unexpected_twist")),
    Category("sandbox", "creative", "Kreativ- und Sandbox-Fans", "Creative and sandbox fans",
             ("Survival", "Kreativmodus", "Multiplayer"),
             ("challenge", "tips_tricks", "surprise", "funny_moments")),
    Category("indie", "casual", "Casual- und Indie-Fans", "Casual and indie fans",
             ("Story", "Koop", "Speedrun"),
             ("surprise", "funny_moments", "short_analysis", "challenge")),
)  # fmt: skip
CATEGORIES_BY_KEY = {c.key: c for c in CATEGORIES}

GENERAL_AUDIENCE = ("general", "Allgemeine Gaming-Zielgruppe", "General gaming audience")


def audience_for(categories: list[str] | tuple[str, ...]) -> tuple[str, str, str]:
    """(key, German label, English label) of the main audience of a game."""
    for key in categories:
        cat = CATEGORIES_BY_KEY.get(key)
        if cat:
            return cat.audience, cat.audience_de, cat.audience_en
    return GENERAL_AUDIENCE
