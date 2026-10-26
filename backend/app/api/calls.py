"""Registry of active calls: the global call cap, shutdown notices and draining."""

import asyncio
import contextlib
from dataclasses import dataclass

from fastapi import WebSocket

from app.api.errors import CloseCode
from app.api.schemas import ClosingMessage

_POLL_S = 0.05


@dataclass
class ActiveCall:
    session_id: str
    websocket: WebSocket


class CallRegistry:
    def __init__(self, max_calls: int) -> None:
        self._max = max_calls
        self._calls: dict[str, ActiveCall] = {}

    @property
    def count(self) -> int:
        return len(self._calls)

    def try_add(self, call: ActiveCall) -> bool:
        if len(self._calls) >= self._max:
            return False
        self._calls[call.session_id] = call
        return True

    def remove(self, session_id: str) -> None:
        self._calls.pop(session_id, None)

    async def notify_closing(self) -> None:
        message = ClosingMessage(reason="restart").model_dump(mode="json")
        for call in list(self._calls.values()):
            with contextlib.suppress(Exception):
                await call.websocket.send_json(message)

    async def drain(self, grace_s: float) -> None:
        """Wait for calls to finish; close whatever is left when the grace period ends."""
        waited = 0.0
        while self._calls and waited < grace_s:
            await asyncio.sleep(_POLL_S)
            waited += _POLL_S
        for call in list(self._calls.values()):
            with contextlib.suppress(Exception):
                await call.websocket.close(code=CloseCode.GOING_AWAY)
        self._calls.clear()
