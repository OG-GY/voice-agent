"""Shared enums and models for the NLU, policy and trace."""

from datetime import date, time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.services.restaurant import Seating

__all__ = [
    "ActionCall", "ActionType", "CallEvent", "Decision", "Entity", "Intent", "NLUResult",
    "Option", "Phase", "Seating", "SlotChange", "SlotName", "SlotStatus", "Task", "TimeRange",
    "DateOptions", "Title", "Trace",
]


class Intent(StrEnum):
    BOOK = "book"
    ASK_AVAILABILITY = "ask_availability"
    CANCEL_BOOKING = "cancel_booking"
    INFORM = "inform"
    AFFIRM = "affirm"
    DENY = "deny"
    DECLINE = "decline"
    CORRECT = "correct"
    FAQ_HOURS = "faq_hours"
    FAQ_LOCATION = "faq_location"
    FAQ_SEATING = "faq_seating"
    REPEAT = "repeat"
    HELP = "help"
    RESTART = "restart"
    ASK_HUMAN = "ask_human"
    HOLD = "hold"
    GOODBYE = "goodbye"
    THANKS = "thanks"
    OUT_OF_SCOPE = "out_of_scope"
    NOMATCH = "nomatch"


class Phase(StrEnum):
    GREETING = "greeting"
    ASK_SEATING = "ask_seating"
    COLLECT_BOOKING = "collect_booking"
    CHECK_AVAILABILITY = "check_availability"
    OFFER_ALTERNATIVES = "offer_alternatives"
    COLLECT_CONTACT = "collect_contact"
    CONFIRM_BOOKING = "confirm_booking"
    BOOKED = "booked"
    COLLECT_REF = "collect_ref"
    COLLECT_CANCEL_NAME = "collect_cancel_name"
    CONFIRM_CANCEL = "confirm_cancel"
    CANCELLED = "cancelled"
    ANSWER_ENQUIRY = "answer_enquiry"
    OFFER_BOOKING = "offer_booking"
    HANDOFF = "handoff"
    END = "end"


class Task(StrEnum):
    BOOKING = "booking"
    CANCEL = "cancel"
    ENQUIRY = "enquiry"


class Title(StrEnum):
    MR = "mr"
    MRS = "mrs"
    MS = "ms"
    MISS = "miss"
    MX = "mx"
    NONE = "none"


class SlotName(StrEnum):
    SEATING = "seating"
    DATE = "date"
    TIME = "time"
    PARTY_SIZE = "party_size"
    NAME = "name"
    TITLE = "title"
    PHONE = "phone"
    BOOKING_REF = "booking_ref"


class SlotStatus(StrEnum):
    EMPTY = "empty"
    FILLED = "filled"
    CONFIRMED = "confirmed"


class CallEvent(StrEnum):
    SILENCE = "silence"
    HANGUP = "hangup"


class ActionType(StrEnum):
    GREET = "greet"
    ASK_SLOT = "ask_slot"
    ASK_SEATING = "ask_seating"
    SUGGEST_SEATING = "suggest_seating"
    ASK_TITLE = "ask_title"
    ANSWER_HOURS = "answer_hours"
    ANSWER_LOCATION = "answer_location"
    ANSWER_SEATING = "answer_seating"
    ANSWER_AVAILABILITY = "answer_availability"
    OFFER_BOOKING = "offer_booking"
    OFFER_ALTERNATIVES = "offer_alternatives"
    EXPLAIN_INVALID = "explain_invalid"
    ACK_SLOTS = "ack_slots"
    CONFIRM_BOOKING = "confirm_booking"
    BOOKING_DONE = "booking_done"
    ASK_WHAT_TO_CHANGE = "ask_what_to_change"
    ASK_REF = "ask_ref"
    VERIFICATION_FAILED = "verification_failed"
    SYSTEM_UNAVAILABLE = "system_unavailable"
    TRY_LATER = "try_later"
    CONFIRM_CANCEL = "confirm_cancel"
    CANCEL_DONE = "cancel_done"
    DECLINE_OUT_OF_SCOPE = "decline_out_of_scope"
    REPROMPT = "reprompt"
    REPEAT_LAST = "repeat_last"
    HELP = "help"
    HOLD_ACK = "hold_ack"
    WARN_UNSAVED = "warn_unsaved"
    CONFIRM_TASK_SWITCH = "confirm_task_switch"
    CHECK_PRESENCE = "check_presence"
    APOLOGIZE_TITLE = "apologize_title"
    CONFIRM_FUZZY = "confirm_fuzzy"
    ANYTHING_ELSE = "anything_else"
    HANDOFF = "handoff"
    GOODBYE = "goodbye"


class TimeRange(BaseModel):
    start: time
    end: time
    label: str


class DateOptions(BaseModel):
    dates: list[date]
    label: str


class Entity(BaseModel):
    type: SlotName
    value: Any
    span: tuple[int, int]
    text: str
    confidence: float


class NLUResult(BaseModel):
    raw: str
    normalized: str
    intent: Intent
    intent_score: float
    secondary_intents: list[Intent] = Field(default_factory=list)
    ranked: list[tuple[Intent, float]] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    fuzzy_fixes: list[tuple[str, str, int]] = Field(default_factory=list)
    is_noise: bool = False


class Option(BaseModel):
    """A choice we offered the caller ("the second one" resolves against these)."""

    date: date
    time: time
    seating: Seating
    label: str


class SlotChange(BaseModel):
    slot: SlotName
    old: Any = None
    new: Any = None


class ActionCall(BaseModel):
    type: ActionType
    params: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    actions: list[ActionCall]
    next_phase: Phase
    reason: str


class Trace(BaseModel):
    turn: int
    transcript: str
    normalized: str
    intent: Intent
    intent_score: float
    ranked_intents: list[tuple[Intent, float]]
    entities: list[Entity]
    fuzzy_fixes: list[tuple[str, str, int]]
    slot_changes: list[SlotChange]
    phase_from: Phase
    phase_to: Phase
    actions: list[ActionCall]
    reason: str
    honorific: str | None
    reply: str
    duration_ms: float
