from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import pytest

from app.brain import Brain, TurnResult
from app.config import Settings
from app.container import AppContainer, build_container
from app.main import create_app
from app.services.booking import InMemoryBookingRepository
from app.services.clock import FixedClock
from app.services.restaurant import DEFAULT_RESTAURANT
from app.services.seed import seeded_repository

NOW = datetime(2026, 10, 28, 15, 0)  # a Wednesday; the seed makes Friday's window tables full


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def repo(clock: FixedClock) -> InMemoryBookingRepository:
    return seeded_repository(DEFAULT_RESTAURANT, clock)


@pytest.fixture
def brain(repo: InMemoryBookingRepository, clock: FixedClock) -> Brain:
    return Brain(repo, clock)


Talk = Callable[..., tuple[TurnResult, list[str]]]


@pytest.fixture
def talk() -> Talk:
    """talk(brain, ["line", ...], result=None) -> (last result, replies)."""

    def _talk(
        brain: Brain, lines: Sequence[str], result: TurnResult | None = None
    ) -> tuple[TurnResult, list[str]]:
        current = result or brain.start("test")
        replies: list[str] = []
        for line in lines:
            current = brain.handle(current.state, line)
            replies.append(current.reply)
        return current, replies

    return _talk


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Settings for tests: ignore any real .env, no speech model, in-memory bookings."""

    def build(**overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "app_env": "test", "stt_enabled": False, "repository_backend": "memory",
            "shutdown_grace_seconds": 0.5,  # tests must not wait 20 s for calls to drain
        }
        return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[call-arg]

    return build


@pytest.fixture
def app_factory(make_settings: Callable[..., Settings], clock: FixedClock) -> Callable[..., Any]:
    """app_factory(stt_factory=None, repository=None, **settings) -> (app, container)."""

    def build(
        stt_factory: Callable[[], Any] | None = None, repository: Any = None, **overrides: Any
    ) -> tuple[Any, AppContainer]:
        settings = make_settings(**overrides)
        repo = repository or seeded_repository(DEFAULT_RESTAURANT, clock)
        container = build_container(settings, repository=repo, stt_factory=stt_factory, clock=clock)
        return create_app(container=container), container

    return build
