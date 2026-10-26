"""Global interrupts, checked before the phase handler on every turn."""

from collections.abc import Callable

from app.brain.policy.booking import start_booking
from app.brain.policy.cancel import start_cancel
from app.brain.policy.common import (
    BOOKING_ORDER,
    BOOKING_PHASES,
    CANCEL_PHASES,
    PolicyContext,
    act,
    end_call,
    finish,
    handoff,
    reprompt,
)
from app.brain.policy.enquiry import answer_questions
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

Interrupt = Callable[
    [DialogueState, NLUResult, list[SlotChange], PolicyContext], Decision | None
]

_QUESTION_INTENTS = {
    Intent.FAQ_HOURS,
    Intent.FAQ_LOCATION,
    Intent.FAQ_SEATING,
    Intent.ASK_AVAILABILITY,
}


def _booking_in_progress(state: DialogueState) -> bool:
    return (
        state.task is Task.BOOKING
        and state.phase in BOOKING_PHASES
        and any(state.is_filled(s) for s in BOOKING_ORDER)
    )


def pending_switch(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    """Answer to "shall I drop the booking we were making?"."""
    if state.pending_switch is None:
        return None
    state.pending_switch = None
    if nlu.intent is Intent.AFFIRM:
        state.clear_slots()
        return start_cancel(state, nlu, changes, ctx)
    if nlu.intent in (Intent.DENY, Intent.DECLINE):
        return finish(state, reprompt(state), state.phase, "caller kept the booking in progress")
    return None


def goodbye(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    warned = state.unsaved_warned_turn == state.turn - 1
    leaving = nlu.intent is Intent.GOODBYE or (
        warned and nlu.intent in (Intent.DENY, Intent.DECLINE)
    )
    if not leaving:
        return None
    if _booking_in_progress(state) and not warned:
        state.unsaved_warned_turn = state.turn
        return finish(
            state, [act(ActionType.WARN_UNSAVED)], state.phase,
            "goodbye in the middle of a booking: warned once",
        )
    return end_call(state, "caller said goodbye")


def ask_human(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.ASK_HUMAN:
        return None
    return handoff(state, "human", "caller asked for a person")


def restart(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.RESTART:
        return None
    state.clear_slots()
    state.task = None
    state.offered_options = []
    state.pending_question = None
    state.expected_slot = None
    return finish(
        state, [act(ActionType.GREET, restarted=True)], Phase.GREETING, "caller asked to start over"
    )


def hold(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is Intent.HOLD:
        return finish(state, [act(ActionType.HOLD_ACK)], state.phase, "caller asked us to wait")
    if state.hold_mode and nlu.is_noise:
        return finish(state, [], state.phase, "caller is holding: stayed quiet")
    return None


def repeat(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.REPEAT:
        return None
    return finish(state, [act(ActionType.REPEAT_LAST)], state.phase, "caller asked to repeat")


def help_(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.HELP:
        return None
    actions = [act(ActionType.HELP)]
    if state.pending_question:
        actions.append(state.pending_question)
    return finish(state, actions, state.phase, "caller asked what we can do")


def questions(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent not in _QUESTION_INTENTS:
        return None
    return answer_questions(state, nlu, changes, ctx)


def out_of_scope(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.OUT_OF_SCOPE:
        return None
    if state.out_of_scope_count >= ctx.config.max_out_of_scope:
        return handoff(state, "out_of_scope", "too many off-topic questions in a row")
    actions = [act(ActionType.DECLINE_OUT_OF_SCOPE)]
    if state.pending_question:
        actions.append(state.pending_question)
    return finish(state, actions, state.phase, "off-topic question: declined politely")


def nomatch(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.NOMATCH:
        return None
    if state.nomatch_count >= ctx.config.max_nomatch:
        return handoff(state, "too_many_failures", "could not understand the caller 3 times")
    actions = [act(ActionType.REPROMPT), *reprompt(state)]
    return finish(state, actions, state.phase, "did not understand: asked again")


def cancel_request(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.CANCEL_BOOKING or state.phase in CANCEL_PHASES:
        return None
    if _booking_in_progress(state):
        state.pending_switch = Task.CANCEL
        return finish(
            state, [act(ActionType.CONFIRM_TASK_SWITCH)], state.phase,
            "cancel requested mid-booking: asked before dropping it",
        )
    return start_cancel(state, nlu, changes, ctx)


def book_from_cancel(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision | None:
    if nlu.intent is not Intent.BOOK or state.phase not in CANCEL_PHASES:
        return None
    state.clear_slot(SlotName.BOOKING_REF)
    state.clear_slot(SlotName.NAME)
    return start_booking(state, changes, ctx)


INTERRUPTS: tuple[Interrupt, ...] = (
    pending_switch, goodbye, ask_human, restart, hold, repeat, help_, questions,
    out_of_scope, nomatch, cancel_request, book_from_cancel,
)
