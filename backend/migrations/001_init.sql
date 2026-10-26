-- SQLite schema for The Copper Pot bookings. Applied by `python -m app.db.migrate`.
-- Times are local restaurant time, stored as text 'YYYY-MM-DD HH:MM' (no timezone, by design).

CREATE TABLE bookings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ref             TEXT    NOT NULL UNIQUE,
  table_id        TEXT    NOT NULL,
  starts_at       TEXT    NOT NULL,
  party           INTEGER NOT NULL CHECK (party BETWEEN 1 AND 8),
  seating         TEXT    NOT NULL CHECK (seating IN ('general','window','private')),
  name            TEXT    NOT NULL,
  name_norm       TEXT    NOT NULL,
  title           TEXT    NOT NULL,
  phone           TEXT    NOT NULL,
  status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','cancelled')),
  idempotency_key TEXT    NOT NULL,
  is_demo         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT    NOT NULL,
  cancelled_at    TEXT
);

-- Asking for the same booking again returns the existing one instead of taking a second table.
CREATE UNIQUE INDEX bookings_one_active_per_key ON bookings (idempotency_key) WHERE status = 'active';
CREATE INDEX bookings_day ON bookings (starts_at);

-- One row per table per 30-minute slot a sitting occupies. The primary key is what forbids
-- two bookings overlapping on one table (SQLite has no exclusion constraints).
CREATE TABLE table_slots (
  table_id   TEXT    NOT NULL,
  slot_start TEXT    NOT NULL,
  booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  PRIMARY KEY (table_id, slot_start)
) WITHOUT ROWID;

CREATE TABLE verification_failures (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  caller_key TEXT NOT NULL,
  at         TEXT NOT NULL
);
CREATE INDEX verification_failures_lookup ON verification_failures (caller_key, at);
