"""Pure validators for the booking slots. Each returns a ValidationIssue, or None when fine."""

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Any

from app.brain.nlu.entities.base import service_window
from app.brain.policy.common import PolicyContext
from app.brain.state import DialogueState
from app.brain.types import Seating, SlotName

_MINUTES_PER_HOUR = 60
_LOOKAROUND_DAYS = 7
_MIN_PARTY = 1


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    slot: SlotName
    params: dict[str, Any] = field(default_factory=dict)


def _as_time(minutes: int) -> time:
    return time(minutes // _MINUTES_PER_HOUR, minutes % _MINUTES_PER_HOUR)


def _minutes(t: time) -> int:
    return t.hour * _MINUTES_PER_HOUR + t.minute


def _open_neighbours(d: date, ctx: PolicyContext) -> list[date]:
    """The nearest open day before (not in the past) and after a closed day."""
    today = ctx.now.date()
    found: list[date] = []
    for step in range(1, _LOOKAROUND_DAYS + 1):
        before = d - timedelta(days=step)
        if before >= today and ctx.restaurant.hours_for(before.weekday()):
            found.append(before)
            break
    for step in range(1, _LOOKAROUND_DAYS + 1):
        after = d + timedelta(days=step)
        if ctx.restaurant.hours_for(after.weekday()):
            found.append(after)
            break
    return found


def validate_date(d: date, ctx: PolicyContext) -> ValidationIssue | None:
    today = ctx.now.date()
    window = ctx.restaurant.booking_window_days
    if d < today:
        return ValidationIssue("date_past", SlotName.DATE, {"date": d})
    if d > today + timedelta(days=window):
        return ValidationIssue("date_too_far", SlotName.DATE, {"days": window})
    if ctx.restaurant.hours_for(d.weekday()) is None:
        return ValidationIssue(
            "closed_day", SlotName.DATE, {"date": d, "options": _open_neighbours(d, ctx)}
        )
    return None


def validate_time(t: time, d: date | None, ctx: PolicyContext) -> ValidationIssue | None:
    r = ctx.restaurant
    hours = r.hours_for(d.weekday()) if d else None
    opens, closes = hours if hours else service_window(r)
    last = min(r.last_seating, closes)
    if t < opens or t > last:
        suggestion = opens if t < opens else last
        params = {"open": opens, "last": last, "suggestion": suggestion}
        return ValidationIssue("time_outside_hours", SlotName.TIME, params)
    minutes = _minutes(t)
    if minutes % r.slot_minutes:
        floor = minutes - minutes % r.slot_minutes
        options = [_as_time(floor)]
        if floor + r.slot_minutes <= _minutes(last):
            options.append(_as_time(floor + r.slot_minutes))
        return ValidationIssue("time_off_slot", SlotName.TIME, {"options": options})
    if d == ctx.now.date() and t <= ctx.now.time():
        later = [s for s in ctx.repo.slots(d) if s > ctx.now.time()]
        return ValidationIssue(
            "time_passed", SlotName.TIME, {"suggestion": later[0] if later else None}
        )
    return None


def validate_party(n: int, ctx: PolicyContext) -> ValidationIssue | None:
    if n < _MIN_PARTY:
        return ValidationIssue("party_invalid", SlotName.PARTY_SIZE, {"party": n})
    if n > ctx.restaurant.max_party:
        return ValidationIssue(
            "party_too_large", SlotName.PARTY_SIZE, {"party": n, "max": ctx.restaurant.max_party}
        )
    return None


def _party_range(seating: Seating, ctx: PolicyContext) -> tuple[int, int]:
    tables = ctx.restaurant.tables_in(seating)
    return min(t.min_party for t in tables), max(t.seats for t in tables)


def validate_seating(seating: Seating, n: int, ctx: PolicyContext) -> ValidationIssue | None:
    low, high = _party_range(seating, ctx)
    if low <= n <= high:
        return None
    fitting = [c for c in Seating if c is not seating and _party_range(c, ctx)[0] <= n <= _party_range(c, ctx)[1]]
    params = {
        "seating": seating, "party": n, "reason": "min" if n < low else "max",
        "limit": low if n < low else high, "options": fitting,
    }
    return ValidationIssue("seating_party_mismatch", SlotName.SEATING, params)


def first_issue(state: DialogueState, ctx: PolicyContext) -> ValidationIssue | None:
    """Validate every filled booking slot, in the order we collect them."""
    d = state.value(SlotName.DATE) if state.is_filled(SlotName.DATE) else None
    if d is not None and (issue := validate_date(d, ctx)):
        return issue
    if state.is_filled(SlotName.TIME) and (
        issue := validate_time(state.value(SlotName.TIME), d, ctx)
    ):
        return issue
    n = state.value(SlotName.PARTY_SIZE) if state.is_filled(SlotName.PARTY_SIZE) else None
    if n is not None and (issue := validate_party(n, ctx)):
        return issue
    if n is not None and state.is_filled(SlotName.SEATING):
        return validate_seating(state.value(SlotName.SEATING), n, ctx)
    return None
