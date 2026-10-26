"""SQLite booking repository (stdlib sqlite3).

Writes run in `BEGIN IMMEDIATE` transactions, so there is one writer at a time. Double booking
is also forbidden by the database itself: `table_slots` has one row per table per 30-minute
slot, with (table_id, slot_start) as the primary key.
"""

import random
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, time, timedelta

from app.db.connection import Database
from app.services.booking import (
    AlreadyCancelledError,
    AvailabilityQueries,
    Booking,
    BookingNotFoundError,
    BookingRequest,
    BookingStatus,
    RepositoryUnavailableError,
    SlotTakenError,
    TooManyAttemptsError,
    VerifyLimits,
    booking_key,
    name_matches,
    normalize_name,
    request_of,
)
from app.services.clock import Clock
from app.services.restaurant import RestaurantConfig, Seating, Table

_REF_DIGITS = 10_000
_REF_ATTEMPTS = 20
_STAMP = "%Y-%m-%d %H:%M"


def _to_booking(row: sqlite3.Row) -> Booking:
    start = datetime.strptime(row["starts_at"], _STAMP)
    return Booking(
        ref=row["ref"],
        table_id=row["table_id"],
        date=start.date(),
        time=start.time(),
        party=row["party"],
        seating=Seating(row["seating"]),
        name=row["name"],
        title=row["title"],
        phone=row["phone"],
        created_at=datetime.fromisoformat(row["created_at"]),
        status=BookingStatus(row["status"]),
    )


