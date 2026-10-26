"""Seating preference: private / window / general (and "any table is fine")."""

import re

from app.brain.nlu import lexicon
from app.brain.nlu.entities.base import ExtractContext, entity
from app.brain.types import Entity, Seating, SlotName


def _alternation(phrases: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(phrases, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in ordered) + r")\b")


_CATEGORY = {cat: _alternation(words) for cat, words in lexicon.SEATING_PHRASES.items()}
_INDIFFERENT = _alternation(lexicon.INDIFFERENT_ALWAYS)
_INDIFFERENT_ASKED = _alternation(lexicon.INDIFFERENT_WHEN_ASKED)

_CONF_EXPLICIT = 0.95
_CONF_INDIFFERENT = 0.8


def extract_seating(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []
    for category, pattern in _CATEGORY.items():
        for m in pattern.finditer(text):
            out.append(entity(SlotName.SEATING, category, m.span(), m.group(), _CONF_EXPLICIT))
    indifferent = [_INDIFFERENT]
    if ctx.expected_slot == SlotName.SEATING:
        indifferent.append(_INDIFFERENT_ASKED)
    for pattern in indifferent:
        for m in pattern.finditer(text):
            out.append(
                entity(SlotName.SEATING, Seating.GENERAL, m.span(), m.group(), _CONF_INDIFFERENT)
            )
    return out
