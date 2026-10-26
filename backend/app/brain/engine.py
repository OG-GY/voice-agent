"""The brain: text in, reply and decision trace out. Pure apart from the injected repository."""

import logging
from time import perf_counter

from app.brain.config import BrainConfig
from app.brain.nlg import render
from app.brain.nlg.honorifics import honorific_word
from app.brain.nlg.templates import T
from app.brain.nlu import run_nlu
from app.brain.nlu.entities.base import ExtractContext
from app.brain.policy import (
    PolicyContext,
    decide,
    greeting_decision,
    handle_hangup,
    handle_silence,
)
from app.brain.state import DialogueState, TurnResult
from app.brain.tracker import apply_nlu
from app.brain.types import (
    ActionCall,
    ActionType,
    CallEvent,
    Decision,
    Intent,
    NLUResult,
    Phase,
    SlotChange,
    Trace,
)
from app.services.booking import (
    BookingRepository,
    RepositoryUnavailableError,
    TooManyAttemptsError,
)
from app.services.clock import Clock
from app.services.restaurant import DEFAULT_RESTAURANT, RestaurantConfig

logger = logging.getLogger(__name__)

_MS_PER_SECOND = 1000


class Brain:
    def __init__(
        self,
        repo: BookingRepository,
        clock: Clock,
        restaurant: RestaurantConfig = DEFAULT_RESTAURANT,
        config: BrainConfig | None = None,
    ) -> None:
        self._clock = clock
        self._restaurant = restaurant
        self._config = config or BrainConfig()
        self._policy = PolicyContext(repo, clock, restaurant, self._config)

    def start(self, session_id: str, caller_key: str = "local") -> TurnResult:
        started = perf_counter()
        state = DialogueState(session_id=session_id, caller_key=caller_key)
        decision = greeting_decision(state)
        nlu = self._empty_nlu("")
        return self._finish(state, nlu, [], decision, Phase.GREETING, started)

    def handle(self, state: DialogueState, text: str) -> TurnResult:
        """Process one caller utterance. The given state is never modified."""
        started = perf_counter()
        working = state.model_copy(deep=True)
        working.turn += 1
        try:
            choosing = working.phase is Phase.OFFER_ALTERNATIVES and bool(working.offered_options)
            ctx = ExtractContext(
                self._clock.now(), self._restaurant, working.expected_slot, choosing
            )
            nlu = run_nlu(text, ctx, self._config, working.phase)
            changes = apply_nlu(working, nlu)
            before = working.phase
            decision = decide(working, nlu, changes, self._policy)
            return self._finish(working, nlu, changes, decision, before, started)
        except RepositoryUnavailableError:
            logger.error("booking storage unavailable on turn %d", working.turn)
            return self._stopped(
                state, text, started, ActionType.SYSTEM_UNAVAILABLE, False,
                "booking system unavailable: state kept",
            )
        except TooManyAttemptsError:
            logger.warning("verification limit reached on turn %d", working.turn)
            return self._stopped(
                state, text, started, ActionType.TRY_LATER, True,
                "too many failed verifications: call ended",
            )
        except Exception as exc:
            # Only the exception type is logged: messages and tracebacks may hold personal data.
            logger.error("brain failed on turn %d: %s", working.turn, type(exc).__name__)
            return self._fallback(state, text, started)

    def handle_event(self, state: DialogueState, event: CallEvent) -> TurnResult:
        """Non-speech events: the caller stayed silent, or hung up."""
        started = perf_counter()
        working = state.model_copy(deep=True)
        working.turn += 1
        before = working.phase
        decision = (
            handle_hangup(working)
            if event is CallEvent.HANGUP
            else handle_silence(working, self._policy)
        )
        return self._finish(working, self._empty_nlu(f"<{event.value}>"), [], decision, before, started)

    # -- internals ----------------------------------------------------------------------

    @staticmethod
    def _empty_nlu(text: str) -> NLUResult:
        return NLUResult(raw=text, normalized=text, intent=Intent.NOMATCH, intent_score=0.0)

    def _finish(
        self,
        state: DialogueState,
        nlu: NLUResult,
        changes: list[SlotChange],
        decision: Decision,
        phase_from: Phase,
        started: float,
    ) -> TurnResult:
        reply = render(decision, state, self._restaurant, self._config, self._clock.now().date())
        if reply:
            state.last_reply = reply
        trace = Trace(
            turn=state.turn, transcript=nlu.raw, normalized=nlu.normalized, intent=nlu.intent,
            intent_score=nlu.intent_score, ranked_intents=nlu.ranked, entities=nlu.entities,
            fuzzy_fixes=nlu.fuzzy_fixes, slot_changes=changes, phase_from=phase_from,
            phase_to=decision.next_phase, actions=decision.actions, reason=decision.reason,
            honorific=honorific_word(state), reply=reply,
            duration_ms=(perf_counter() - started) * _MS_PER_SECOND,
        )
        logger.info(
            "turn=%d %s->%s intent=%s actions=%s",
            state.turn, phase_from.value, decision.next_phase.value, nlu.intent.value,
            [a.type.value for a in decision.actions],
        )
        return TurnResult(state=state, reply=reply, trace=trace, ended=state.ended)

    def _stopped(
        self, state: DialogueState, text: str, started: float, action: ActionType, end: bool, reason: str
    ) -> TurnResult:
        """A turn that could not run: keep the state exactly as it was (or end the call)."""
        kept = state.model_copy(deep=True)
        kept.turn += 1
        if end:
            kept.ended = True
            kept.phase = Phase.END
            kept.pending_question = None
            kept.expected_slot = None
        decision = Decision(actions=[ActionCall(type=action)], next_phase=kept.phase, reason=reason)
        return self._finish(kept, self._empty_nlu(text), [], decision, state.phase, started)

    def _fallback(self, state: DialogueState, text: str, started: float) -> TurnResult:
        """A bug must never drop the call: apologise and keep the previous state."""
        kept = state.model_copy(deep=True)
        kept.turn += 1
        reply = T["fallback"][0]
        trace = Trace(
            turn=kept.turn, transcript=text, normalized=text, intent=Intent.NOMATCH,
            intent_score=0.0, ranked_intents=[], entities=[], fuzzy_fixes=[], slot_changes=[],
            phase_from=kept.phase, phase_to=kept.phase, actions=[],
            reason="internal error: asked the caller to repeat", honorific=None, reply=reply,
            duration_ms=(perf_counter() - started) * _MS_PER_SECOND,
        )
        return TurnResult(state=kept, reply=reply, trace=trace, ended=kept.ended)
