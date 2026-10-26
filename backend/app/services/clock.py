"""Injectable clocks so the brain never reads the system time directly.

All times are naive local time: every caller is in the restaurant's area.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now()


class FixedClock:
    """A clock that always returns the same moment (CLI --now flag, manual checks)."""

    def __init__(self, fixed: datetime) -> None:
        self._now = fixed

    def now(self) -> datetime:
        return self._now
