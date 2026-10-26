"""Turn values into speech-friendly phrases."""

from collections.abc import Sequence
from datetime import date, time

from app.brain.types import Option
from app.services.restaurant import RestaurantConfig, Seating

_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)
_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)
_NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve",
)
_SEATING = {
    Seating.GENERAL: "a regular table",
    Seating.WINDOW: "a window table",
    Seating.PRIVATE: "a private family table",
}
_RANGE_PHRASES = {
    "lunch": "lunchtime", "afternoon": "the afternoon", "evening": "the evening",
    "dinner": "the evening", "tonight": "the evening",
}
_ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}
_NOON = 12
_PHONE_GROUPS = {10: (4, 3, 3), 11: (4, 3, 4)}


def say_number(n: int) -> str:
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else str(n)


def say_party(n: int) -> str:
    return f"{say_number(n)} {'person' if n == 1 else 'people'}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else _ORDINAL_SUFFIXES.get(n % 10, "th")
    return f"{n}{suffix}"


def say_weekday(d: date) -> str:
    return _WEEKDAYS[d.weekday()]


def say_date(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    text = f"{say_weekday(d)} the {_ordinal(d.day)}"
    return text if d.month == today.month else f"{text} of {_MONTHS[d.month - 1]}"


def say_on(d: date, today: date) -> str:
    """"today", "tomorrow" or "on Friday the 30th"."""
    text = say_date(d, today)
    return text if text in ("today", "tomorrow") else f"on {text}"


def say_time(t: time) -> str:
    if t.hour == _NOON and t.minute == 0:
        return "noon"
    if t.hour == 0 and t.minute == 0:
        return "midnight"
    minutes = f":{t.minute:02d}" if t.minute else ""
    return f"{t.hour % 12 or 12}{minutes} {'PM' if t.hour >= _NOON else 'AM'}"


def say_seating(seating: Seating) -> str:
    return _SEATING[seating]


def say_range(label: str) -> str:
    return _RANGE_PHRASES.get(label, label)


def say_phone(digits: str) -> str:
    sizes = _PHONE_GROUPS.get(len(digits), (4, 3, 3))
    groups: list[str] = []
    start = 0
    for size in sizes:
        chunk = digits[start:start + size]
        start += size
        if chunk:
            groups.append(" ".join(chunk))
    if digits[start:]:
        groups.append(" ".join(digits[start:]))
    return ", ".join(groups)


def say_ref(ref: str) -> str:
    """"CP-4821" -> "C P, 4 8 2 1"."""
    prefix, _, digits = ref.partition("-")
    return f"{' '.join(prefix)}, {' '.join(digits)}"


def join_or(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def say_options(options: Sequence[Option]) -> str:
    if len({o.seating for o in options}) == 1:
        times = join_or([say_time(o.time) for o in options])
        return f"{say_seating(options[0].seating)} at {times}"
    return join_or([f"{say_seating(o.seating)} at {say_time(o.time)}" for o in options])


def say_open_days(restaurant: RestaurantConfig) -> str:
    days = sorted(d for d, hours in restaurant.opening_hours.items() if hours)
    if days == list(range(days[0], days[-1] + 1)) and len(days) > 2:
        return f"{_WEEKDAYS[days[0]]} to {_WEEKDAYS[days[-1]]}"
    return join_or([_WEEKDAYS[d] for d in days])


def say_closed_days(restaurant: RestaurantConfig) -> str:
    closed = sorted(d for d, hours in restaurant.opening_hours.items() if not hours)
    return join_or([f"{_WEEKDAYS[d]}s" for d in closed])
