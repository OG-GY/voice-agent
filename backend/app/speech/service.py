"""Speech-to-text lifecycle: load the model off the event loop, report status, queue requests."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.observability.logging import log_event
from app.speech.base import SpeechStatus, SpeechToText, SttUnavailable, Transcript
from app.speech.queue import TranscriptionQueue

logger = logging.getLogger(__name__)


def _default_factory(settings: Settings) -> Callable[[], SpeechToText]:
    def build() -> SpeechToText:
        from app.speech.whisper_stt import WhisperSpeechToText

        return WhisperSpeechToText(settings)

    return build


class SpeechService:
    def __init__(
        self, settings: Settings, stt_factory: Callable[[], SpeechToText] | None = None
    ) -> None:
        self._settings = settings
        self._factory = stt_factory or _default_factory(settings)
        self._queue: TranscriptionQueue | None = None
        self._task: asyncio.Task[None] | None = None
        self._status = SpeechStatus.LOADING if settings.stt_enabled else SpeechStatus.DISABLED

    @property
    def status(self) -> SpeechStatus:
        if self._status is SpeechStatus.READY and self._queue is not None and self._queue.degraded:
            return SpeechStatus.DEGRADED
        return self._status

    @property
    def available(self) -> bool:
        return self.status is SpeechStatus.READY

    async def start(self, wait: bool = False) -> None:
        if not self._settings.stt_enabled:
            return
        self._task = asyncio.create_task(self._load())
        if wait:
            await self._task

    async def _load(self) -> None:
        try:
            stt = await asyncio.to_thread(self._factory)
        except Exception as exc:  # missing library, missing model, bad config...
            self._status = SpeechStatus.FAILED
            log_event(logger, "stt_load_failed", logging.ERROR, error_category=type(exc).__name__)
            return
        s = self._settings
        self._queue = TranscriptionQueue(
            stt,
            workers=s.stt_workers,
            max_queue=s.stt_queue_max,
            per_ip_max=s.stt_queue_per_ip,
            max_wait_s=s.stt_queue_wait_seconds,
            run_timeout_s=s.stt_timeout_seconds,
        )
        self._status = SpeechStatus.READY
        log_event(logger, "stt_ready")

    async def transcribe(self, audio: Any, ip: str) -> Transcript:
        if self._queue is None or not self.available:
            raise SttUnavailable
        return await self._queue.transcribe(audio, ip)

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._queue is not None:
            self._queue.close()
