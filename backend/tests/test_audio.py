import numpy as np
import pytest

from app.speech.audio import AudioProblem, check_pcm16, pcm16_to_float32

ONE_SECOND = 16_000 * 2  # bytes of PCM16 mono at 16 kHz


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, AudioProblem.INVALID),
        (3, AudioProblem.INVALID),  # odd byte count cannot be PCM16
        (ONE_SECOND * 31, AudioProblem.TOO_LONG),
        (1000, AudioProblem.TOO_SHORT),
        (ONE_SECOND, None),
    ],
)
def test_size_checks_use_the_byte_length(size: int, expected: AudioProblem | None) -> None:
    problem, _ = check_pcm16(size, min_seconds=0.2, max_seconds=30)
    assert problem is expected


def test_duration_is_reported() -> None:
    _, seconds = check_pcm16(ONE_SECOND * 2, 0.2, 30)
    assert seconds == pytest.approx(2.0)


def test_pcm16_converts_to_floats_between_minus_one_and_one() -> None:
    samples = np.array([0, 16384, -32768, 32767], dtype="<i2").tobytes()
    converted = pcm16_to_float32(samples)
    assert converted.dtype == np.float32
    assert converted.tolist() == pytest.approx([0.0, 0.5, -1.0, 0.99997], abs=1e-4)
