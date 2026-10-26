"""Shared helpers for entity extractors."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time

from app.brain.types import Entity, SlotName
from app.services.restaurant import RestaurantConfig


@dataclass(frozen=True)
class ExtractContext:
    now: datetime
    restaurant: RestaurantConfig
    expected_slot: SlotName | None = None
    # True while we're offering alternatives: "the 2nd" means the second option, not a date.
    choosing_option: bool = False

    @property
    def today(self) -> date:
        return self.now.date()


def entity(
    slot: SlotName, value: object, span: tuple[int, int], text: str, confidence: float
) -> Entity:
    return Entity(type=slot, value=value, span=span, text=text, confidence=confidence)


def service_window(restaurant: RestaurantConfig) -> tuple[time, time]:
    """Earliest opening and latest closing time across all open days."""
    hours = [h for h in restaurant.opening_hours.values() if h]
    return min(h[0] for h in hours), max(h[1] for h in hours)


_BARE_NUMBER = re.compile(
    r"^(?:(?:actually|no|um|well|ok|okay|so) )*"
    r"(?:(?:make it|change it to|change to|its|it's|at|for|about|around|maybe) )?"
    r"(\d{1,2})(?: (?:please|then))?$"
)


def bare_number(text: str) -> re.Match[str] | None:
    """Match an utterance that is just a number ("7", "make it 8"); caller checks the context."""
    return _BARE_NUMBER.match(text)
