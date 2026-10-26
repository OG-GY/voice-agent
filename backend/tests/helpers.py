"""Test helpers shared by several test files."""

from typing import Any

from app.services.booking import RepositoryUnavailableError


class FlakyRepository:
    """Wraps a repository and fails on demand, like a database that is down."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.down = False

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            if self.down:
                raise RepositoryUnavailableError
            return attribute(*args, **kwargs)

        return call
