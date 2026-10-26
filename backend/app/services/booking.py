"""Booking repository contract, shared logic, and the in-memory implementation (tests only)."""

import hashlib
import random
import re
import threading
from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Protocol

from app.services.clock import Clock
from app.services.restaurant import RestaurantConfig, Seating, Table

_MINUTES_PER_HOUR = 60
_REF_DIGITS = 10_000
_TITLE_WORDS = frozenset({"mr", "mister", "mrs", "missus", "ms", "miss", "mx"})


class BookingStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BookingRequest:
    date: date
    time: time
    party: int
    seating: Seating
    name: str
    title: str
    phone: str


@dataclass(frozen=True)
class Booking:
    ref: str
    table_id: str
    date: date
    time: time
    party: int
    seating: Seating
    name: str
    title: str
    phone: str
    created_at: datetime
    status: BookingStatus = BookingStatus.ACTIVE


@dataclass(frozen=True)
class Alternative:
    """A free slot we can offer when the requested one is taken."""

    date: date
    time: time
    seating: Seating


@dataclass(frozen=True)
class VerifyLimits:
    """How many failed cancel verifications are tolerated inside the window."""

    per_caller: int = 5
    global_: int = 30
    window_minutes: int = 15


class SlotTakenError(Exception):
    """The table was free when checked but is gone now."""


class BookingNotFoundError(Exception):
    """No booking matches. Carries no reference or name: it may end up in logs."""


class AlreadyCancelledError(Exception):
    pass


class RepositoryUnavailableError(Exception):
    """The storage cannot be used right now. Carries no paths, SQL or values."""


class TooManyAttemptsError(Exception):
    """Too many failed verifications for this caller (or overall) in the window."""


# -- helpers shared by every repository ---------------------------------------------------


def normalize_name(name: str) -> str:
    """Lower-case words only, titles dropped: "Mr. Sample" -> "sample"."""
    words = re.findall(r"[a-z']+", name.casefold())
    return " ".join(w for w in words if w not in _TITLE_WORDS)


def name_matches(stored_norm: str, given: str) -> bool:
    """The full name, or the surname alone, matches; a first name alone does not."""
    given_norm = normalize_name(given)
    if not given_norm or not stored_norm:
        return False
    return given_norm in (stored_norm, stored_norm.split()[-1])


