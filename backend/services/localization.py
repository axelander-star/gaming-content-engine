"""Localization checks and adaptation per language (Phase 9, Agent 10).

The Script & Hook Agent already writes every language from its own templates, so
nothing is translated word for word. This step makes sure each version really is
written for its audience:

* **language check** – the text reads as the target language (no stray words of the
  other language; game names are ignored),
* **form** – no double spaces or repeated words, sentences start with a capital and
  end with punctuation,
* **audience** – language-specific hashtags and call to action,
* **no copy** – hook and title differ from the other language version of the clip.

Mechanical problems are fixed automatically and recorded; a text in the wrong
language is an error the operator has to look at. This is a rule-based check, not
a full spelling dictionary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.enums import Language

#: Frequent function words; two or more hits of the other language mean "wrong language".
MARKERS: dict[Language, frozenset[str]] = {
    Language.DE: frozenset(
        [
            "und",
            "der",
            "das",
            "nicht",
            "ist",
            "ein",
            "eine",
            "mit",
            "für",
            "auf",
            "wie",
            "du",
            "dich",
            "hier",
            "jetzt",
        ]
    ),
    Language.EN: frozenset(
        [
            "the",
            "and",
            "you",
            "your",
            "this",
            "that",
            "with",
            "for",
            "what",
            "is",
            "are",
            "not",
            "here",
            "now",
        ]
    ),
}
HASHTAGS = {Language.DE: "#GamingDeutsch", Language.EN: "#GamingClips"}
END_PUNCT = (".", "!", "?", "…", ":")
WORD = re.compile(r"[\wäöüÄÖÜß']+")


@dataclass
class TextCheck:
    text: str
    fixes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _strip_names(text: str, names: list[str]) -> str:
    for name in names:
        if name:
            text = text.replace(name, " ")
    return text


def wrong_language(text: str, language: Language, names: list[str]) -> list[str]:
    """Words of the other language found in ``text`` (ignoring game names)."""
    other = Language.EN if language == Language.DE else Language.DE
    words = [w.lower() for w in WORD.findall(_strip_names(text, names))]
    hits = [w for w in words if w in MARKERS[other] and w not in MARKERS[language]]
    return hits if len(hits) >= 2 else []


def tidy(text: str, *, sentence: bool = True) -> tuple[str, list[str]]:
    """Fix mechanical problems. Returns the text and what was changed."""
    fixes: list[str] = []
    cleaned = re.sub(r"[ \t]{2,}", " ", text).strip()
    if cleaned != text.strip():
        fixes.append("doppelte Leerzeichen entfernt")
    repeated = re.sub(r"\b(\w+)( \1\b)+", r"\1", cleaned, flags=re.IGNORECASE)
    if repeated != cleaned:
        fixes.append("doppeltes Wort entfernt")
        cleaned = repeated
    if sentence and cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
        fixes.append("Satzanfang großgeschrieben")
    if sentence and cleaned and not cleaned.endswith(END_PUNCT):
        cleaned += "."
        fixes.append("Satzzeichen ergänzt")
    return cleaned, fixes


def check_text(
    text: str, language: Language, names: list[str], *, sentence: bool = True
) -> TextCheck:
    fixed, fixes = tidy(text, sentence=sentence)
    result = TextCheck(fixed, fixes)
    hits = wrong_language(fixed, language, names)
    if hits:
        result.problems.append(f"Wörter der anderen Sprache: {', '.join(sorted(set(hits)))}")
    return result


def adapt_description(description: str, language: Language) -> tuple[str, list[str]]:
    """Add the audience hashtag of the language if missing."""
    tag = HASHTAGS[language]
    if tag in description:
        return description, []
    lines = description.rstrip().split("\n")
    if lines and lines[-1].startswith("#"):
        lines[-1] = f"{lines[-1]} {tag}"
    else:
        lines += ["", tag]
    return "\n".join(lines), [f"Hashtag {tag} ergänzt"]


def same_as_other_language(texts: dict[str, str], other: dict[str, str]) -> list[str]:
    """Fields that are identical to the other language version (a copy, not localized)."""
    return [k for k, v in texts.items() if v and other.get(k) == v]
