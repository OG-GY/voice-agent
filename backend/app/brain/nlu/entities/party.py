"""Party size: "4 people", "table for two", "just me", "me and my wife"."""

import re
from collections.abc import Callable

from app.brain.nlu.entities.base import ExtractContext, bare_number, entity
from app.brain.types import Entity, SlotName

_UNIT = r"(?:people|persons|guests|pax|adults|of us)"
_NOT_TIME = r"(?!:| ?(?:am|pm))"

# (pattern, confidence, value from match)
_RULES: tuple[tuple[re.Pattern[str], float, Callable[[re.Match[str]], int]], ...] = tuple(
    (re.compile(p), c, f)
    for p, c, f in (
        (r"\bme and my [a-z]+ and (\d{1,2}) (?:kids|children|friends|others)\b", 0.85,
         lambda m: int(m.group(1)) + 2),
        (r"\bme and (\d{1,2}) (?:friends|others|colleagues|people)\b", 0.85,
         lambda m: int(m.group(1)) + 1),
        (r"\bme and my (?:wife|husband|partner|friend|mom|mum|dad|girlfriend|boyfriend|son|"
         r"daughter|brother|sister|colleague)\b", 0.85, lambda m: 2),
        (rf"\b(\d{{1,2}}) {_UNIT}\b", 0.95, lambda m: int(m.group(1))),
        (rf"\b(?:table|reservation|booking|seats?) for (\d{{1,2}}){_NOT_TIME}\b", 0.9,
         lambda m: int(m.group(1))),
        (r"\b(?:party|family|group) of (\d{1,2})\b", 0.9, lambda m: int(m.group(1))),
        (r"\b(?:just|only) me\b|\bmyself\b|\balone\b|\bjust 1\b", 0.9, lambda m: 1),
        (r"\bboth of us\b", 0.85, lambda m: 2),
    )
)
_CONF_BARE = 0.8


def extract_party(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []
    for pattern, conf, value in _RULES:
        for m in pattern.finditer(text):
            out.append(entity(SlotName.PARTY_SIZE, value(m), m.span(), m.group(), conf))
    if ctx.expected_slot == SlotName.PARTY_SIZE and (bare := bare_number(text)):
        out.append(
            entity(SlotName.PARTY_SIZE, int(bare.group(1)), bare.span(1), bare.group(1), _CONF_BARE)
        )
    return out
