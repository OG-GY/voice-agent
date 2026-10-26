"""Everything the running app shares: brain, repository, speech, limiters, active calls."""

import asyncio
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from app.api.calls import CallRegistry
from app.api.limits import IpRegistry
from app.brain import Brain
from app.config import Settings
from app.db.connection import Database
from app.db.migrate import migrate
from app.services.booking import BookingRepository, InMemoryBookingRepository, VerifyLimits
from app.services.clock import Clock, FixedClock, SystemClock
from app.services.restaurant import DEFAULT_RESTAURANT, RestaurantConfig
from app.services.seed import build_seed, seeded_repository
from app.services.sqlite_booking import SqliteBookingRepository
from app.speech.base import SpeechStatus, SpeechToText
from app.speech.service import SpeechService

_DB_CHECK_TIMEOUT_S = 1.0
_DB_CACHE_S = 2.0
_KEY_CHARS = 32


@dataclass
class AppContainer:
    settings: Settings
    restaurant: RestaurantConfig
    clock: Clock
    repository: BookingRepository
    brain: Brain
    speech: SpeechService
    ips: IpRegistry
    calls: CallRegistry
    brain_executor: ThreadPoolExecutor
    secret: bytes
    shutting_down: bool = False
    _loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    _db_cache: tuple[float, bool] | None = field(default=None, repr=False)

    def caller_key(self, ip: str) -> str:
        """Opaque id for rate limiting; the raw IP is never stored."""
        return hmac.new(self.secret, ip.encode(), hashlib.sha256).hexdigest()[:_KEY_CHARS]

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self.speech.start(wait=self.settings.app_env == "test")

    def begin_shutdown(self) -> None:
        """Safe to call from a signal handler: stop accepting calls and warn the active ones."""
        if self.shutting_down:
            return
        self.shutting_down = True
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.calls.notify_closing()))

    async def aclose(self) -> None:
        self.shutting_down = True
        await self.calls.drain(self.settings.shutdown_grace_seconds)
        await self.speech.stop()
        self.brain_executor.shutdown(wait=False, cancel_futures=True)
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()

    async def _database_ok(self) -> bool:
        now = time.monotonic()
        if self._db_cache is not None and now - self._db_cache[0] < _DB_CACHE_S:
            return self._db_cache[1]
        try:
            ok = bool(
                await asyncio.wait_for(asyncio.to_thread(self.repository.ping), _DB_CHECK_TIMEOUT_S)
            )
        except Exception:
            ok = False
        self._db_cache = (now, ok)
        return ok

    async def readiness(self) -> tuple[dict[str, str | bool], int]:
        """Component states only: no paths, versions, hostnames or error text."""
        database = await self._database_ok()
        speech = self.speech.status
        if self.shutting_down or not database:
            status, code = "unavailable", 503
        elif speech is SpeechStatus.READY:
            status, code = "ready", 200
        else:
            status, code = "degraded", 200  # text-only calls still work
        body: dict[str, str | bool] = {
            "status": status,
            "database": "ok" if database else "unavailable",
            "speech": speech.value,
            "shutting_down": self.shutting_down,
        }
        return body, code


def _make_repository(settings: Settings, restaurant: RestaurantConfig, clock: Clock) -> BookingRepository:
    limits = VerifyLimits(
        settings.verify_max_per_caller, settings.verify_max_global, settings.verify_window_minutes
    )
    if settings.repository_backend == "memory":
        if settings.seed_demo_data:
            return seeded_repository(restaurant, clock, limits)
        return InMemoryBookingRepository(restaurant, clock, limits=limits)
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path, settings.db_busy_timeout_ms)
    migrate(db)
    repo = SqliteBookingRepository(restaurant, clock, db, limits)
    if settings.seed_demo_data:
        repo.replace_demo_bookings(build_seed(clock.now(), restaurant))
    return repo


def build_container(
    settings: Settings,
    *,
    repository: BookingRepository | None = None,
    stt_factory: Callable[[], SpeechToText] | None = None,
    clock: Clock | None = None,
) -> AppContainer:
    restaurant = DEFAULT_RESTAURANT
    if clock is None:
        clock = FixedClock(settings.fixed_now()) if settings.brain_fixed_now else SystemClock()
    repo = repository or _make_repository(settings, restaurant, clock)
    secret = settings.caller_key_secret.get_secret_value().encode() or secrets.token_bytes(_KEY_CHARS)
    return AppContainer(
        settings=settings,
        restaurant=restaurant,
        clock=clock,
        repository=repo,
        brain=Brain(repo, clock, restaurant),
        speech=SpeechService(settings, stt_factory),
        ips=IpRegistry(settings),
        calls=CallRegistry(settings.max_concurrent_calls),
        brain_executor=ThreadPoolExecutor(
            max_workers=settings.max_concurrent_calls, thread_name_prefix="brain"
        ),
        secret=secret,
    )
