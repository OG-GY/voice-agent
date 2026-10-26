"""Policy: decide what to do next. Interrupts run first, then the handler for the phase.

`decide` also applies the decision to the state (phase, pending question, expected slot).

Action parameters the replies (NLG) can rely on:
  ASK_SLOT(slot, [options], [range])  ASK_SEATING  ASK_TITLE  ASK_REF
  ACK_SLOTS(slots, corrected, available)       slot values are read from the state
  EXPLAIN_INVALID(code, **details)             see validation.py for codes and details
  OFFER_ALTERNATIVES(options, lost, ...)       options are Option objects
  CONFIRM_BOOKING                              read-back from the state's slots
  BOOKING_DONE(booking)  CANCEL_DONE(booking, [already])  CONFIRM_CANCEL(booking)
  VERIFICATION_FAILED  ANSWER_AVAILABILITY(...)  ANYTHING_ELSE([kept])
  HANDOFF(reason)  GREET([restarted])  DECLINE_OUT_OF_SCOPE  WARN_UNSAVED  ...
"""

from collections.abc import Callable

from app.brain.policy.booking import handle_collect, handle_confirm, handle_contact
from app.brain.policy.cancel import handle_cancel_details, handle_confirm_cancel
from app.brain.policy.common import PolicyContext, act, end_call, finish, reprompt
from app.brain.policy.enquiry import handle_closing, handle_greeting, handle_offer_booking
from app.brain.policy.interrupts import INTERRUPTS
from app.brain.state import DialogueState
from app.brain.types import ActionType, Decision, NLUResult, Phase, SlotChange

Handler = Callable[[DialogueState, NLUResult, list[SlotChange], PolicyContext], Decision]

HANDLERS: dict[Phase, Handler] = {
    Phase.GREETING: handle_greeting,
    Phase.ASK_SEATING: handle_collect,
    Phase.COLLECT_BOOKING: handle_collect,
    Phase.CHECK_AVAILABILITY: handle_collect,
    Phase.OFFER_ALTERNATIVES: handle_collect,
    Phase.COLLECT_CONTACT: handle_contact,
    Phase.CONFIRM_BOOKING: handle_confirm,
    Phase.COLLECT_REF: handle_cancel_details,
    Phase.COLLECT_CANCEL_NAME: handle_cancel_details,
    Phase.CONFIRM_CANCEL: handle_confirm_cancel,
    Phase.OFFER_BOOKING: handle_offer_booking,
    Phase.BOOKED: handle_closing,
    Phase.CANCELLED: handle_closing,
    Phase.ANSWER_ENQUIRY: handle_closing,
}


def decide(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    if state.ended:
        return Decision(actions=[], next_phase=state.phase, reason="call already ended")
    for interrupt in INTERRUPTS:
        decision = interrupt(state, nlu, changes, ctx)
        if decision is not None:
            return decision
    return HANDLERS[state.phase](state, nlu, changes, ctx)


def greeting_decision(state: DialogueState) -> Decision:
    return finish(state, [act(ActionType.GREET)], Phase.GREETING, "call started")


def handle_silence(state: DialogueState, ctx: PolicyContext) -> Decision:
    state.silence_count += 1
    limit = ctx.config.max_hold_silence if state.hold_mode else ctx.config.max_silence
    if state.silence_count > limit:
        return end_call(state, "no response from the caller")
    if state.hold_mode and state.silence_count == 1:
        return finish(state, [], state.phase, "caller is holding: stayed quiet")
    actions = [act(ActionType.CHECK_PRESENCE)]
    if state.pending_question:
        actions += reprompt(state)
    return finish(state, actions, state.phase, f"silence {state.silence_count}: checked presence")


def handle_hangup(state: DialogueState) -> Decision:
    reason = f"caller hung up during {state.phase.value}"
    return finish(state, [], Phase.END, reason)


__all__ = [
    "HANDLERS",
    "PolicyContext",
    "decide",
    "greeting_decision",
    "handle_hangup",
    "handle_silence",
]
