"""Hooks that sound like a person, not like a channel bot (Ausbau A7).

Three rules for the first line of a short:

* **no clichés**: phrases every AI or clickbait channel uses ("Du wirst nicht
  glauben …", "krassester Moment ever", "Absolutely insane!!!", "in diesem Video")
  are rejected, as are piles of exclamation marks, all-caps words and emoji;
* **short**: at most ``MAX_WORDS`` words, spoken in about two seconds;
* **not again**: the same wording is not used twice in a row on a channel; the
  Script & Hook Agent passes the channel's recent hooks as ``avoid``.

The template pool has several natural wordings per hook type and language
(:data:`POOL`); a model-written hook that breaks a rule is replaced by a template.
"""

from __future__ import annotations

import hashlib
import re

from core.enums import Language

MAX_WORDS = 14

_CLICHES: dict[Language, tuple[str, ...]] = {
    Language.DE: (
        r"\bdu wirst (es )?nicht glauben\b",
        r"\bunglaublich\b",
        r"\bkrasseste[nrs]?\b",
        r"\bin diesem video\b",
        r"\bheute zeige ich\b",
        r"\bschnall dich an\b",
        r"\bwahnsinn\b",
        r"\bmega\b.*\bmega\b",
        r"\bjeder macht diesen fehler\b",
        r"\bdas hat die welt noch nie gesehen\b",
        r"\bepisch(e|en|er)?\b",
        r"\bever\b",
    ),
    Language.EN: (
        r"\byou won'?t believe\b",
        r"\bunbelievable\b",
        r"\binsane\b",
        r"\bmind[- ]?blowing\b",
        r"\bin this video\b",
        r"\btoday i'?m going to\b",
        r"\bbuckle up\b",
        r"\bwildest\b",
        r"\babsolutely epic\b",
        r"\bpure epic\b",
        r"\bgame[- ]?changer\b",
        r"\bwait (un)?til the end\b",
    ),
}
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
_CAPS = re.compile(r"\b[A-ZÄÖÜ]{4,}\b")


def problems(text: str, language: Language) -> list[str]:
    """Why a hook sounds artificial; empty when it is fine."""
    out = []
    low = text.lower()
    for pattern in _CLICHES[language]:
        if re.search(pattern, low):
            out.append(f"Floskel: {re.search(pattern, low).group(0)}")  # type: ignore[union-attr]
    if text.count("!") > 1:
        out.append("zu viele Ausrufezeichen")
    if _CAPS.search(text):
        out.append("Wort in Großbuchstaben")
    if _EMOJI.search(text):
        out.append("Emoji im gesprochenen Hook")
    if len(text.split()) > MAX_WORDS:
        out.append(f"länger als {MAX_WORDS} Wörter")
    return out


def natural(text: str, language: Language) -> bool:
    return not problems(text, language)


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def pick(
    options: tuple[str, ...], seed: str, avoid: frozenset[str] | set[str] = frozenset()
) -> str:
    """A wording from ``options``: stable for the seed, skipping recently used ones."""
    if not options:
        return ""
    start = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(options)
    order = options[start:] + options[:start]
    used = {_norm(a) for a in avoid}
    for option in order:
        if _norm(option) not in used:
            return option
    return order[0]


#: Several natural wordings per hook type. {g} = game. Short, spoken, no hype words.
POOL: dict[Language, dict[str, tuple[str, ...]]] = {
    Language.DE: {
        "question": (
            "Hättest du das in {g} kommen sehen?",
            "Was passiert hier gleich in {g}?",
            "Wie hättest du das in {g} gelöst?",
            "Siehst du, was in {g} gleich schiefgeht?",
        ),
        "bold_claim": (
            "So etwas siehst du in {g} nicht oft.",
            "Das war der beste Moment meiner {g}-Woche.",
            "Ehrlich, das klappt in {g} fast nie.",
            "Dieser {g}-Moment hat mich echt überrascht.",
        ),
        "countdown": (
            "Achte auf die letzten fünf Sekunden.",
            "Schau genau auf die Mitte vom Bild.",
            "Gleich passiert's, pass auf.",
        ),
        "pov": (
            "POV: Du denkst, in {g} ist alles ruhig …",
            "POV: Deine Runde in {g} läuft gerade perfekt …",
            "POV: Du hast in {g} nur noch einen Versuch …",
        ),
        "challenge": (
            "Würdest du das in {g} schaffen?",
            "Schaffst du das in {g} auch?",
            "Ich wette, das klappt bei dir in {g} nicht beim ersten Mal.",
        ),
        "stakes": (
            "Eine falsche Entscheidung und die Runde in {g} ist vorbei.",
            "Jetzt entscheidet sich alles in {g}.",
            "Ein Fehler hier und alles in {g} war umsonst.",
        ),
    },
    Language.EN: {
        "question": (
            "Did you see this coming in {g}?",
            "What happens next in {g}?",
            "How would you have played this in {g}?",
            "Can you spot what goes wrong in {g}?",
        ),
        "bold_claim": (
            "You don't see this in {g} every day.",
            "Best thing that happened in my {g} week.",
            "Honestly, this almost never works in {g}.",
            "This {g} moment caught me off guard.",
        ),
        "countdown": (
            "Watch the last five seconds.",
            "Keep your eyes on the middle.",
            "Here it comes, watch closely.",
        ),
        "pov": (
            "POV: You think {g} is calm right now …",
            "POV: Your {g} run is going perfectly …",
            "POV: One last try in {g} …",
        ),
        "challenge": (
            "Could you pull this off in {g}?",
            "Think you could do this in {g}?",
            "Bet you can't do this in {g} first try.",
        ),
        "stakes": (
            "One wrong move and this {g} run is over.",
            "Everything comes down to this.",
            "One mistake here and the whole {g} run is gone.",
        ),
    },
}
