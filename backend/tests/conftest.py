from collections.abc import Callable, Sequence
from datetime import datetime

import pytest

from app.brain import Brain, TurnResult
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
