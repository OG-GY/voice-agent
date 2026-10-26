"""Apply migrations/NNN_*.sql in order, tracked with PRAGMA user_version.

    uv run python -m app.db.migrate
"""

import sqlite3
from pathlib import Path

from app.config import load_settings
from app.db.connection import Database

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def migrate(db: Database, directory: Path = MIGRATIONS_DIR) -> int:
    """Apply every migration newer than the database; return the resulting version."""
    conn = db.get()
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        if version <= current:
            continue
        script = path.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        current = version
    return current


def main() -> None:
    settings = load_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path, settings.db_busy_timeout_ms)
    print(f"database is at version {migrate(db)}")
    db.close_all()


if __name__ == "__main__":
    main()
