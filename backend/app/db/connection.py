"""SQLite connections: one per thread, never shared between threads."""

import contextlib
import sqlite3
import threading
from pathlib import Path

_MS_PER_SECOND = 1000


class Database:
    def __init__(self, path: str | Path, busy_timeout_ms: int = 3000) -> None:
        self.path = str(path)
        self._busy_ms = busy_timeout_ms
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def get(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.path,
                timeout=self._busy_ms / _MS_PER_SECOND,
                isolation_level=None,  # autocommit; writes use an explicit BEGIN IMMEDIATE
                check_same_thread=False,  # so close_all() can run from another thread
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={int(self._busy_ms)}")
            self._local.conn = conn
            with self._lock:
                self._all.append(conn)
        return conn

    def close_all(self) -> None:
        with self._lock:
            for conn in self._all:
                with contextlib.suppress(sqlite3.Error):
                    conn.close()
            self._all.clear()
            self._local = threading.local()