class SqliteBookingRepository(AvailabilityQueries):
    def __init__(
        self,
        restaurant: RestaurantConfig,
        clock: Clock,
        db: Database,
        limits: VerifyLimits | None = None,
        rng_seed: int | None = None,
    ) -> None:
        self._restaurant = restaurant
        self._clock = clock
        self._db = db
        self._limits = limits or VerifyLimits()
        self._lock = nullcontext()  # reads need no lock: SQLite WAL allows concurrent readers
        self._rng = random.Random(rng_seed)

    # -- connections --------------------------------------------------------------------

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._db.get()
        except sqlite3.Error:
            raise RepositoryUnavailableError from None

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One BEGIN IMMEDIATE transaction: committed on success, rolled back on any error."""
        try:
            conn = self._db.get()
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise RepositoryUnavailableError from None
        try:
            yield conn
            conn.execute("COMMIT")
        except sqlite3.Error:
            self._rollback(conn)
            raise RepositoryUnavailableError from None
        except BaseException:
            self._rollback(conn)
            raise

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def ping(self) -> bool:
        try:
            with self._read() as conn:
                conn.execute("SELECT 1").fetchone()
        except RepositoryUnavailableError:
            return False
        return True

    def close(self) -> None:
        self._db.close_all()

    # -- availability -------------------------------------------------------------------

    def _slot_starts(self, d: date, t: time) -> list[str]:
        r = self._restaurant
        start = datetime.combine(d, t)
        steps = r.sitting_minutes // r.slot_minutes
        return [(start + timedelta(minutes=i * r.slot_minutes)).strftime(_STAMP) for i in range(steps)]

    def _busy(self, table_id: str, d: date, t: time) -> bool:
        starts = self._slot_starts(d, t)
        marks = ",".join("?" * len(starts))
        with self._read() as conn:
            row = conn.execute(
                f"SELECT 1 FROM table_slots WHERE table_id = ? AND slot_start IN ({marks}) LIMIT 1",
                (table_id, *starts),
            ).fetchone()
        return row is not None

    # -- bookings -----------------------------------------------------------------------

    def _candidates(self, party: int, seating: Seating) -> list[Table]:
        return sorted(
            (t for t in self._restaurant.tables_in(seating) if t.min_party <= party <= t.seats),
            key=lambda t: (t.seats, t.id),
        )

    def _new_ref(self) -> str:
        return f"CP-{self._rng.randrange(_REF_DIGITS):04d}"

    def _insert(
        self,
        conn: sqlite3.Connection,
        b: Booking | BookingRequest,
        table_id: str,
        ref: str | None,
        key: str,
        starts: list[str],
        is_demo: bool = False,
    ) -> int:
        """Insert a booking and its slot rows. Raises sqlite3.IntegrityError on a clash."""
        attempts = 1 if ref else _REF_ATTEMPTS
        stamp = self._clock.now().isoformat(timespec="seconds")
        for _ in range(attempts):
            chosen = ref or self._new_ref()
            try:
                cur = conn.execute(
                    "INSERT INTO bookings (ref, table_id, starts_at, party, seating, name, name_norm,"
                    " title, phone, idempotency_key, is_demo, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        chosen, table_id, starts[0], b.party, b.seating.value, b.name,
                        normalize_name(b.name), b.title, b.phone, key, int(is_demo), stamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if ref is None and "bookings.ref" in str(exc):
                    continue  # reference collision: try another
                raise
            row_id = cur.lastrowid
            assert row_id is not None
            conn.executemany(
                "INSERT INTO table_slots (table_id, slot_start, booking_id) VALUES (?,?,?)",
                [(table_id, s, row_id) for s in starts],
            )
            return row_id
        raise RuntimeError("could not allocate a booking reference")

    def _try_table(
        self, conn: sqlite3.Connection, request: BookingRequest, table: Table, key: str, starts: list[str]
    ) -> Booking | None:
        conn.execute("SAVEPOINT pick")
        try:
            row_id = self._insert(conn, request, table.id, None, key, starts)
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK TO pick")
            conn.execute("RELEASE pick")
            return None  # the table's slots were taken: try the next table
        conn.execute("RELEASE pick")
        return _to_booking(conn.execute("SELECT * FROM bookings WHERE id = ?", (row_id,)).fetchone())

    def book(self, request: BookingRequest) -> Booking:
        key = booking_key(request)
        with self._write() as conn:
            existing = conn.execute(
                "SELECT * FROM bookings WHERE idempotency_key = ? AND status = 'active'", (key,)
            ).fetchone()
            if existing is not None:
                return _to_booking(existing)
            if request.time not in self.slots(request.date):
                raise SlotTakenError
            starts = self._slot_starts(request.date, request.time)
            for table in self._candidates(request.party, request.seating):
                booking = self._try_table(conn, request, table, key, starts)
                if booking is not None:
                    return booking
            raise SlotTakenError

    def find_for_cancel(self, ref: str, name: str, caller_key: str) -> Booking | None:
        now = self._clock.now()
        cutoff = (now - timedelta(minutes=self._limits.window_minutes)).isoformat(timespec="seconds")
        with self._write() as conn:
            conn.execute("DELETE FROM verification_failures WHERE at <= ?", (cutoff,))
            by_caller = conn.execute(
                "SELECT COUNT(*) FROM verification_failures WHERE caller_key = ?", (caller_key,)
            ).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM verification_failures").fetchone()[0]
            if by_caller >= self._limits.per_caller or total >= self._limits.global_:
                raise TooManyAttemptsError
            row = conn.execute(
                "SELECT * FROM bookings WHERE ref = ?", (ref.strip().upper(),)
            ).fetchone()
            if row is not None and name_matches(row["name_norm"], name):
                return _to_booking(row)
            conn.execute(
                "INSERT INTO verification_failures (caller_key, at) VALUES (?, ?)",
                (caller_key, now.isoformat(timespec="seconds")),
            )
            return None

    def cancel(self, ref: str, verified_name: str) -> Booking:
        stamp = self._clock.now().isoformat(timespec="seconds")
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM bookings WHERE ref = ?", (ref.strip().upper(),)
            ).fetchone()
            if row is None or not name_matches(row["name_norm"], verified_name):
                raise BookingNotFoundError
            done = conn.execute(
                "UPDATE bookings SET status = 'cancelled', cancelled_at = ?"
                " WHERE id = ? AND status = 'active'",
                (stamp, row["id"]),
            )
            if done.rowcount == 0:
                raise AlreadyCancelledError
            conn.execute("DELETE FROM table_slots WHERE booking_id = ?", (row["id"],))
            return _to_booking(
                conn.execute("SELECT * FROM bookings WHERE id = ?", (row["id"],)).fetchone()
            )

    def bookings(self) -> list[Booking]:
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM bookings ORDER BY starts_at, ref").fetchall()
        return [_to_booking(r) for r in rows]

    # -- demo data ----------------------------------------------------------------------

    def replace_demo_bookings(self, demo: Iterable[Booking]) -> int:
        """Replace only the fake demo rows (is_demo = 1); real bookings are never touched."""
        count = 0
        with self._write() as conn:
            conn.execute("DELETE FROM bookings WHERE is_demo = 1")
            for b in demo:
                starts = self._slot_starts(b.date, b.time)
                self._insert(
                    conn, b, b.table_id, b.ref, booking_key(request_of(b)), starts, is_demo=True
                )
                count += 1
        return count
