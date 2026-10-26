"""PCM16 audio checks and conversion. Checks use the byte length, before any buffer is built."""

from enum import StrEnum

import numpy as np

from app.config import BYTES_PER_SAMPLE, SAMPLE_RATE

_INT16_SCALE = 32768.0


class AudioProblem(StrEnum):
    INVALID = "invalid"
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"


def check_pcm16(num_bytes: int, min_seconds: float, max_seconds: float) -> tuple[AudioProblem | None, float]:
    """(problem, duration in seconds) for a PCM16 16 kHz mono recording of this size."""
    if num_bytes == 0 or num_bytes % BYTES_PER_SAMPLE:
        return AudioProblem.INVALID, 0.0
    seconds = num_bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE)
    if seconds > max_seconds:
        return AudioProblem.TOO_LONG, seconds
    if seconds < min_seconds:
        return AudioProblem.TOO_SHORT, seconds
    return None, seconds


def pcm16_to_float32(data: bytes) -> "np.ndarray[tuple[int], np.dtype[np.float32]]":
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / _INT16_SCALE
