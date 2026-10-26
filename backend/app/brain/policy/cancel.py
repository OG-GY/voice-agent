"""Cancellation flow: ask for the reference, then the name, verify both, confirm, cancel.

A booking is never described or cancelled unless the reference AND the name match. Every
kind of mismatch gets the same reply, so nothing reveals which references exist.
"""

from app.brain.policy.common import (
    PolicyContext,
    act,
    finish,
    handoff,
    reprompt,
    stalled,
)
from app.brain.state import DialogueState
from app.brain.types import (
    ActionType,
    Decision,
    Intent,
    NLUResult,
    Phase,
    SlotChange,
    SlotName,
    Task,
)
from app.services.booking import AlreadyCancelledError, BookingNotFoundError, BookingStatus


def _verification_failed(state: DialogueState, ctx: PolicyContext) -> Decision:
    """Same outcome whatever was wrong; both answers are cleared so the caller starts over."""
    state.verify_failures += 1
    state.clear_slot(SlotName.BOOKING_REF)
    state.clear_slot(SlotName.NAME)
    if state.verify_failures >= ctx.config.max_verify_failures:
        return handoff(state, "verification_failed", "details did not match: call limit reached")
    return finish(
        state, [act(ActionType.VERIFICATION_FAILED), act(ActionType.ASK_REF)],
        Phase.COLLECT_REF, "details did not match",
    )


def _verify(state: DialogueState, ctx: PolicyContext) -> Decision:
    ref, name = state.value(SlotName.BOOKING_REF), state.value(SlotName.NAME)
    booking = ctx.repo.find_for_cancel(ref, name, state.caller_key)
    if booking is None:
        return _verification_failed(state, ctx)
    if booking.status is BookingStatus.CANCELLED:
        state.clear_slots()
        state.task = None
        actions = [
            act(ActionType.CANCEL_DONE, booking=booking, already=True),
            act(ActionType.ANYTHING_ELSE),
        ]
        return finish(state, actions, Phase.CANCELLED, "booking was already cancelled")
    return finish(
        state, [act(ActionType.CONFIRM_CANCEL, booking=booking)], Phase.CONFIRM_CANCEL,
        "details verified: asked to confirm the cancellation",
    )


def advance_cancel(
    state: DialogueState, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    """Ask for what's missing (reference, then name); verify as soon as both are known."""
    if not state.is_filled(SlotName.BOOKING_REF):
        if stuck := stalled(state, SlotName.BOOKING_REF, changes, ctx):
            return stuck
        return finish(state, [act(ActionType.ASK_REF)], Phase.COLLECT_REF, "need booking reference")
    if not state.is_filled(SlotName.NAME):
        if stuck := stalled(state, SlotName.NAME, changes, ctx):
            return stuck
        return finish(
            state, [act(ActionType.ASK_SLOT, slot=SlotName.NAME, for_cancel=True)],
            Phase.COLLECT_CANCEL_NAME, "need the name on the booking",
        )
    return _verify(state, ctx)


def start_cancel(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    state.task = Task.CANCEL
    state.offered_options = []
    return advance_cancel(state, changes, ctx)


def handle_cancel_details(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    """COLLECT_REF and COLLECT_CANCEL_NAME."""
    return advance_cancel(state, changes, ctx)


def handle_confirm_cancel(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    if any(c.slot in (SlotName.BOOKING_REF, SlotName.NAME) for c in changes):
        return advance_cancel(state, changes, ctx)  # details changed: verify again
    if nlu.intent is Intent.AFFIRM:
        try:
            booking = ctx.repo.cancel(
                state.value(SlotName.BOOKING_REF), state.value(SlotName.NAME)
            )
        except (BookingNotFoundError, AlreadyCancelledError):
            return _verification_failed(state, ctx)
        state.clear_slots()
        state.task = None
        actions = [act(ActionType.CANCEL_DONE, booking=booking), act(ActionType.ANYTHING_ELSE)]
        return finish(state, actions, Phase.CANCELLED, "booking cancelled")
    if nlu.intent in (Intent.DENY, Intent.DECLINE):
        state.clear_slots()
        state.task = None
        return finish(
            state, [act(ActionType.ANYTHING_ELSE, kept=True)], Phase.ANSWER_ENQUIRY,
            "caller kept the booking",
        )
    return finish(state, reprompt(state), state.phase, "unclear answer to cancel confirmation")
