"""Booking phases: collect details, check availability, collect contact, confirm, book."""

from app.brain.policy.common import (
    BOOKING_ORDER,
    CONTACT_ORDER,
    PolicyContext,
    act,
    ask_for,
    finish,
    handoff,
    reprompt,
    stalled,
)
from app.brain.policy.validation import ValidationIssue, first_issue
from app.brain.state import DialogueState
from app.brain.types import (
    ActionCall,
    ActionType,
    DateOptions,
    Decision,
    Intent,
    NLUResult,
    Option,
    Phase,
    SlotChange,
    SlotName,
    Task,
    TimeRange,
)
from app.services.booking import BookingRequest, SlotTakenError


def _phase_for(slot: SlotName) -> Phase:
    return Phase.ASK_SEATING if slot is SlotName.SEATING else Phase.COLLECT_BOOKING


def _ack(changes: list[SlotChange], available: bool = False) -> list[ActionCall]:
    slots = [c.slot for c in changes if c.slot in BOOKING_ORDER]
    if not slots and not available:
        return []
    corrected = [c.slot for c in changes if c.slot in BOOKING_ORDER and c.old is not None]
    return [act(ActionType.ACK_SLOTS, slots=slots, corrected=corrected, available=available)]


def _ask_slot(state: DialogueState, slot: SlotName, ctx: PolicyContext) -> ActionCall:
    """Ask for a slot; a vague earlier answer ("this weekend", "evening") narrows the question."""
    vague = state.vague.get(slot)
    if slot is SlotName.DATE and isinstance(vague, DateOptions):
        today = ctx.now.date()
        days = [d for d in vague.dates if d >= today and ctx.restaurant.hours_for(d.weekday())]
        return act(ActionType.ASK_SLOT, slot=slot, options=days)
    if slot is SlotName.TIME and isinstance(vague, TimeRange):
        d, seating, now = state.value(SlotName.DATE), state.value(SlotName.SEATING), ctx.now
        free = [
            t
            for t in ctx.repo.availability_summary(d, seating, None)
            if vague.start <= t <= vague.end and (d != now.date() or t > now.time())
        ]
        state.offered_options = [
            Option(date=d, time=t, seating=seating, label=f"{t:%H:%M}")
            for t in free[: ctx.config.vague_time_options]
        ]
        return act(
            ActionType.ASK_SLOT, slot=slot, range=vague.label, options=list(state.offered_options)
        )
    return ask_for(slot)


