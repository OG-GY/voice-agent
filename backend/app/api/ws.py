"""The /ws/call WebSocket: protocol loop only. The logic lives in CallSession and the brain."""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Coroutine
from time import perf_counter
from typing import Any, Literal

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from app.api.call_session import CallBusyError, CallSession, TurnTimeoutError
from app.api.calls import ActiveCall
from app.api.errors import ERROR_MESSAGES, CloseCode, ErrorCode, ProtocolError
from app.api.limits import AdmitResult, ConnectionLimits
from app.api.sanitize import public_turn
from app.api.schemas import (
    ErrorMessage,
    ReadyMessage,
    TextMessage,
    TranscriptMessage,
    parse_client_message,
)
from app.brain import CallEvent, TurnResult
from app.config import SAMPLE_RATE
from app.container import AppContainer
from app.observability.logging import log_event, reset_session, set_session
from app.speech.audio import AudioProblem, check_pcm16, pcm16_to_float32
from app.speech.base import SttBusy, SttFailed, SttTimeout, SttUnavailable

router = APIRouter()
logger = logging.getLogger(__name__)
_MS = 1000
Source = Literal["greeting", "text", "audio"]


class ClientGone(Exception):
    """The client disconnected."""


def client_ip(ws: WebSocket, trusted: list[str]) -> str:
    peer = ws.client.host if ws.client else "unknown"
    if peer in trusted:  # X-Forwarded-For is only believed when it comes from our own proxy
        first = ws.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if first:
            return first
    return peer


def is_secure(ws: WebSocket, trusted: list[str]) -> bool:
    if ws.url.scheme in ("wss", "https"):
        return True
    peer = ws.client.host if ws.client else ""
    return peer in trusted and ws.headers.get("x-forwarded-proto", "").lower() in ("https", "wss")


def origin_allowed(ws: WebSocket, allowed: list[str], production: bool) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:
        return not production  # non-browser tools send no Origin: fine for development only
    return origin in allowed


