"""Fake bookings, dated relative to today, so the "full" paths are always reachable."""

from datetime import date, datetime, time, timedelta

from app.services.booking import Booking, InMemoryBookingRepository, VerifyLimits
from app.services.clock import Clock
from app.services.restaurant import RestaurantConfig, Seating, Table

_FIRST_REF = 1001
_FRIDAY, _SATURDAY = 4, 5


_FIRST_NAMES = ("Alex", "Sam", "Jordan", "Casey", "Riley", "Taylor", "Morgan", "Jamie", "Quinn", "Avery")
_LAST_NAMES = ("Sample", "Example", "Testcase", "Demo")


def _fake_name(n: int) -> str:
    """Fake, letters-only names (callers have to be able to say them): CP-1001 is "Alex Sample"."""
    i = n - 1
    return f"{_FIRST_NAMES[i % len(_FIRST_NAMES)]} {_LAST_NAMES[(i // len(_FIRST_NAMES)) % len(_LAST_NAMES)]}"


def _on_or_after(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def build_seed(now: datetime, restaurant: RestaurantConfig) -> list[Booking]:
    """Coming Friday: every window table taken at 19:00 (window is full 18:00-20:30).
    Coming Saturday: all general and window tables at 19:30, one private booth at 20:00.
    CP-1001 is a booking you can use to try the cancel flow.
    """
    friday = _on_or_after(now.date(), _FRIDAY)
    saturday = _on_or_after(now.date(), _SATURDAY)
    out: list[Booking] = []

    def add(table: Table, day: date, at: time) -> None:
        n = len(out) + 1
        out.append(
            Booking(
                ref=f"CP-{_FIRST_REF + n - 1}",
                table_id=table.id,
                date=day,
                time=at,
                party=table.seats,
                seating=table.category,
                name=_fake_name(n),
                title="none",
                phone=f"5550100{n:03d}",
                created_at=now,
            )
        )

    for table in restaurant.tables_in(Seating.WINDOW):
        add(table, friday, time(19, 0))
    for category in (Seating.GENERAL, Seating.WINDOW):
        for table in restaurant.tables_in(category):
            add(table, saturday, time(19, 30))
    add(restaurant.tables_in(Seating.PRIVATE)[0], saturday, time(20, 0))
    return out


def seeded_repository(
    restaurant: RestaurantConfig, clock: Clock, limits: VerifyLimits | None = None
) -> InMemoryBookingRepository:
    return InMemoryBookingRepository(
        restaurant, clock, build_seed(clock.now(), restaurant), limits=limits
    )
