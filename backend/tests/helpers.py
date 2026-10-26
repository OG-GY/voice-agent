"""Test helpers shared by several test files."""

import threading
from typing import Any

from app.services.booking import RepositoryUnavailableError
from app.speech.base import Transcript


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


class FakeStt:
    """A speech-to-text that never loads a model: scripted text, optionally blocked or failing."""

    def __init__(
        self, text: str = "hello", gate: threading.Event | None = None, fail: bool = False
    ) -> None:
        self.text = text
        self.gate = gate
        self.fail = fail
        self.calls = 0

    def transcribe(self, audio: Any) -> Transcript:
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.fail:
            raise ValueError("boom")
        return Transcript(self.text, 0.9, 1.0)