def booking_key(request: BookingRequest) -> str:
    """Identifies "the same booking asked again": used to make confirmations idempotent."""
    parts = [
        request.date.isoformat(),
        request.time.strftime("%H:%M"),
        str(request.party),
        request.seating.value,
        normalize_name(request.name),
        re.sub(r"\D", "", request.phone),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def request_of(b: Booking) -> BookingRequest:
    return BookingRequest(b.date, b.time, b.party, b.seating, b.name, b.title, b.phone)


def _minutes(t: time) -> int:
    return t.hour * _MINUTES_PER_HOUR + t.minute


def _as_time(minutes: int) -> time:
    return time(minutes // _MINUTES_PER_HOUR, minutes % _MINUTES_PER_HOUR)


class BookingRepository(Protocol):
    def ping(self) -> bool: ...

    def slots(self, d: date) -> list[time]: ...

    def check_availability(
        self, d: date, t: time, party: int, seating: Seating
    ) -> Table | None: ...

    def find_alternatives(
        self, d: date, t: time, party: int, seating: Seating, limit: int, window_minutes: int
    ) -> list[Alternative]: ...

    def availability_summary(
        self, d: date, seating: Seating | None = None, party: int | None = None
    ) -> list[time]: ...

    def next_available_day(self, after: date, party: int, seating: Seating) -> date | None: ...

    def book(self, request: BookingRequest) -> Booking:
        """Idempotent: the same booking asked twice returns the first one."""
        ...

    def find_for_cancel(self, ref: str, name: str, caller_key: str) -> Booking | None:
        """The booking only when reference AND name match, otherwise None.

        Raises TooManyAttemptsError when this caller (or everyone) failed too often recently.
        """
        ...

    def cancel(self, ref: str, verified_name: str) -> Booking: ...

    def bookings(self) -> list[Booking]: ...


class AvailabilityQueries:
    """Availability logic shared by every repository; subclasses say which tables are busy."""

    _restaurant: RestaurantConfig
    _lock: AbstractContextManager[Any]

    def _busy(self, table_id: str, d: date, t: time) -> bool:
        raise NotImplementedError

    def slots(self, d: date) -> list[time]:
        """Bookable start times on a day; empty when closed."""
        hours = self._restaurant.hours_for(d.weekday())
        if hours is None:
            return []
        last = _minutes(min(self._restaurant.last_seating, hours[1]))
        step = self._restaurant.slot_minutes
        return [_as_time(m) for m in range(_minutes(hours[0]), last + 1, step)]

    def _free_table(self, d: date, t: time, party: int | None, seating: Seating) -> Table | None:
        """Smallest free table of the category that fits the party (any size if None)."""
        fitting = sorted(
            (
                tb
                for tb in self._restaurant.tables_in(seating)
                if party is None or tb.min_party <= party <= tb.seats
            ),
            key=lambda tb: (tb.seats, tb.id),
        )
        return next((tb for tb in fitting if not self._busy(tb.id, d, t)), None)

    def check_availability(
        self, d: date, t: time, party: int, seating: Seating
    ) -> Table | None:
        with self._lock:
            if t not in self.slots(d):
                return None
            return self._free_table(d, t, party, seating)

    def find_alternatives(
        self, d: date, t: time, party: int, seating: Seating, limit: int, window_minutes: int
    ) -> list[Alternative]:
        """Nearest free times in the same category, then the same time in other categories."""
        with self._lock:
            slots = self.slots(d)
            base = _minutes(t)
            near = sorted(
                (
                    s
                    for s in slots
                    if s != t
                    and abs(_minutes(s) - base) <= window_minutes
                    and self._free_table(d, s, party, seating)
                ),
                key=lambda s: (abs(_minutes(s) - base), -_minutes(s)),
            )
            found = [Alternative(d, s, seating) for s in near[:limit]]
            if t in slots:
                others = [
                    Alternative(d, t, other)
                    for other in Seating
                    if other != seating and self._free_table(d, t, party, other)
                ]
                found.extend(others[:limit])
            return found

    def availability_summary(
        self, d: date, seating: Seating | None = None, party: int | None = None
    ) -> list[time]:
        categories = [seating] if seating else list(Seating)
        with self._lock:
            return [
                s
                for s in self.slots(d)
                if any(self._free_table(d, s, party, c) for c in categories)
            ]

    def next_available_day(self, after: date, party: int, seating: Seating) -> date | None:
        for offset in range(1, self._restaurant.booking_window_days + 1):
            day = after + timedelta(days=offset)
            if self.availability_summary(day, seating, party):
                return day
        return None


class InMemoryBookingRepository(AvailabilityQueries):
    """For tests and quick local runs. Not storage you should rely on."""

    def __init__(
        self,
        restaurant: RestaurantConfig,
        clock: Clock,
        bookings: Iterable[Booking] = (),
        rng_seed: int = 7,
        limits: VerifyLimits | None = None,
    ) -> None:
        self._restaurant = restaurant
        self._clock = clock
        self._limits = limits or VerifyLimits()
        self._lock = threading.RLock()
        self._rng = random.Random(rng_seed)
        self._bookings: dict[str, Booking] = {b.ref: b for b in bookings}
        self._failures: list[tuple[str, datetime]] = []

    def ping(self) -> bool:
        return True

    def _busy(self, table_id: str, d: date, t: time) -> bool:
        sitting = self._restaurant.sitting_minutes
        start = _minutes(t)
        return any(
            b.status is BookingStatus.ACTIVE
            and b.table_id == table_id
            and b.date == d
            and _minutes(b.time) < start + sitting
            and start < _minutes(b.time) + sitting
            for b in self._bookings.values()
        )

    def _new_ref(self) -> str:
        while True:
            ref = f"CP-{self._rng.randrange(_REF_DIGITS):04d}"
            if ref not in self._bookings:
                return ref

    def book(self, request: BookingRequest) -> Booking:
        with self._lock:
            key = booking_key(request)
            for existing in self._bookings.values():
                if (
                    existing.status is BookingStatus.ACTIVE
                    and booking_key(request_of(existing)) == key
                ):
                    return existing
            table = self.check_availability(
                request.date, request.time, request.party, request.seating
            )
            if table is None:
                raise SlotTakenError
            booking = Booking(
                ref=self._new_ref(),
                table_id=table.id,
                date=request.date,
                time=request.time,
                party=request.party,
                seating=request.seating,
                name=request.name,
                title=request.title,
                phone=request.phone,
                created_at=self._clock.now(),
            )
            self._bookings[booking.ref] = booking
            return booking

    def find_for_cancel(self, ref: str, name: str, caller_key: str) -> Booking | None:
        with self._lock:
            now = self._clock.now()
            cutoff = now - timedelta(minutes=self._limits.window_minutes)
            self._failures = [(k, t) for k, t in self._failures if t > cutoff]
            by_caller = sum(1 for k, _ in self._failures if k == caller_key)
            if by_caller >= self._limits.per_caller or len(self._failures) >= self._limits.global_:
                raise TooManyAttemptsError
            booking = self._bookings.get(ref.strip().upper())
            if booking is not None and name_matches(normalize_name(booking.name), name):
                return booking
            self._failures.append((caller_key, now))
            return None

    def cancel(self, ref: str, verified_name: str) -> Booking:
        with self._lock:
            booking = self._bookings.get(ref.strip().upper())
            if booking is None or not name_matches(normalize_name(booking.name), verified_name):
                raise BookingNotFoundError
            if booking.status is BookingStatus.CANCELLED:
                raise AlreadyCancelledError
            cancelled = replace(booking, status=BookingStatus.CANCELLED)
            self._bookings[cancelled.ref] = cancelled
            return cancelled

    def bookings(self) -> list[Booking]:
        with self._lock:
            return sorted(self._bookings.values(), key=lambda b: (b.date, b.time, b.ref))
