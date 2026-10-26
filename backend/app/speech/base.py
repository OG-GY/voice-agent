"""Speech-to-text contract and its errors."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class SpeechStatus(StrEnum):
    DISABLED = "disabled"
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"  # a transcription is stuck; new audio is refused until it ends
    FAILED = "failed"


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float
    duration_s: float


class SpeechToText(Protocol):
    def transcribe(self, audio: Any) -> Transcript:
        """audio: float32 numpy array, 16 kHz, mono."""
        ...


class SttBusy(Exception):
    """The transcription queue is full, or the wait was too long."""


class SttTimeout(Exception):
    """The transcription ran longer than allowed."""


class SttUnavailable(Exception):
    """Speech recognition is disabled, still loading, failed to load, or stuck."""


class SttFailed(Exception):
    """The transcription itself raised an error."""
