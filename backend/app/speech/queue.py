"""Bounded transcription queue with wait and run timeouts.

A Python thread cannot be killed. If a transcription runs past its timeout the caller gets
SttTimeout, the queue marks itself degraded and refuses new audio until that thread returns.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any

from app.observability.logging import log_event
from app.speech.base import SpeechToText, SttBusy, SttFailed, SttTimeout, SttUnavailable, Transcript

logger = logging.getLogger(__name__)
_MS = 1000


class TranscriptionQueue:
    def __init__(
        self,
        stt: SpeechToText,
        *,
        workers: int,
        max_queue: int,
        per_ip_max: int,
        max_wait_s: float,
        run_timeout_s: float,
    ) -> None:
        self._stt = stt
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stt")
        self._permits = asyncio.Semaphore(workers)
        self._max_queue = max_queue
        self._per_ip_max = per_ip_max
        self._max_wait = max_wait_s
        self._run_timeout = run_timeout_s
        self._waiting = 0
        self._per_ip: dict[str, int] = {}
        self._stuck = 0

    @property
    def degraded(self) -> bool:
        return self._stuck > 0

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def transcribe(self, audio: Any, ip: str) -> Transcript:
        if self._stuck:
            raise SttUnavailable
        if self._waiting >= self._max_queue or self._per_ip.get(ip, 0) >= self._per_ip_max:
            log_event(logger, "stt_failure", logging.WARNING, kind="busy")
            raise SttBusy
        self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        try:
            queued_at = perf_counter()
            self._waiting += 1
            try:
                await asyncio.wait_for(self._permits.acquire(), self._max_wait)
            except TimeoutError:
                log_event(logger, "stt_failure", logging.WARNING, kind="busy")
                raise SttBusy from None
            finally:
                self._waiting -= 1
            return await self._run(audio, perf_counter() - queued_at)
        finally:
            remaining = self._per_ip.get(ip, 1) - 1
            if remaining > 0:
                self._per_ip[ip] = remaining
            else:
                self._per_ip.pop(ip, None)

    async def _run(self, audio: Any, waited_s: float) -> Transcript:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, self._stt.transcribe, audio)
        started = perf_counter()
        try:
            result: Transcript = await asyncio.wait_for(asyncio.shield(future), self._run_timeout)
        except TimeoutError:
            self._stuck += 1
            future.add_done_callback(self._unstick)
            log_event(logger, "stt_failure", logging.ERROR, kind="timeout")
            raise SttTimeout from None
        except asyncio.CancelledError:
            future.add_done_callback(self._release_permit)
            raise
        except Exception as exc:
            self._permits.release()
            log_event(logger, "stt_failure", logging.ERROR, kind="failed", error_category=type(exc).__name__)
            raise SttFailed from None
        self._permits.release()
        log_event(
            logger, "stt_done", wait_ms=round(waited_s * _MS, 1),
            duration_ms=round((perf_counter() - started) * _MS, 1),
        )
        return result

    def _release_permit(self, future: "asyncio.Future[Any]") -> None:
        self._permits.release()
        if not future.cancelled():
            future.exception()  # mark the error as seen

    def _unstick(self, future: "asyncio.Future[Any]") -> None:
        self._stuck -= 1
        self._release_permit(future)
