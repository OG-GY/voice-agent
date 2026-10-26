"""SQLite specifics: persistence, concurrency, locking, seed data. (Shared rules: contract tests.)"""

import sqlite3
import threading
from datetime import date, datetime, time
from pathlib import Path

import pytest

from app.db.connection import Database
from app.db.migrate import migrate
from app.services.booking import (
    AlreadyCancelledError,
    BookingRequest,
    BookingStatus,
    RepositoryUnavailableError,
    SlotTakenError,
    TooManyAttemptsError,
    VerifyLimits,
)
from app.services.clock import FixedClock
from app.services.restaurant import DEFAULT_RESTAURANT, Seating
from app.services.seed import build_seed
from app.services.sqlite_booking import SqliteBookingRepository

NOW = datetime(2026, 10, 28, 15, 0)
FRIDAY = date(2026, 10, 30)


def new_repo(path: Path, busy_ms: int = 3000, limits: VerifyLimits | None = None):  # type: ignore[no-untyped-def]
    db = Database(path, busy_ms)
    migrate(db)
    return SqliteBookingRepository(DEFAULT_RESTAURANT, FixedClock(NOW), db, limits), db


def request(n: int = 0, at: time = time(12, 0), seating: Seating = Seating.WINDOW, party: int = 2) -> BookingRequest:
    return BookingRequest(FRIDAY, at, party, seating, "Alex Sample", "none", f"55501000{n:02d}")


def test_migrating_twice_is_harmless(tmp_path: Path) -> None:
    db = Database(tmp_path / "m.db")
    assert migrate(db) == migrate(db) == 1


def test_bookings_and_cancellations_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    repo, db = new_repo(path)
    booking = repo.book(request())
    db.close_all()

    repo, db = new_repo(path)  # a fresh process opening the same file
    assert [b.ref for b in repo.bookings()] == [booking.ref]
    repo.cancel(booking.ref, "Alex Sample")
    db.close_all()

    repo, _ = new_repo(path)
    assert repo.bookings()[0].status is BookingStatus.CANCELLED
    assert repo.check_availability(FRIDAY, time(12, 0), 2, Seating.WINDOW) is not None  # slots freed


def test_failed_verifications_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "limits.db"
    limits = VerifyLimits(per_caller=1)
    repo, db = new_repo(path, limits=limits)
    assert repo.find_for_cancel("CP-0000", "x", "caller") is None
    db.close_all()
    repo, _ = new_repo(path, limits=limits)
    with pytest.raises(TooManyAttemptsError):
        repo.find_for_cancel("CP-0000", "x", "caller")


def test_twenty_threads_race_for_the_only_private_room(tmp_path: Path) -> None:
    repo, _ = new_repo(tmp_path / "race.db")
    outcomes: list[str] = []
    barrier = threading.Barrier(20)

    def worker(n: int) -> None:
        barrier.wait()
        try:
            repo.book(request(n, time(19, 0), Seating.PRIVATE, party=8))
            outcomes.append("won")
        except SlotTakenError:
            outcomes.append("lost")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("won") == 1
    assert outcomes.count("lost") == 19
    assert len(repo.bookings()) == 1


def test_racing_cancellations_cancel_exactly_once(tmp_path: Path) -> None:
    repo, _ = new_repo(tmp_path / "cancel.db")
    booking = repo.book(request())
    outcomes: list[str] = []
    barrier = threading.Barrier(10)

    def worker() -> None:
        barrier.wait()
        try:
            repo.cancel(booking.ref, "Alex Sample")
            outcomes.append("cancelled")
        except AlreadyCancelledError:
            outcomes.append("already")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("cancelled") == 1
    assert outcomes.count("already") == 9


def test_a_locked_database_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    repo, db = new_repo(tmp_path / "locked.db", busy_ms=100)
    blocker = sqlite3.connect(db.path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")  # another process holds the write lock
    try:
        with pytest.raises(RepositoryUnavailableError) as error:
            repo.book(request())
        assert str(error.value) == ""  # no path, SQL or values in the message
        assert db.path not in repr(error.value)
        assert repo.bookings() == []  # nothing was half-written
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    repo.book(request())  # works again once the lock is gone


def test_an_unusable_file_is_unavailable(tmp_path: Path) -> None:
    db = Database(tmp_path / "no-such-folder" / "x.db")
    repo = SqliteBookingRepository(DEFAULT_RESTAURANT, FixedClock(NOW), db)
    with pytest.raises(RepositoryUnavailableError):
        repo.bookings()
    assert repo.ping() is False


def test_ping_reports_a_healthy_database(tmp_path: Path) -> None:
    repo, _ = new_repo(tmp_path / "ok.db")
    assert repo.ping() is True


def test_reseeding_replaces_only_the_demo_rows(tmp_path: Path) -> None:
    repo, _ = new_repo(tmp_path / "seed.db")
    real = repo.book(request())
    first = repo.replace_demo_bookings(build_seed(NOW, DEFAULT_RESTAURANT))
    second = repo.replace_demo_bookings(build_seed(NOW, DEFAULT_RESTAURANT))
    assert first == second > 0
    refs = [b.ref for b in repo.bookings()]
    assert real.ref in refs
    assert len(refs) == first + 1
    assert "CP-1001" in refs
