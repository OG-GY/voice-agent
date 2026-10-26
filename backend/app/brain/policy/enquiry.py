"""Enquiries (hours, location, availability) and the phases around them."""

from datetime import date, time

from app.brain.policy.booking import start_booking
from app.brain.policy.common import (
    CLOSING_PHASES,
    FLOW_PHASES,
    PolicyContext,
    act,
    booking_changes,
    end_call,
    finish,
    polite_close,
    reprompt,
)
from app.brain.policy.validation import validate_date, validate_seating, validate_time
from app.brain.state import DialogueState
from app.brain.types import (
    ActionCall,
    ActionType,
    Decision,
    Intent,
    NLUResult,
    Phase,
    Seating,
    SlotChange,
    SlotName,
    Task,
    TimeRange,
)

_SHOWN_TIMES = 4
_NEAREST_SHOWN = 2
_DEFAULT_PARTY = 2
_MINUTES_PER_HOUR = 60


def _minutes(t: time) -> int:
    return t.hour * _MINUTES_PER_HOUR + t.minute


def _spread(times: list[time], n: int) -> list[time]:
    """Pick up to n times spread evenly across the list."""
    if len(times) <= n:
        return times
    indexes = sorted({round(i * (len(times) - 1) / (n - 1)) for i in range(n)})
    return [times[i] for i in indexes]


def _next_day(
    ctx: PolicyContext, d: date, party: int | None, seating: Seating | None
) -> date | None:
    categories = [seating] if seating else list(Seating)
    days = [ctx.repo.next_available_day(d, party or _DEFAULT_PARTY, c) for c in categories]
    return min((x for x in days if x), default=None)


def _availability(state: DialogueState, ctx: PolicyContext) -> list[ActionCall]:
    now = ctx.now
    d = state.value(SlotName.DATE) if state.is_filled(SlotName.DATE) else None
    assumed_today = d is None
    if d is None:
        d = now.date()
    if issue := validate_date(d, ctx):
        return [act(ActionType.EXPLAIN_INVALID, code=issue.code, **issue.params)]
    seating = state.value(SlotName.SEATING) if state.is_filled(SlotName.SEATING) else None
    party = state.value(SlotName.PARTY_SIZE) if state.is_filled(SlotName.PARTY_SIZE) else None
    t = state.value(SlotName.TIME) if state.is_filled(SlotName.TIME) else None
    if seating and party and (issue := validate_seating(seating, party, ctx)):
        return [act(ActionType.EXPLAIN_INVALID, code=issue.code, **issue.params)]
    if t and (issue := validate_time(t, d, ctx)):
        return [act(ActionType.EXPLAIN_INVALID, code=issue.code, **issue.params)]
    free = ctx.repo.availability_summary(d, seating, party)
    params: dict[str, object] = {
        "date": d, "assumed_today": assumed_today, "seating": seating, "party": party,
        "time": t, "available": True, "times": [], "nearest": [], "next_day": None,
    }
    if t is not None:
        params["available"] = t in free
        params["nearest"] = sorted(free, key=lambda s: abs(_minutes(s) - _minutes(t)))[:_NEAREST_SHOWN]
    else:
        rng = state.vague.get(SlotName.TIME)
        if isinstance(rng, TimeRange):
            free = [s for s in free if rng.start <= s <= rng.end]
        if d == now.date():
            free = [s for s in free if s > now.time()]
        params["times"] = _spread(free, _SHOWN_TIMES)
        params["available"] = bool(free)
    if not params["available"] and not params["nearest"]:
        params["next_day"] = _next_day(ctx, d, party, seating)
    return [act(ActionType.ANSWER_AVAILABILITY, **params)]


def answer_questions(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    """Answer hours / location / availability, then go back to what we were doing."""
    actions: list[ActionCall] = []
    answered: list[str] = []
    for intent in (nlu.intent, *nlu.secondary_intents):
        if intent is Intent.FAQ_HOURS:
            actions.append(act(ActionType.ANSWER_HOURS))
        elif intent is Intent.FAQ_LOCATION:
            actions.append(act(ActionType.ANSWER_LOCATION))
        elif intent is Intent.FAQ_SEATING:
            actions.append(act(ActionType.ANSWER_SEATING))
        elif intent is Intent.ASK_AVAILABILITY:
            actions.extend(_availability(state, ctx))
        else:
            continue
        answered.append(intent.value)
    reason = "answered " + ", ".join(answered)
    if state.phase in FLOW_PHASES and state.pending_question:
        actions.append(state.pending_question)
        return finish(state, actions, state.phase, reason + "; re-asked the pending question")
    if state.task is None:
        state.task = Task.ENQUIRY
    if state.phase is Phase.OFFER_BOOKING or state.phase in CLOSING_PHASES:
        actions.append(act(ActionType.ANYTHING_ELSE))
        return finish(state, actions, Phase.ANSWER_ENQUIRY, reason + "; asked if anything else")
    actions.append(act(ActionType.OFFER_BOOKING))
    return finish(state, actions, Phase.OFFER_BOOKING, reason + "; offered a booking once")


def handle_greeting(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    if nlu.intent is Intent.BOOK or booking_changes(changes):
        return start_booking(state, changes, ctx)
    if nlu.intent in (Intent.THANKS, Intent.DENY, Intent.DECLINE):
        return end_call(state, "caller did not need anything")
    return finish(state, [act(ActionType.HELP)], Phase.GREETING, "no clear request: offered help")


def handle_offer_booking(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    if polite_close(nlu) or nlu.intent in (Intent.DENY, Intent.DECLINE, Intent.THANKS):
        return end_call(state, "enquiry finished, no booking wanted")
    if nlu.intent in (Intent.AFFIRM, Intent.BOOK) or booking_changes(changes):
        return start_booking(state, changes, ctx)
    return finish(state, reprompt(state), state.phase, "unclear answer to the booking offer")


def handle_closing(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    """BOOKED, CANCELLED and ANSWER_ENQUIRY: "anything else?"."""
    if polite_close(nlu) or nlu.intent in (Intent.DENY, Intent.DECLINE, Intent.THANKS):
        return end_call(state, "nothing else needed")
    if nlu.intent is Intent.BOOK or booking_changes(changes):
        return start_booking(state, changes, ctx)
    if nlu.intent is Intent.AFFIRM:
        state.pending_question = None
        return finish(state, [act(ActionType.HELP)], Phase.GREETING, "yes to 'anything else': offered help")
    return finish(state, reprompt(state), state.phase, "unclear answer to 'anything else'")
