"""Shared policy helpers: context, phase groups, and `finish`, which applies a decision."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.brain.config import BrainConfig
from app.brain.state import DialogueState
from app.brain.types import (
    ActionCall,
    ActionType,
    Decision,
    NLUResult,
    Phase,
    SlotChange,
    SlotName,
)
from app.services.booking import BookingRepository
from app.services.clock import Clock
from app.services.restaurant import RestaurantConfig

BOOKING_ORDER = (SlotName.SEATING, SlotName.DATE, SlotName.TIME, SlotName.PARTY_SIZE)
CONTACT_ORDER = (SlotName.NAME, SlotName.TITLE, SlotName.PHONE)

BOOKING_PHASES = frozenset({
    Phase.ASK_SEATING, Phase.COLLECT_BOOKING, Phase.OFFER_ALTERNATIVES,
    Phase.COLLECT_CONTACT, Phase.CONFIRM_BOOKING,
})
CANCEL_PHASES = frozenset({Phase.COLLECT_REF, Phase.COLLECT_CANCEL_NAME, Phase.CONFIRM_CANCEL})
FLOW_PHASES = BOOKING_PHASES | CANCEL_PHASES
# "Anything else?" phases: a booking or cancellation just finished, or an enquiry was answered.
CLOSING_PHASES = frozenset({Phase.BOOKED, Phase.CANCELLED, Phase.ANSWER_ENQUIRY})

# Actions that wait for the caller's answer; the last one becomes the pending question.
_QUESTIONS = frozenset({
    ActionType.ASK_SLOT, ActionType.ASK_SEATING, ActionType.SUGGEST_SEATING,
    ActionType.ASK_TITLE, ActionType.ASK_REF,
    ActionType.CONFIRM_BOOKING, ActionType.CONFIRM_CANCEL, ActionType.OFFER_BOOKING,
    ActionType.OFFER_ALTERNATIVES, ActionType.ASK_WHAT_TO_CHANGE, ActionType.ANYTHING_ELSE,
})
_SLOT_OF_ACTION = {
    ActionType.ASK_SEATING: SlotName.SEATING,
    ActionType.SUGGEST_SEATING: SlotName.SEATING,
    ActionType.ASK_TITLE: SlotName.TITLE,
    ActionType.ASK_REF: SlotName.BOOKING_REF,
}
_STRONG_YES = re.compile(r"\b(?:yes|yeah|yep|yup|sure|please|go ahead|book|reserve)\b")


@dataclass(frozen=True)
class PolicyContext:
    repo: BookingRepository
    clock: Clock
    restaurant: RestaurantConfig
    config: BrainConfig

    @property
    def now(self) -> datetime:
        return self.clock.now()


def act(kind: ActionType, **params: Any) -> ActionCall:
    return ActionCall(type=kind, params=params)


def ask_for(slot: SlotName) -> ActionCall:
    if slot in (SlotName.SEATING, SlotName.TITLE, SlotName.BOOKING_REF):
        return act({
            SlotName.SEATING: ActionType.ASK_SEATING,
            SlotName.TITLE: ActionType.ASK_TITLE,
            SlotName.BOOKING_REF: ActionType.ASK_REF,
        }[slot])
    return act(ActionType.ASK_SLOT, slot=slot)


def _expected_slot(question: ActionCall) -> SlotName | None:
    if question.type is ActionType.ASK_SLOT:
        slot: SlotName = question.params["slot"]
        return slot
    return _SLOT_OF_ACTION.get(question.type)


def finish(state: DialogueState, actions: list[ActionCall], phase: Phase, reason: str) -> Decision:
    """Build the decision and apply its effect on the phase, pending question and expected slot."""
    state.phase = phase
    if phase in (Phase.END, Phase.HANDOFF):
        state.ended = True
        state.pending_question = None
        state.expected_slot = None
    else:
        question = next((a for a in reversed(actions) if a.type in _QUESTIONS), None)
        if question is not None:
            state.pending_question = question
            state.expected_slot = _expected_slot(question)
    return Decision(actions=actions, next_phase=phase, reason=reason)


def reprompt(state: DialogueState) -> list[ActionCall]:
    """Re-ask what we were waiting for (or offer help when nothing is pending)."""
    return [state.pending_question] if state.pending_question else [act(ActionType.HELP)]


def end_call(state: DialogueState, reason: str) -> Decision:
    state.task = None
    return finish(state, [act(ActionType.GOODBYE)], Phase.END, reason)


def handoff(state: DialogueState, why: str, reason: str) -> Decision:
    return finish(state, [act(ActionType.HANDOFF, reason=why)], Phase.HANDOFF, reason)


def stalled(
    state: DialogueState, slot: SlotName, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    """Hand off when we keep asking for a slot and the caller never provides it."""
    if state.expected_slot is not slot or any(c.slot is slot for c in changes):
        return None
    state.slots[slot].attempts += 1
    attempts = state.slots[slot].attempts
    if attempts >= ctx.config.max_slot_attempts:
        return handoff(state, "too_many_failures", f"{slot.value} asked {attempts} times in vain")
    return None


def booking_changes(changes: list[SlotChange]) -> bool:
    return any(c.slot in BOOKING_ORDER for c in changes)


def polite_close(nlu: NLUResult) -> bool:
    """"ok thanks" (no real yes) ends an enquiry; "yes thanks" does not."""
    return "thank" in nlu.normalized and not _STRONG_YES.search(nlu.normalized)
