"""Lets the signal handler in serve.py tell the running app to start shutting down."""

from typing import Protocol


class _Stoppable(Protocol):
    def begin_shutdown(self) -> None: ...


_current: _Stoppable | None = None


def register(container: _Stoppable) -> None:
    global _current
    _current = container


def clear() -> None:
    global _current
    _current = None


def begin_shutdown() -> None:
    if _current is not None:
        _current.begin_shutdown()
