"""Behavior every BookingRepository must have. Add new implementations to `make_repo`."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from app.db.connection import Database
from app.db.migrate import migrate
from app.services.booking import (
    AlreadyCancelledError,
    BookingNotFoundError,
    BookingRepository,
    BookingRequest,
    BookingStatus,
    InMemoryBookingRepository,
    SlotTakenError,
    TooManyAttemptsError,
    VerifyLimits,
)
from app.services.clock import FixedClock
from app.services.restaurant import DEFAULT_RESTAURANT, Seating
from app.services.sqlite_booking import SqliteBookingRepository

FRIDAY = date(2026, 10, 30)
FIRST_NAMES = ("Alex", "Sam", "Jordan", "Casey", "Riley", "Taylor")

RepoFactory = Callable[..., BookingRepository]


class MovableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 28, 15, 0)

    def now(self) -> datetime:
        return self.current


@pytest.fixture(params=["memory", "sqlite"])
def make_repo(request: pytest.FixtureRequest, tmp_path: Path) -> RepoFactory:
    def factory(limits: VerifyLimits | None = None, clock: MovableClock | None = None) -> BookingRepository:
        used_clock = clock or FixedClock(datetime(2026, 10, 28, 15, 0))
        if request.param == "memory":
            return InMemoryBookingRepository(DEFAULT_RESTAURANT, used_clock, limits=limits)
        db = Database(tmp_path / "contract.db")
        migrate(db)
        return SqliteBookingRepository(DEFAULT_RESTAURANT, used_clock, db, limits)

    return factory


def req(n: int = 0, at: time = time(19, 0), seating: Seating = Seating.WINDOW) -> BookingRequest:
    """A different (fake) guest per n, so two requests are never the 'same booking'."""
    return BookingRequest(
        date=FRIDAY, time=at, party=2, seating=seating,
        name=f"{FIRST_NAMES[n]} Sample", title="none", phone=f"55501000{n:02d}",
    )


def test_a_window_slot_holds_five_parties_of_two_then_conflicts(make_repo: RepoFactory) -> None:
    repo = make_repo()
    for n in range(5):
        repo.book(req(n))
    with pytest.raises(SlotTakenError):
        repo.book(req(5))


def test_overlapping_sittings_are_blocked_but_the_next_slot_is_free(make_repo: RepoFactory) -> None:
    repo = make_repo()
    for n in range(5):
        repo.book(req(n))
    with pytest.raises(SlotTakenError):
        repo.book(req(5, at=time(20, 0)))  # 19:00 sittings last until 20:30
    repo.book(req(5, at=time(20, 30)))


def test_other_seating_types_are_unaffected(make_repo: RepoFactory) -> None:
    repo = make_repo()
    for n in range(5):
        repo.book(req(n))
    repo.book(req(5, seating=Seating.GENERAL))


def test_cancelling_frees_the_table(make_repo: RepoFactory) -> None:
    repo = make_repo()
    first = repo.book(req(0))
    for n in range(1, 5):
        repo.book(req(n))
    with pytest.raises(SlotTakenError):
        repo.book(req(5))
    repo.cancel(first.ref, "Alex Sample")
    repo.book(req(5))


def test_asking_twice_returns_the_same_booking(make_repo: RepoFactory) -> None:
    repo = make_repo()
    first, again = repo.book(req(0)), repo.book(req(0))
    assert first.ref == again.ref
    assert len(repo.bookings()) == 1


def test_a_cancelled_booking_can_be_booked_again(make_repo: RepoFactory) -> None:
    repo = make_repo()
    first = repo.book(req(0))
    repo.cancel(first.ref, "Alex Sample")
    assert repo.book(req(0)).ref != first.ref


def test_cancel_needs_the_right_name(make_repo: RepoFactory) -> None:
    repo = make_repo()
    booking = repo.book(req(0))
    with pytest.raises(BookingNotFoundError):
        repo.cancel(booking.ref, "Nobody Special")
    assert repo.bookings()[0].status is BookingStatus.ACTIVE
    repo.cancel(booking.ref, "Alex Sample")
    with pytest.raises(AlreadyCancelledError):
        repo.cancel(booking.ref, "Alex Sample")


@pytest.mark.parametrize("given", ["Alex Sample", "alex sample", "Sample", "Mr Sample"])
def test_find_for_cancel_accepts_full_name_or_surname(make_repo: RepoFactory, given: str) -> None:
    repo = make_repo()
    booking = repo.book(req(0))
    assert repo.find_for_cancel(booking.ref, given, "caller") is not None


@pytest.mark.parametrize("given", ["Alex", "Sam Sample", "Nobody Special", ""])
def test_find_for_cancel_rejects_anything_else(make_repo: RepoFactory, given: str) -> None:
    repo = make_repo()
    booking = repo.book(req(0))
    assert repo.find_for_cancel(booking.ref, given, "caller") is None


def test_unknown_reference_looks_like_a_wrong_name(make_repo: RepoFactory) -> None:
    repo = make_repo()
    assert repo.find_for_cancel("CP-0000", "Alex Sample", "caller") is None


def test_too_many_failures_lock_the_caller_out_but_not_others(make_repo: RepoFactory) -> None:
    repo = make_repo(VerifyLimits(per_caller=2))
    booking = repo.book(req(0))
    assert repo.find_for_cancel(booking.ref, "Wrong Person", "caller") is None
    assert repo.find_for_cancel(booking.ref, "Wrong Person", "caller") is None
    with pytest.raises(TooManyAttemptsError):
        repo.find_for_cancel(booking.ref, "Alex Sample", "caller")  # even the right answer
    assert repo.find_for_cancel(booking.ref, "Alex Sample", "someone else") is not None


def test_the_global_limit_applies_across_callers(make_repo: RepoFactory) -> None:
    repo = make_repo(VerifyLimits(per_caller=10, global_=3))
    for n in range(3):
        assert repo.find_for_cancel("CP-0000", "x", f"caller-{n}") is None
    with pytest.raises(TooManyAttemptsError):
        repo.find_for_cancel("CP-0000", "x", "caller-new")


def test_failures_expire_after_the_window(make_repo: RepoFactory) -> None:
    clock = MovableClock()
    repo = make_repo(VerifyLimits(per_caller=1, window_minutes=15), clock)
    assert repo.find_for_cancel("CP-0000", "x", "caller") is None
    with pytest.raises(TooManyAttemptsError):
        repo.find_for_cancel("CP-0000", "x", "caller")
    clock.current += timedelta(minutes=16)
    assert repo.find_for_cancel("CP-0000", "x", "caller") is None
