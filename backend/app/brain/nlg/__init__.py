"""NLG: turn a Decision into short, speakable sentences."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.brain.config import BrainConfig
from app.brain.nlg.formatters import (
    join_or,
    say_closed_days,
    say_date,
    say_number,
    say_on,
    say_open_days,
    say_options,
    say_party,
    say_phone,
    say_range,
    say_ref,
    say_seating,
    say_time,
    say_weekday,
)
from app.brain.nlg.honorifics import full_name, hon
from app.brain.nlg.templates import T
from app.brain.state import DialogueState
from app.brain.types import ActionCall, ActionType, Decision, Seating, SlotName
from app.services.booking import Booking
from app.services.restaurant import RestaurantConfig


@dataclass
class _Ctx:
    state: DialogueState
    restaurant: RestaurantConfig
    config: BrainConfig
    today: date


class _Fields(dict[str, Any]):
    """Template fields; {hon} / {HON} are only computed (and counted) when a template uses them."""

    def __init__(self, base: dict[str, Any], rc: _Ctx) -> None:
        super().__init__(base)
        self._rc = rc

    def __missing__(self, key: str) -> str:
        rc = self._rc
        if key == "hon":
            value = hon(rc.state, rc.config)
        elif key == "HON":
            value = hon(rc.state, rc.config, force=True)
        elif key == "restaurant":
            value = rc.restaurant.name
        else:
            raise KeyError(key)
        self[key] = value
        return value


def _say(rc: _Ctx, text: str, **fields: Any) -> str:
    return text.format_map(_Fields(fields, rc))


def _variant(rc: _Ctx, key: str, **fields: Any) -> str:
    variants = T[key]
    return _say(rc, variants[rc.state.turn % len(variants)], **fields)


def _describe(booking: Booking, rc: _Ctx) -> str:
    return (
        f"{say_seating(booking.seating)} {say_on(booking.date, rc.today)} "
        f"at {say_time(booking.time)} for {say_party(booking.party)}"
    )


# -- asking ---------------------------------------------------------------------------


def _ask_slot(a: ActionCall, rc: _Ctx) -> str:
    slot, options = a.params["slot"], a.params.get("options")
    if slot is SlotName.DATE:
        if options:
            return _variant(rc, "ask_date_options", options=join_or([say_weekday(d) for d in options]))
        return _variant(rc, "ask_date")
    if slot is SlotName.TIME:
        label = a.params.get("range")
        if label and options:
            times = join_or([say_time(o.time) for o in options])
            return _variant(rc, "ask_time_range", range=say_range(label), times=times)
        if label:
            return _variant(rc, "ask_time_range_none", range=say_range(label))
        return _variant(rc, "ask_time")
    keys = {SlotName.PARTY_SIZE: "ask_party", SlotName.NAME: "ask_name", SlotName.PHONE: "ask_phone"}
    if slot is SlotName.NAME and a.params.get("for_cancel"):
        return _variant(rc, "ask_cancel_name")
    return _variant(rc, keys[slot])


def _ask_seating(a: ActionCall, rc: _Ctx) -> str:
    retry = rc.state.slots[SlotName.SEATING].attempts > 0
    return _variant(rc, "ask_seating_short" if retry else "ask_seating_full")


def _suggest_what(seating: Seating, rc: _Ctx) -> str:
    if seating is Seating.PRIVATE:
        top = max(t.seats for t in rc.restaurant.tables_in(seating))
        return (
            "our private area, where your group gets its own space "
            f"with room for up to {say_number(top)}"
        )
    return say_seating(seating)


def _suggest_seating(a: ActionCall, rc: _Ctx) -> str:
    p = a.params
    key = "suggest_min" if p["reason"] == "min" else "suggest_max"
    base = _variant(rc, key, seat=p["seating"].value, limit=p["limit"])
    options = [_suggest_what(c, rc) for c in p["options"]]
    tail = "suggest_one" if len(options) == 1 else "suggest_many"
    return base + _variant(rc, tail, party=say_party(p["party"]), what=join_or(options))


def _ack(a: ActionCall, rc: _Ctx) -> str:
    st, slots = rc.state, a.params["slots"]
    parts: list[str] = []
    if SlotName.SEATING in slots and st.is_filled(SlotName.SEATING):
        parts.append(say_seating(st.value(SlotName.SEATING)))
    if SlotName.DATE in slots and st.is_filled(SlotName.DATE):
        parts.append(say_on(st.value(SlotName.DATE), rc.today))
    if SlotName.TIME in slots and st.is_filled(SlotName.TIME):
        parts.append(f"at {say_time(st.value(SlotName.TIME))}")
    if SlotName.PARTY_SIZE in slots and st.is_filled(SlotName.PARTY_SIZE):
        parts.append(f"for {say_party(st.value(SlotName.PARTY_SIZE))}")
    available = _variant(rc, "available") if a.params["available"] else ""
    if not parts:
        return available
    lead = _variant(rc, "ack_corrected" if a.params["corrected"] else "ack_lead")
    return f"{lead}{' '.join(parts)}. {available}".strip()


def _confirm_booking(a: ActionCall, rc: _Ctx) -> str:
    st = rc.state
    what = (
        f"{say_seating(st.value(SlotName.SEATING))} "
        f"{say_on(st.value(SlotName.DATE), rc.today)} at {say_time(st.value(SlotName.TIME))} "
        f"for {say_party(st.value(SlotName.PARTY_SIZE))}"
    )
    return _variant(
        rc, "confirm_booking", what=what, who=full_name(st),
        phone=say_phone(st.value(SlotName.PHONE)),
    )


# -- explaining -----------------------------------------------------------------------


def _explain(a: ActionCall, rc: _Ctx) -> str:  # noqa: PLR0911
    p, code = a.params, a.params["code"]
    if code == "date_past":
        return _say(rc, "Sorry{hon}, that date has already passed.")
    if code == "date_too_far":
        return f"We take bookings up to {p['days']} days ahead."
    if code == "closed_day":
        nearest = join_or([say_weekday(d) for d in p["options"]])
        tail = f" The nearest open days are {nearest}." if nearest else ""
        return _say(rc, "Sorry{hon}, we're closed on {day}s.", day=say_weekday(p["date"])) + tail
    if code == "time_outside_hours":
        return f"We take bookings from {say_time(p['open'])} until {say_time(p['last'])}."
    if code == "time_off_slot":
        return f"We book in half-hour slots, for example {join_or([say_time(t) for t in p['options']])}."
    if code == "time_passed":
        later = f" The next slot is {say_time(p['suggestion'])}." if p["suggestion"] else ""
        return "That time has already passed today." + later
    if code == "party_invalid":
        return "Sorry, I didn't catch a valid number of guests."
    if code == "phone_invalid":
        return "That phone number doesn't look right: I need 10 or 11 digits."
    if code == "seating_party_mismatch":
        seat, limit = p["seating"].value, p["limit"]
        base = (
            f"Our {seat} tables are for parties of {limit} or more."
            if p["reason"] == "min"
            else f"Our {seat} tables seat up to {limit}."
        )
        options = join_or([say_seating(c) for c in p["options"]])
        offer = f" For {say_party(p['party'])} I can offer {options}." if options else ""
        return base + offer
    if code == "fully_booked":
        text = f"Unfortunately we're fully booked {say_on(p['date'], rc.today)}."
        if p["next_day"]:
            text += f" The next day with space is {say_date(p['next_day'], rc.today)}."
        return text
    return "Sorry, that doesn't work."


def _offer_alternatives(a: ActionCall, rc: _Ctx) -> str:
    spoken = say_options(a.params["options"])
    if a.params.get("reask"):
        return _variant(rc, "offer_reask", options=spoken)
    if a.params["lost"]:
        lead = _variant(rc, "offer_lost")
    else:
        lead = _variant(
            rc, "offer_lead", seating=say_seating(a.params["requested_seating"]),
            time=say_time(a.params["requested_time"]),
        )
    key = "offer_one" if len(a.params["options"]) == 1 else "offer_many"
    return lead + _variant(rc, key, options=spoken)


# -- enquiries ------------------------------------------------------------------------


def _answer_seating(a: ActionCall, rc: _Ctx) -> str:
    """Explain the three table types, using the real table sizes."""
    r = rc.restaurant

    def sizes(seating: Seating) -> tuple[str, str]:
        tables = r.tables_in(seating)
        return say_number(min(t.min_party for t in tables)), say_number(max(t.seats for t in tables))

    _, regular_top = sizes(Seating.GENERAL)
    _, window_top = sizes(Seating.WINDOW)
    private_low, private_top = sizes(Seating.PRIVATE)
    return (
        "We have three kinds of tables. "
        f"A regular table is in our main dining room and seats up to {regular_top}. "
        f"A window table is by the street window, with a view, and seats up to {window_top}. "
        f"A private family table is a quieter area of its own, for groups of {private_low} to {private_top}."
    )


def _answer_hours(a: ActionCall, rc: _Ctx) -> str:
    r = rc.restaurant
    opens, closes = next(h for h in r.opening_hours.values() if h)
    return (
        f"We're open {say_open_days(r)}, from {say_time(opens)} to {say_time(closes)}, "
        f"with last seating at {say_time(r.last_seating)}. We're closed on {say_closed_days(r)}."
    )


def _answer_availability(a: ActionCall, rc: _Ctx) -> str:
    p = a.params
    what = say_seating(p["seating"]) if p["seating"] else "a table"
    if p["party"]:
        what += f" for {say_party(p['party'])}"
    day = "today" if p["assumed_today"] else say_on(p["date"], rc.today)
    if p["time"] is not None:
        at = say_time(p["time"])
        if p["available"]:
            return f"Yes, we have {what} {day} at {at}."
        text = f"Sorry, we don't have {what} {day} at {at}."
        if p["nearest"]:
            text += f" The closest free times are {join_or([say_time(t) for t in p['nearest']])}."
    elif p["available"]:
        return f"{day.capitalize()}, I have {what} free at {join_or([say_time(t) for t in p['times']])}."
    else:
        text = f"I'm afraid we're fully booked {day}."
    if p["next_day"]:
        text += f" The next day with space is {say_date(p['next_day'], rc.today)}."
    return text


# -- finishing ------------------------------------------------------------------------


def _booking_done(a: ActionCall, rc: _Ctx) -> str:
    b: Booking = a.params["booking"]
    return _variant(rc, "booking_done", what=_describe(b, rc), ref=say_ref(b.ref))


def _confirm_cancel(a: ActionCall, rc: _Ctx) -> str:
    b: Booking = a.params["booking"]
    return _variant(rc, "cancel_confirm", ref=say_ref(b.ref), what=_describe(b, rc), who=b.name)


def _cancel_done(a: ActionCall, rc: _Ctx) -> str:
    b: Booking = a.params["booking"]
    if a.params.get("already"):
        return _variant(rc, "cancel_already", ref=say_ref(b.ref))
    return _variant(rc, "cancel_done", ref=say_ref(b.ref), what=_describe(b, rc))


def _handoff(a: ActionCall, rc: _Ctx) -> str:
    key = {
        "human": "handoff_human", "party_too_large": "handoff_party",
        "too_many_failures": "handoff_failures", "out_of_scope": "handoff_scope",
        "verification_failed": "handoff_verification",
    }[a.params["reason"]]
    return _variant(rc, key, max=rc.restaurant.max_party)


def _simple(key: str) -> Callable[[ActionCall, _Ctx], str]:
    return lambda a, rc: _variant(rc, key)


RENDERERS: dict[ActionType, Callable[[ActionCall, _Ctx], str]] = {
    ActionType.GREET: lambda a, rc: _variant(rc, "greet_restart" if a.params.get("restarted") else "greet"),
    ActionType.ASK_SLOT: _ask_slot,
    ActionType.ASK_SEATING: _ask_seating,
    ActionType.SUGGEST_SEATING: _suggest_seating,
    ActionType.ASK_TITLE: lambda a, rc: _variant(rc, "ask_title", name=rc.state.value(SlotName.NAME)),
    ActionType.ASK_REF: _simple("ask_ref"),
    ActionType.ACK_SLOTS: _ack,
    ActionType.EXPLAIN_INVALID: _explain,
    ActionType.OFFER_ALTERNATIVES: _offer_alternatives,
    ActionType.CONFIRM_BOOKING: _confirm_booking,
    ActionType.BOOKING_DONE: _booking_done,
    ActionType.CONFIRM_CANCEL: _confirm_cancel,
    ActionType.CANCEL_DONE: _cancel_done,
    ActionType.VERIFICATION_FAILED: _simple("verification_failed"),
    ActionType.SYSTEM_UNAVAILABLE: _simple("unavailable"),
    ActionType.TRY_LATER: _simple("try_later"),
    ActionType.ANSWER_HOURS: _answer_hours,
    ActionType.ANSWER_LOCATION: lambda a, rc: f"We're at {rc.restaurant.address}.",
    ActionType.ANSWER_SEATING: _answer_seating,
    ActionType.ANSWER_AVAILABILITY: _answer_availability,
    ActionType.OFFER_BOOKING: _simple("offer_booking"),
    ActionType.ANYTHING_ELSE: lambda a, rc: (
        _variant(rc, "kept") + " " if a.params.get("kept") else ""
    ) + _variant(rc, "anything_else"),
    ActionType.ASK_WHAT_TO_CHANGE: _simple("ask_change"),
    ActionType.DECLINE_OUT_OF_SCOPE: _simple("out_of_scope"),
    ActionType.REPROMPT: lambda a, rc: T["reprompt"][min(max(rc.state.nomatch_count - 1, 0), len(T["reprompt"]) - 1)],
    ActionType.REPEAT_LAST: lambda a, rc: rc.state.last_reply or "I haven't said anything yet.",
    ActionType.HELP: _simple("help"),
    ActionType.HOLD_ACK: _simple("hold"),
    ActionType.WARN_UNSAVED: _simple("warn_unsaved"),
    ActionType.CONFIRM_TASK_SWITCH: _simple("switch"),
    ActionType.CHECK_PRESENCE: _simple("presence"),
    ActionType.HANDOFF: _handoff,
    ActionType.GOODBYE: _simple("goodbye"),
}


def render(
    decision: Decision,
    state: DialogueState,
    restaurant: RestaurantConfig,
    config: BrainConfig,
    today: date,
) -> str:
    rc = _Ctx(state, restaurant, config, today)
    parts: list[str] = []
    if state.title_corrected:
        parts.append(_variant(rc, "apology"))
    for action in decision.actions:
        renderer = RENDERERS.get(action.type)
        text = renderer(action, rc) if renderer else _variant(rc, "fallback")
        if text:
            parts.append(text)
    return " ".join(parts)
