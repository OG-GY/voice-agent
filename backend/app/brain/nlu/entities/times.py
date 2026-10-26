"""Times: "7pm", "7:30", "at 7", "evening". Bare hours 1-11 are read as PM when open then."""

import re
from datetime import time

from app.brain.nlu import lexicon
from app.brain.nlu.entities.base import ExtractContext, bare_number, entity, service_window
from app.brain.types import Entity, SlotName, TimeRange

_MERIDIEM = re.compile(r"\b(\d{1,2})(?::(\d{2}))? ?(am|pm)\b")
_COLON = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?! ?(?:am|pm))(?![\d:])")
_AT_HOUR = re.compile(
    r"\b(?:at|around|about|by|from) (\d{1,2})\b(?![:\d])(?! ?(?:am|pm|people|persons|guests|pax))"
)
_RANGE = re.compile(r"\b(" + "|".join(lexicon.TIME_RANGES) + r")\b")

_CONF_EXACT = 0.95
_CONF_INFERRED = 0.85
_CONF_BARE = 0.75
_CONF_RANGE = 0.7
_NOON_HOUR = 12


def _infer_hour(hour: int, ctx: ExtractContext) -> int:
    """Hour 1-11 with no am/pm: PM if that falls inside opening hours."""
    if hour >= _NOON_HOUR:
        return hour
    lo, hi = service_window(ctx.restaurant)
    return hour + 12 if lo.hour <= hour + 12 <= hi.hour else hour


def extract_times(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []

    def add(span: tuple[int, int], matched: str, value: object, conf: float) -> None:
        out.append(entity(SlotName.TIME, value, span, matched, conf))

    for m in _MERIDIEM.finditer(text):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not (1 <= hour <= _NOON_HOUR and minute < 60):
            continue
        hour = hour % 12 + (12 if m.group(3) == "pm" else 0)
        add(m.span(), m.group(), time(hour, minute), _CONF_EXACT)
    for m in _COLON.finditer(text):
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            continue
        explicit = hour == 0 or hour >= _NOON_HOUR
        value = time(hour if explicit else _infer_hour(hour, ctx), minute)
        add(m.span(), m.group(), value, _CONF_EXACT if explicit else _CONF_INFERRED)
    for m in _AT_HOUR.finditer(text):
        hour = int(m.group(1))
        if 1 <= hour <= 23:
            add(m.span(1), m.group(1), time(_infer_hour(hour, ctx), 0), _CONF_INFERRED)
    for m in _RANGE.finditer(text):
        start, end = lexicon.TIME_RANGES[m.group(1)]
        add(m.span(), m.group(), TimeRange(start=start, end=end, label=m.group(1)), _CONF_RANGE)
    if ctx.expected_slot == SlotName.TIME and (bare := bare_number(text)):
        hour = int(bare.group(1))
        if 1 <= hour <= 23:
            add(bare.span(1), bare.group(1), time(_infer_hour(hour, ctx), 0), _CONF_BARE)
    return out
