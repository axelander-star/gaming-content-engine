"""Creative concepts, hooks and scripts (Phase 8, Agents 8 and 9).

Rule-based and free of charge. Every choice is explained, so the Learning Agent
(Phase 14) can later shift the weights with real performance data.

**Formats** come from ``core.catalog.VIDEO_FORMATS``. Only formats whose promise can
be checked from the measured scene signals are chosen automatically. Formats that
need an understanding of the content (funny, near miss, tips, challenge, comparison,
analysis) would promise something nobody verified; they stay manual until a vision
model or an operator note can confirm them.

**Hooks** are opening structures. Every language has its own wording, written for
that audience, not translated.

**Variants** of the same clip differ in hook structure and, where a second format
fits the scene, in format too. Variant A is the best guess; the others are
experiments for the Learning Agent.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from core.catalog import FORMATS_BY_KEY
from core.enums import Language

Scores = dict[str, float]

#: How well the measured scene signals support a format's promise (0..1).
SIGNAL_FORMATS: dict[str, Callable[[Scores], float]] = {
    "epic_scene": lambda s: 0.6 * s.get("motion", 0) + 0.4 * s.get("audio", 0),
    "surprise": lambda s: s.get("surprise", 0),
    "unexpected_twist": lambda s: 0.6 * s.get("surprise", 0) + 0.4 * s.get("buildup", 0),
    "storytelling": lambda s: 0.7 * s.get("buildup", 0) + 0.3 * s.get("audio", 0),
}
#: Formats that need content understanding; never chosen automatically.
CONTENT_FORMATS = (
    "funny_moments",
    "near_miss",
    "tips_tricks",
    "challenge",
    "comparison",
    "short_analysis",
)
MIN_FORMAT_FIT = 0.3

#: Weights of the concept score (sum 1.0).
CONCEPT_WEIGHTS = {"signal": 0.6, "game_profile": 0.2, "performance": 0.2}
NEUTRAL = 0.5  # unknown values (no own videos yet) count neutral

HOOK_TYPES = ("question", "bold_claim", "countdown", "pov", "challenge", "stakes")
HOOK_LABELS = {
    "question": "Frage",
    "bold_claim": "Starke Behauptung",
    "countdown": "Countdown",
    "pov": "Ich-Perspektive (POV)",
    "challenge": "Herausforderung an Zuschauer",
    "stakes": "Was auf dem Spiel steht",
}
#: Which hooks suit which format (best first).
FORMAT_HOOKS: dict[str, tuple[str, ...]] = {
    "epic_scene": ("bold_claim", "pov", "countdown", "challenge"),
    "surprise": ("question", "countdown", "pov", "bold_claim"),
    "unexpected_twist": ("question", "stakes", "countdown", "bold_claim"),
    "storytelling": ("stakes", "pov", "question", "bold_claim"),
}

# Hook lines per language. {g} = game. Several wordings per hook keep channels varied.
HOOKS: dict[Language, dict[str, tuple[str, ...]]] = {
    Language.DE: {
        "question": ("Hättest du das in {g} kommen sehen?", "Was passiert hier gleich in {g}?"),
        "bold_claim": (
            "Das ist der krasseste {g}-Moment, den ich kenne.",
            "So etwas siehst du in {g} nicht oft.",
        ),
        "countdown": ("Achte auf die letzten fünf Sekunden.", "Warte bis zum Ende."),
        "pov": (
            "POV: Du denkst, in {g} ist alles ruhig …",
            "POV: Deine Runde in {g} läuft gerade perfekt …",
        ),
        "challenge": ("Würdest du das in {g} schaffen?", "Schaffst du das in {g} auch?"),
        "stakes": (
            "Eine falsche Entscheidung und die Runde in {g} ist vorbei.",
            "Jetzt entscheidet sich alles in {g}.",
        ),
    },
    Language.EN: {
        "question": ("Did you see this coming in {g}?", "What happens next in {g}?"),
        "bold_claim": (
            "This is the wildest {g} moment I've seen.",
            "You don't see this in {g} every day.",
        ),
        "countdown": ("Watch the last five seconds.", "Wait for the end."),
        "pov": (
            "POV: You think {g} is calm right now …",
            "POV: Your {g} run is going perfectly …",
        ),
        "challenge": ("Could you pull this off in {g}?", "Think you could do this in {g}?"),
        "stakes": ("One wrong move and this {g} run is over.", "Everything comes down to this."),
    },
}

# Voiceover beats per format and language: setup, build-up, payoff.
BEATS: dict[Language, dict[str, tuple[str, str, str]]] = {
    Language.DE: {
        "epic_scene": (
            "Erst sieht alles normal aus.",
            "Dann geht es richtig los.",
            "Einfach episch.",
        ),
        "surprise": (
            "Alles läuft nach Plan.",
            "Pass jetzt genau auf.",
            "Damit hat keiner gerechnet.",
        ),
        "unexpected_twist": (
            "Die Lage scheint klar.",
            "Aber dann dreht sich alles.",
            "Was für eine Wendung.",
        ),
        "storytelling": (
            "Es beginnt ganz harmlos.",
            "Die Spannung steigt mit jeder Sekunde.",
            "Und genau so endet es.",
        ),
    },
    Language.EN: {
        "epic_scene": ("It all looks normal at first.", "Then it kicks off.", "Absolutely epic."),
        "surprise": ("Everything is going to plan.", "Now watch closely.", "Nobody expected that."),
        "unexpected_twist": (
            "It looks like it's over.",
            "But then everything flips.",
            "What a twist.",
        ),
        "storytelling": (
            "It starts out harmless.",
            "The tension builds every second.",
            "And this is how it ends.",
        ),
    },
}

CTAS: dict[Language, tuple[str, ...]] = {
    Language.DE: (
        "Folge für mehr {g}-Momente.",
        "Schreib in die Kommentare, wie du reagiert hättest.",
    ),
    Language.EN: (
        "Follow for more {g} moments.",
        "Tell me in the comments what you would have done.",
    ),
}
TITLES: dict[Language, dict[str, str]] = {
    Language.DE: {
        "epic_scene": "{g}: dieser Moment ist einfach episch",
        "surprise": "{g}: damit hat niemand gerechnet",
        "unexpected_twist": "{g}: die Wendung am Ende",
        "storytelling": "{g}: so schnell kann es gehen",
    },
    Language.EN: {
        "epic_scene": "{g}: this moment is pure epic",
        "surprise": "{g}: nobody saw this coming",
        "unexpected_twist": "{g}: wait for the twist",
        "storytelling": "{g}: how fast it can turn",
    },
}
CREDIT = {Language.DE: "Gameplay: {s} (lizenziert)", Language.EN: "Gameplay: {s} (licensed)"}

#: Spoken words per second in a short voiceover (calm, understandable pace).
WORDS_PER_SECOND = {Language.DE: 2.2, Language.EN: 2.5}
TITLE_MAX = 100
HOOK_S = 2.5
CTA_S = 3.0
PAUSE_S = 0.4


@dataclass
class Concept:
    video_format: str
    hook_type: str
    score: float
    components: dict[str, float]
    experiment: bool = False
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pick(options: tuple[str, ...], seed: str) -> str:
    """Stable choice among wordings, so re-runs give the same text."""
    digest = hashlib.sha256(seed.encode()).digest()
    return options[digest[0] % len(options)]


def format_fits(scores: Scores) -> dict[str, float]:
    return {key: round(min(1.0, max(0.0, fn(scores))), 3) for key, fn in SIGNAL_FORMATS.items()}


def rank_concepts(
    scores: Scores,
    profile_formats: list[str],
    performance: dict[str, float],
) -> list[Concept]:
    """All automatically allowed (format, hook) pairs, best first.

    ``profile_formats`` are the Game Intelligence ideas for this game and language;
    ``performance`` maps format keys to 0..1 from own published videos (empty until
    Phase 14 delivers data, then unknown formats count neutral).
    """
    out: list[Concept] = []
    for fmt, fit in format_fits(scores).items():
        if fit < MIN_FORMAT_FIT:
            continue
        components = {
            "signal": fit,
            "game_profile": 1.0 if fmt in profile_formats else 0.0,
            "performance": round(performance.get(fmt, NEUTRAL), 3),
        }
        base = sum(CONCEPT_WEIGHTS[k] * v for k, v in components.items())
        for rank, hook in enumerate(FORMAT_HOOKS[fmt]):
            score = round(base - 0.02 * rank, 3)  # suitability order of the hooks
            out.append(Concept(fmt, hook, score, components))
    out.sort(key=lambda c: (-c.score, c.video_format, c.hook_type))
    return out


def choose_variants(concepts: list[Concept], count: int) -> list[Concept]:
    """Best concept plus up to ``count - 1`` that really differ.

    Every further variant uses a hook structure not used yet; a second format is
    preferred when one fits, so the test compares more than the first sentence.
    """
    if not concepts:
        return []
    first = concepts[0]
    first.reasons.append("höchste Bewertung")
    chosen = [first]
    while len(chosen) < count:
        used_hooks = {c.hook_type for c in chosen}
        used_formats = {c.video_format for c in chosen}
        fresh = [c for c in concepts if c.hook_type not in used_hooks]
        if not fresh:
            break
        other_format = [c for c in fresh if c.video_format not in used_formats]
        pick = other_format[0] if other_format else fresh[0]
        pick.experiment = True
        pick.reasons.append(
            "Test: anderes Format und andere Hook-Struktur"
            if other_format
            else "Test: andere Hook-Struktur"
        )
        chosen.append(pick)
    return chosen


@dataclass
class ScriptDraft:
    hook: str
    voiceover_text: str
    call_to_action: str
    title: str
    description: str
    beats: list[dict[str, Any]]
    words: int
    word_budget: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_script(
    *,
    language: Language,
    video_format: str,
    hook_type: str,
    game: str,
    source_name: str,
    duration_s: float,
    seed: str,
) -> ScriptDraft:
    """Hook, voiceover beats, call to action, title and description for one variant.

    The voiceover is shortened until it fits the clip at a calm speaking pace.
    """
    g = game or ("dem Spiel" if language == Language.DE else "this game")
    hook = _pick(HOOKS[language][hook_type], f"{seed}:hook").format(g=g)
    setup, build, payoff = BEATS[language][video_format]
    cta = _pick(CTAS[language], f"{seed}:cta").format(g=g)
    wps = WORDS_PER_SECOND[language]
    budget = int(duration_s * wps)

    def words(*parts: str) -> int:
        return sum(len(p.split()) for p in parts)

    def need(text: str) -> float:
        """Seconds to say ``text`` calmly, with a short breath after it."""
        return words(text) / wps + PAUSE_S if text else 0.0

    lines = [setup, build, payoff]
    kinds = ["setup", "buildup", "payoff"]

    def total() -> float:
        return max(HOOK_S, need(hook)) + sum(need(t) for t in lines) + max(CTA_S, need(cta))

    while lines and (words(hook, *lines, cta) > budget or total() > duration_s):
        lines.pop(0)  # drop setup first, the payoff stays
        kinds.pop(0)
    if cta and (words(hook, *lines, cta) > budget or total() > duration_s):
        cta = ""
    # Beats follow each other; every beat gets the time it needs to be said calmly
    # and the remaining time is shared out as pauses, so the payoff lands late.
    hook_end = max(HOOK_S, need(hook))
    cta_start = duration_s - (max(CTA_S, need(cta)) if cta else 0.0)
    slack = max(0.0, cta_start - hook_end - sum(need(t) for t in lines))
    gap = slack / len(lines) if lines else 0.0
    beats: list[dict[str, Any]] = [
        {"kind": "hook", "start_s": 0.0, "end_s": round(hook_end, 1), "text": hook}
    ]
    t = hook_end
    for kind, text in zip(kinds, lines, strict=True):
        start = t + gap  # pause before each line builds tension
        t = start + need(text)
        beats.append({"kind": kind, "start_s": round(start, 1), "end_s": round(t, 1), "text": text})
    if lines:
        beats[-1]["end_s"] = round(cta_start, 1)
    if cta:
        beats.append(
            {
                "kind": "cta",
                "start_s": round(cta_start, 1),
                "end_s": round(duration_s, 1),
                "text": cta,
            }
        )
    title = TITLES[language][video_format].format(g=g)[:TITLE_MAX]
    fmt_label = (
        FORMATS_BY_KEY[video_format].de
        if language == Language.DE
        else (FORMATS_BY_KEY[video_format].en)
    )
    tag = "".join(ch for ch in game.title() if ch.isalnum()) if game else ""
    hashtags = " ".join(t for t in (f"#{tag}" if tag else "", "#Gaming") if t)
    description = "\n".join(
        [hook, "", f"{fmt_label} · {g}", CREDIT[language].format(s=source_name), "", hashtags]
    )
    voiceover = " ".join([*lines, cta]).strip()
    return ScriptDraft(
        hook=hook,
        voiceover_text=voiceover,
        call_to_action=cta,
        title=title,
        description=description,
        beats=beats,
        words=words(hook, voiceover),
        word_budget=budget,
    )