def advance_booking(
    state: DialogueState, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    """Validate what we have, ask for what's missing, or check availability when complete."""
    state.task = Task.BOOKING
    if state.is_filled(SlotName.SEATING):
        state.suggested_seatings = []
    if issue := first_issue(state, ctx):
        if issue.code == "party_too_large":
            return handoff(state, "party_too_large", "party above the phone-booking limit")
        if issue.code == "seating_party_mismatch" and issue.params["options"]:
            return _suggest_seating(state, issue)
        state.clear_slot(issue.slot)
        actions = [
            act(ActionType.EXPLAIN_INVALID, code=issue.code, **issue.params),
            _ask_slot(state, issue.slot, ctx),
        ]
        return finish(
            state, actions, _phase_for(issue.slot), f"{issue.code}: cleared {issue.slot.value}"
        )
    missing = next((s for s in BOOKING_ORDER if not state.is_filled(s)), None)
    if missing is not None:
        if stuck := stalled(state, missing, changes, ctx):
            return stuck
        actions = [*_ack(changes), _ask_slot(state, missing, ctx)]
        return finish(state, actions, _phase_for(missing), f"{missing.value} still missing")
    seating, d, t, n = (state.value(s) for s in BOOKING_ORDER)
    if ctx.repo.check_availability(d, t, n, seating) is not None:
        state.offered_options = []
        return advance_contact(state, changes, ctx, _ack(changes, available=True))
    return _offer_alternatives(state, ctx, lost=False)


def _suggest_seating(state: DialogueState, issue: ValidationIssue) -> Decision:
    """The chosen table type can't seat this party: suggest the type(s) that can, don't re-ask."""
    state.clear_slot(SlotName.SEATING)
    state.suggested_seatings = list(issue.params["options"])
    names = ", ".join(s.value for s in state.suggested_seatings)
    reason = (
        f"{issue.params['seating'].value} can't seat {issue.params['party']}: suggested {names}"
    )
    return finish(state, [act(ActionType.SUGGEST_SEATING, **issue.params)], Phase.ASK_SEATING, reason)


def _offer_alternatives(state: DialogueState, ctx: PolicyContext, lost: bool) -> Decision:
    seating, d, t, n = (state.value(s) for s in BOOKING_ORDER)
    cfg = ctx.config
    found = ctx.repo.find_alternatives(
        d, t, n, seating, cfg.alternatives_limit, cfg.alternatives_window_minutes
    )
    found = found[: cfg.alternatives_limit + 1]  # keep it short enough to say aloud
    if found:
        state.offered_options = [
            Option(date=a.date, time=a.time, seating=a.seating, label=f"{a.seating.value} {a.time:%H:%M}")
            for a in found
        ]
        action = act(
            ActionType.OFFER_ALTERNATIVES, options=list(state.offered_options), lost=lost,
            requested_time=t, requested_seating=seating,
        )
        reason = f"{seating.value} {t:%H:%M} on {d} unavailable: offered {len(found)} alternatives"
        return finish(state, [action], Phase.OFFER_ALTERNATIVES, reason)
    next_day = ctx.repo.next_available_day(d, n, seating)
    state.clear_slot(SlotName.DATE)
    state.clear_slot(SlotName.TIME)
    actions = [
        act(ActionType.EXPLAIN_INVALID, code="fully_booked", date=d, next_day=next_day),
        ask_for(SlotName.DATE),
    ]
    return finish(state, actions, Phase.COLLECT_BOOKING, f"{d} fully booked, no alternatives")


def advance_contact(
    state: DialogueState,
    changes: list[SlotChange],
    ctx: PolicyContext,
    ack: list[ActionCall] | None = None,
) -> Decision:
    prefix = ack or []
    missing = next((s for s in CONTACT_ORDER if not state.is_filled(s)), None)
    if missing is None:
        return finish(
            state, [*prefix, act(ActionType.CONFIRM_BOOKING)], Phase.CONFIRM_BOOKING,
            "all details collected: read back for confirmation",
        )
    if stuck := stalled(state, missing, changes, ctx):
        return stuck
    return finish(
        state, [*prefix, ask_for(missing)], Phase.COLLECT_CONTACT, f"{missing.value} still missing"
    )


def start_booking(
    state: DialogueState, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    state.unsaved_warned_turn = None
    return advance_booking(state, changes, ctx)


def handle_collect(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    """ASK_SEATING, COLLECT_BOOKING and OFFER_ALTERNATIVES."""
    suggestions = state.suggested_seatings
    if suggestions and not changes and nlu.intent in (Intent.AFFIRM, Intent.DENY, Intent.DECLINE):
        if nlu.intent is Intent.AFFIRM and len(suggestions) == 1:
            state.set_slot(SlotName.SEATING, suggestions[0])
            seating_change = SlotChange(slot=SlotName.SEATING, old=None, new=suggestions[0])
            return advance_booking(state, [seating_change], ctx)
        if nlu.intent is Intent.AFFIRM:
            return finish(state, reprompt(state), state.phase, "yes to several table types: asked which")
        state.suggested_seatings = []
        return finish(
            state, [act(ActionType.ASK_WHAT_TO_CHANGE)], Phase.COLLECT_BOOKING,
            "declined the suggested table type",
        )
    if not changes and nlu.intent in (Intent.AFFIRM, Intent.DENY, Intent.DECLINE):
        if state.phase is Phase.OFFER_ALTERNATIVES and state.offered_options:
            if nlu.intent is Intent.AFFIRM:
                action = act(
                    ActionType.OFFER_ALTERNATIVES, options=list(state.offered_options),
                    lost=False, reask=True,
                )
                return finish(state, [action], state.phase, "yes to several options: asked which")
            state.offered_options = []
            return finish(
                state, [act(ActionType.ASK_WHAT_TO_CHANGE)], Phase.COLLECT_BOOKING,
                "declined the alternatives",
            )
        return finish(state, reprompt(state), state.phase, "yes/no is not an answer here")
    return advance_booking(state, changes, ctx)


def handle_contact(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    if state.needs_recheck:
        return advance_booking(state, changes, ctx)
    if (
        state.expected_slot is SlotName.PHONE
        and not changes
        and any(ch.isdigit() for ch in nlu.normalized)
    ):
        # Digits, but not a valid phone number (too short or too long): say so.
        if stuck := stalled(state, SlotName.PHONE, changes, ctx):
            return stuck
        actions = [
            act(ActionType.EXPLAIN_INVALID, code="phone_invalid"),
            ask_for(SlotName.PHONE),
        ]
        return finish(state, actions, Phase.COLLECT_CONTACT, "phone number has the wrong length")
    if not changes and nlu.intent in (Intent.AFFIRM, Intent.DENY, Intent.DECLINE):
        return finish(state, reprompt(state), state.phase, "yes/no is not an answer here")
    return advance_contact(state, changes, ctx)


def _finalize(state: DialogueState, ctx: PolicyContext) -> Decision:
    seating, d, t, n = (state.value(s) for s in BOOKING_ORDER)
    request = BookingRequest(
        date=d, time=t, party=n, seating=seating,
        name=state.value(SlotName.NAME),
        title=str(state.value(SlotName.TITLE).value),
        phone=state.value(SlotName.PHONE),
    )
    try:
        booking = ctx.repo.book(request)
    except SlotTakenError:
        return _offer_alternatives(state, ctx, lost=True)
    state.booking_ref = booking.ref
    state.clear_slots()
    state.offered_options = []
    state.task = None
    actions = [act(ActionType.BOOKING_DONE, booking=booking), act(ActionType.ANYTHING_ELSE)]
    return finish(state, actions, Phase.BOOKED, "booking created")


def handle_confirm(
    state: DialogueState, nlu: NLUResult, changes: list[SlotChange], ctx: PolicyContext
) -> Decision:
    if state.needs_recheck:
        return advance_booking(state, changes, ctx)
    if changes:
        return advance_contact(state, changes, ctx)
    if nlu.intent is Intent.AFFIRM:
        return _finalize(state, ctx)
    if nlu.intent in (Intent.DENY, Intent.DECLINE):
        return finish(
            state, [act(ActionType.ASK_WHAT_TO_CHANGE)], Phase.CONFIRM_BOOKING,
            "caller rejected the read-back: asked what to change",
        )
    return finish(state, reprompt(state), state.phase, "unclear answer to the read-back")