class CallHandler:
    def __init__(self, container: AppContainer, websocket: WebSocket) -> None:
        self.c = container
        self.s = container.settings
        self.ws = websocket
        self.ip = client_ip(websocket, self.s.trusted_proxy_list)
        self.limits = ConnectionLimits(self.s)
        self.session_id = uuid.uuid4().hex[:12]
        self.session: CallSession | None = None
        self.closing = False
        self.gone = False
        self._ip_held = False
        self._call_held = False

    # -- lifecycle ----------------------------------------------------------------------

    async def run(self) -> None:
        reason = self._pre_accept_rejection()
        if reason is not None:
            log_event(logger, "connection_rejected", logging.WARNING, reason=reason)
            await self.ws.close(code=CloseCode.POLICY)
            return
        await self.ws.accept()
        refusal = self._admit()
        if refusal is not None:
            log_event(logger, "connection_rejected", logging.WARNING, reason=refusal)
            await self.ws.close(code=CloseCode.TRY_LATER)
            return
        token = set_session(self.session_id)
        started = perf_counter()
        try:
            await self._serve()
        except (WebSocketDisconnect, ClientGone):
            self.gone = True
        except asyncio.CancelledError:
            self.gone = True
            raise
        except Exception as exc:
            log_event(logger, "call_error", logging.ERROR, error_category=type(exc).__name__)
            with contextlib.suppress(Exception):
                await self._error(ErrorCode.SERVICE_UNAVAILABLE)
                await self.ws.close(code=CloseCode.INTERNAL)
        finally:
            await self._cleanup(started)
            reset_session(token)

    def _pre_accept_rejection(self) -> str | None:
        production = self.s.app_env == "production"
        if production and not is_secure(self.ws, self.s.trusted_proxy_list):
            return "not_secure"
        if not origin_allowed(self.ws, self.s.cors_origin_list, production):
            return "origin"
        return None

    def _admit(self) -> str | None:
        if self.c.shutting_down:
            return "shutting_down"
        result = self.c.ips.admit(self.ip)
        if result is not AdmitResult.OK:
            return result.value
        self._ip_held = True
        if not self.c.calls.try_add(ActiveCall(self.session_id, self.ws)):
            self.c.ips.release(self.ip)
            self._ip_held = False
            return "call_limit"
        self._call_held = True
        return None

    async def _cleanup(self, started: float) -> None:
        session = self.session
        unexpected = self.gone and session is not None and not session.ended
        # Free the slots first, with no await: a cancelled task can be cancelled again at the
        # next await, and the call must never stay registered.
        if self._call_held:
            self.c.calls.remove(self.session_id)
        if self._ip_held:
            self.c.ips.release(self.ip)
        if session is not None and not session.ended:
            with contextlib.suppress(Exception):
                await session.hangup()
        if session is not None:
            if unexpected:
                log_event(logger, "unexpected_disconnect", logging.WARNING)
            log_event(
                logger, "call_ended", duration_s=round(perf_counter() - started, 1),
                turns=session.state.turn if session.state else 0,
            )

    # -- main loop ----------------------------------------------------------------------

    async def _serve(self) -> None:
        s = self.s
        self.session = CallSession(
            self.c.brain, self.session_id, self.c.caller_key(self.ip), self.c.brain_executor,
            s.turn_timeout_seconds, s.waiting_messages_per_call,
        )
        limits = {"max_text_chars": float(s.max_text_chars), "max_utterance_seconds": s.max_utterance_seconds}
        await self._send(ReadyMessage(session_id=self.session_id, sample_rate=SAMPLE_RATE, limits=limits))
        log_event(logger, "call_started", active_calls=self.c.calls.count)
        await self._turn(self.session.start(), "greeting", "")
        while not self.session.ended and not self.closing:
            try:
                message = await asyncio.wait_for(self.ws.receive(), s.idle_timeout_seconds)
            except TimeoutError:
                await self._turn(self.session.handle_event(CallEvent.SILENCE), "text", "")
                continue
            if message["type"] == "websocket.disconnect":
                raise ClientGone
            if message.get("bytes") is not None:
                await self._on_audio(message["bytes"])
            elif message.get("text") is not None:
                await self._on_text_frame(message["text"])
        if self.session.ended and not self.closing:
            await self.ws.close(code=CloseCode.NORMAL)

    async def _admit_message(self) -> bool:
        if self.limits.allow_message() and self.c.ips.allow_message(self.ip):
            return True
        await self._invalid(ErrorCode.RATE_LIMITED)
        return False

    async def _on_text_frame(self, raw: str) -> None:
        assert self.session is not None
        if not await self._admit_message():
            return
        if len(raw.encode("utf-8")) > self.s.text_frame_max_bytes:
            await self._invalid(ErrorCode.TEXT_TOO_LONG)
            return
        try:
            message = parse_client_message(raw)
        except ProtocolError as exc:
            await self._invalid(exc.code)
            return
        if isinstance(message, TextMessage):
            if len(message.text) > self.s.max_text_chars:
                await self._invalid(ErrorCode.TEXT_TOO_LONG)
                return
            await self._turn(self.session.handle_text(message.text), "text", message.text)
        elif message.kind == "silence":
            await self._turn(self.session.handle_event(CallEvent.SILENCE), "text", "")
        elif message.kind == "barge_in":
            await self.session.mark_barge_in()
        else:
            await self._turn(self.session.handle_event(CallEvent.HANGUP), "text", "")

    async def _on_audio(self, data: bytes) -> None:
        assert self.session is not None
        if not await self._admit_message():
            return
        problem, seconds = check_pcm16(
            len(data), self.s.min_utterance_seconds, self.s.max_utterance_seconds
        )
        if problem is AudioProblem.INVALID:
            await self._invalid(ErrorCode.AUDIO_INVALID)
            return
        if problem is AudioProblem.TOO_LONG:
            await self._invalid(ErrorCode.AUDIO_TOO_LONG)
            return
        if problem is AudioProblem.TOO_SHORT:  # a click or breath: treat as "not understood"
            await self._turn(self.session.handle_text(""), "audio", "")
            return
        if not self.limits.allow_audio(seconds):
            await self._error(ErrorCode.RATE_LIMITED)
            return
        if not self.c.speech.available:
            await self._error(ErrorCode.STT_UNAVAILABLE)
            return
        try:
            transcript = await self.c.speech.transcribe(pcm16_to_float32(data), self.ip)
        except SttBusy:
            await self._error(ErrorCode.STT_BUSY)
            return
        except SttTimeout:
            await self._error(ErrorCode.STT_TIMEOUT)
            return
        except (SttUnavailable, SttFailed):
            await self._error(ErrorCode.STT_UNAVAILABLE)
            return
        await self._send(TranscriptMessage(text=transcript.text))
        await self._turn(self.session.handle_text(transcript.text), "audio", transcript.text)

    # -- sending ------------------------------------------------------------------------

    async def _turn(
        self, work: Coroutine[Any, Any, TurnResult], source: Source, transcript: str
    ) -> None:
        started = perf_counter()
        try:
            result = await work
        except CallBusyError:
            await self._invalid(ErrorCode.RATE_LIMITED)
            return
        except TurnTimeoutError:
            await self._error(ErrorCode.SERVICE_UNAVAILABLE)
            return
        await self._send(public_turn(result, source, transcript, self.s.expose_debug_trace))
        trace = result.trace
        log_event(
            logger, "turn", turn=trace.turn, phase_from=trace.phase_from.value,
            phase_to=trace.phase_to.value, intent=trace.intent.value,
            actions=[a.type.value for a in trace.actions],
            duration_ms=round((perf_counter() - started) * _MS, 1),
        )
        if self.s.log_transcripts:  # development only: refused by the config in production
            logger.debug("transcript", extra={"fields": {"text": transcript, "reply": result.reply}})

    async def _send(self, model: BaseModel) -> None:
        await self.ws.send_json(model.model_dump(mode="json"))

    async def _error(self, code: ErrorCode) -> None:
        await self._send(ErrorMessage(code=code.value, message=ERROR_MESSAGES[code]))

    async def _invalid(self, code: ErrorCode) -> None:
        await self._error(code)
        log_event(logger, "invalid_message", logging.WARNING, error_code=code.value)
        close_now = self.limits.note_invalid()
        self.c.ips.note_invalid(self.ip)
        if close_now:
            self.closing = True
            await self.ws.close(code=CloseCode.POLICY)


@router.websocket("/ws/call")
async def call_endpoint(websocket: WebSocket) -> None:
    await CallHandler(websocket.app.state.container, websocket).run()
