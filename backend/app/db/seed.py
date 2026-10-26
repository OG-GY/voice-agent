"""Load the fake demo bookings into the database (development only).

    uv run python -m app.db.seed
"""

from pathlib import Path

from app.config import ConfigError, load_settings
from app.db.connection import Database
from app.db.migrate import migrate
from app.services.clock import FixedClock, SystemClock
from app.services.restaurant import DEFAULT_RESTAURANT
from app.services.seed import build_seed
from app.services.sqlite_booking import SqliteBookingRepository


def main() -> None:
    settings = load_settings()
    if settings.app_env == "production":
        raise ConfigError("refusing to load demo data when APP_ENV=production")
    clock = FixedClock(settings.fixed_now()) if settings.brain_fixed_now else SystemClock()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path, settings.db_busy_timeout_ms)
    migrate(db)
    repo = SqliteBookingRepository(DEFAULT_RESTAURANT, clock, db)
    count = repo.replace_demo_bookings(build_seed(clock.now(), DEFAULT_RESTAURANT))
    print(f"loaded {count} fake demo bookings (real bookings untouched)")
    db.close_all()


if __name__ == "__main__":
    main()
