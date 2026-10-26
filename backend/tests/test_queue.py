"""The bounded transcription queue, with a fake speech-to-text (no model is loaded)."""

import asyncio
import threading

import pytest
from helpers import FakeStt

from app.speech.base import SttBusy, SttFailed, SttTimeout, SttUnavailable
from app.speech.queue import TranscriptionQueue

AUDIO = [0.0] * 1600


def make_queue(stt: FakeStt, **overrides: float | int) -> TranscriptionQueue:
    options = {
        "workers": 1, "max_queue": 1, "per_ip_max": 5, "max_wait_s": 0.5, "run_timeout_s": 2.0,
    }
    options.update(overrides)
    return TranscriptionQueue(stt, **options)  # type: ignore[arg-type]


async def settle() -> None:
    await asyncio.sleep(0.05)


async def test_a_transcription_returns_its_text() -> None:
    queue = make_queue(FakeStt("table for two"))
    assert (await queue.transcribe(AUDIO, "ip")).text == "table for two"
    queue.close()


async def test_a_full_queue_is_refused_at_once() -> None:
    gate = threading.Event()
    queue = make_queue(FakeStt(gate=gate), max_queue=1, max_wait_s=5)
    running = asyncio.create_task(queue.transcribe(AUDIO, "a"))
    await settle()
    waiting = asyncio.create_task(queue.transcribe(AUDIO, "b"))
    await settle()
    with pytest.raises(SttBusy):  # one running, one waiting: no room for a third
        await queue.transcribe(AUDIO, "c")
    gate.set()
    await asyncio.gather(running, waiting)
    queue.close()


async def test_waiting_too_long_is_refused() -> None:
    gate = threading.Event()
    queue = make_queue(FakeStt(gate=gate), max_wait_s=0.1)
    running = asyncio.create_task(queue.transcribe(AUDIO, "a"))
    await settle()
    with pytest.raises(SttBusy):
        await queue.transcribe(AUDIO, "b")
    gate.set()
    await running
    queue.close()


async def test_one_ip_cannot_fill_the_queue() -> None:
    gate = threading.Event()
    queue = make_queue(FakeStt(gate=gate), max_queue=4, per_ip_max=1)
    running = asyncio.create_task(queue.transcribe(AUDIO, "same-ip"))
    await settle()
    with pytest.raises(SttBusy):
        await queue.transcribe(AUDIO, "same-ip")
    gate.set()
    await running
    queue.close()


async def test_a_stuck_transcription_times_out_then_the_queue_recovers() -> None:
    gate = threading.Event()
    queue = make_queue(FakeStt(gate=gate), run_timeout_s=0.1)
    with pytest.raises(SttTimeout):
        await queue.transcribe(AUDIO, "a")
    assert queue.degraded
    with pytest.raises(SttUnavailable):  # refuses new audio while the thread is stuck
        await queue.transcribe(AUDIO, "b")
    gate.set()
    await asyncio.sleep(0.2)
    assert not queue.degraded
    assert (await queue.transcribe(AUDIO, "c")).text == "hello"
    queue.close()


async def test_a_failing_model_is_reported_and_does_not_block_the_queue() -> None:
    stt = FakeStt(fail=True)
    queue = make_queue(stt)
    with pytest.raises(SttFailed):
        await queue.transcribe(AUDIO, "a")
    stt.fail = False
    assert (await queue.transcribe(AUDIO, "a")).text == "hello"
    queue.close()
