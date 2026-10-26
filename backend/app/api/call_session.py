"""One call: owns the dialogue state and runs one turn at a time. No FastAPI types here."""

import asyncio
from collections.abc import Callable
from concurrent.futures import Executor

from app.brain import Brain, CallEvent, DialogueState, TurnResult


class CallBusyError(Exception):
    """Too many messages are already waiting for this call's turn."""


class TurnTimeoutError(Exception):
    """A turn took longer than allowed; the call state was left as it was."""


class CallSession:
    def __init__(
        self,
        brain: Brain,
        session_id: str,
        caller_key: str,
        executor: Executor,
        turn_timeout_s: float,
        max_waiting: int,
    ) -> None:
        self.session_id = session_id
        self.state: DialogueState | None = None
        self.ended = False
        self._brain = brain
        self._caller_key = caller_key
        self._executor = executor
        self._timeout = turn_timeout_s
        self._max_waiting = max_waiting
        self._lock = asyncio.Lock()
        self._busy = 0  # the running turn plus the ones waiting for it

    async def _run(self, work: Callable[[DialogueState | None], TurnResult]) -> TurnResult:
        if self._busy >= self._max_waiting + 1:
            raise CallBusyError
        self._busy += 1
        try:
            async with self._lock:
                loop = asyncio.get_running_loop()
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(self._executor, work, self.state), self._timeout
                    )
                except TimeoutError:
                    raise TurnTimeoutError from None
                self.state = result.state
                self.ended = result.ended
                return result
        finally:
            self._busy -= 1

    async def start(self) -> TurnResult:
        return await self._run(lambda _: self._brain.start(self.session_id, self._caller_key))

    async def handle_text(self, text: str) -> TurnResult:
        return await self._run(lambda state: self._brain.handle(_need(state), text))

    async def handle_event(self, event: CallEvent) -> TurnResult:
        return await self._run(lambda state: self._brain.handle_event(_need(state), event))

    async def mark_barge_in(self) -> None:
        async with self._lock:
            if self.state is not None:
                self.state.last_reply_interrupted = True

    async def hangup(self) -> None:
        """Tell the brain the caller is gone (once)."""
        if self.ended or self.state is None:
            return
        await self.handle_event(CallEvent.HANGUP)


def _need(state: DialogueState | None) -> DialogueState:
    if state is None:
        raise RuntimeError("the call has not started")
    return state
