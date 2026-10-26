"""Static restaurant data for The Copper Pot (fictional)."""

from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum


class Seating(StrEnum):
    GENERAL = "general"
    WINDOW = "window"
    PRIVATE = "private"


@dataclass(frozen=True)
class Table:
    id: str
    category: Seating
    seats: int
    min_party: int = 1


def _tables() -> tuple[Table, ...]:
    general = [Table(f"G2-{i}", Seating.GENERAL, 2) for i in range(1, 5)]
    general += [Table(f"G4-{i}", Seating.GENERAL, 4) for i in range(1, 4)]
    general += [Table("G6-1", Seating.GENERAL, 6)]
    window = [Table(f"W2-{i}", Seating.WINDOW, 2) for i in range(1, 4)]
    window += [Table(f"W4-{i}", Seating.WINDOW, 4) for i in range(1, 3)]
    private = [Table(f"P6-{i}", Seating.PRIVATE, 6, min_party=3) for i in range(1, 3)]
    private += [Table("P8-1", Seating.PRIVATE, 8, min_party=3)]
    return tuple(general + window + private)


def _hours() -> dict[int, tuple[time, time] | None]:
    """Weekday (Monday=0) -> (open, close), or None when closed."""
    open_day = (time(12, 0), time(22, 0))
    return {0: None, 1: open_day, 2: open_day, 3: open_day, 4: open_day, 5: open_day, 6: open_day}


@dataclass(frozen=True)
class RestaurantConfig:
    name: str = "The Copper Pot"
    address: str = "12 Harbour Lane, Old Town"
    opening_hours: dict[int, tuple[time, time] | None] = field(default_factory=_hours)
    last_seating: time = time(21, 0)
    slot_minutes: int = 30
    sitting_minutes: int = 90
    booking_window_days: int = 60
    max_party: int = 8
    tables: tuple[Table, ...] = field(default_factory=_tables)

    def hours_for(self, weekday: int) -> tuple[time, time] | None:
        return self.opening_hours.get(weekday)

    def tables_in(self, category: Seating) -> tuple[Table, ...]:
        return tuple(t for t in self.tables if t.category == category)


DEFAULT_RESTAURANT = RestaurantConfig()
