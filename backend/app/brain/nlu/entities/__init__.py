"""Entity extraction: run every extractor, drop overlaps, keep the last value per slot."""

from collections.abc import Callable

from app.brain.nlu.entities import contact, dates, party, seating, times
from app.brain.nlu.entities.base import ExtractContext
from app.brain.types import Entity, SlotName

Extractor = Callable[[str, ExtractContext], list[Entity]]

EXTRACTORS: tuple[Extractor, ...] = (
    contact.extract_refs,
    contact.extract_phones,
    dates.extract_dates,
    times.extract_times,
    party.extract_party,
    seating.extract_seating,
    contact.extract_titles,
    contact.extract_names,
)


def _conflicts(a: Entity, b: Entity) -> bool:
    if a.span == b.span and a.type != b.type:
        return False  # one word can mean two things ("tonight" is a date and a time)
    return a.span[0] < b.span[1] and b.span[0] < a.span[1]


def extract_all(text: str, ctx: ExtractContext) -> list[Entity]:
    found = [e for extractor in EXTRACTORS for e in extractor(text, ctx)]
    found.sort(key=lambda e: (-e.confidence, -(e.span[1] - e.span[0]), e.span[0]))
    accepted: list[Entity] = []
    for e in found:
        if not any(_conflicts(e, a) for a in accepted):
            accepted.append(e)
    # "4... no, 5 people": the last mention of a slot wins.
    latest: dict[SlotName, Entity] = {}
    for e in accepted:
        current = latest.get(e.type)
        if current is None or e.span[0] > current.span[0]:
            latest[e.type] = e
    return sorted(latest.values(), key=lambda e: e.span[0])
