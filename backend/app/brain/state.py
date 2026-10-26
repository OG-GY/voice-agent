"""Serializable dialogue state kept per call."""

from typing import Any

from pydantic import BaseModel, Field

from app.brain.types import (
    ActionCall,
    Option,
    Phase,
    Seating,
    SlotName,
    SlotStatus,
    Task,
    Title,
    Trace,
)


class Slot(BaseModel):
    value: Any = None
    status: SlotStatus = SlotStatus.EMPTY
    turn_set: int | None = None
    attempts: int = 0


def _empty_slots() -> dict[SlotName, Slot]:
    return {name: Slot() for name in SlotName}


class DialogueState(BaseModel):
    session_id: str
    turn: int = 0
    phase: Phase = Phase.GREETING
    task: Task | None = None
    slots: dict[SlotName, Slot] = Field(default_factory=_empty_slots)
    expected_slot: SlotName | None = None
    # Vague answers ("this weekend", "evening") waiting to be narrowed down by the caller.
    vague: dict[SlotName, Any] = Field(default_factory=dict)
    offered_options: list[Option] = Field(default_factory=list)
    # Table types we suggested because the caller's choice can't seat their party.
    suggested_seatings: list[Seating] = Field(default_factory=list)
    pending_question: ActionCall | None = None
    nomatch_count: int = 0
    out_of_scope_count: int = 0
    silence_count: int = 0
    hold_mode: bool = False
    honorific_last_turn: int | None = None
    last_reply: str = ""
    last_reply_interrupted: bool = False
    caller_title: Title | None = None  # outlives the slots: "sir"/"ma'am" lasts the whole call
    pending_switch: Task | None = None
    unsaved_warned_turn: int | None = None
    caller_key: str = "local"  # opaque id of the caller (hashed IP, set by the API)
    verify_failures: int = 0
    needs_recheck: bool = False
    title_corrected: bool = False
    booking_ref: str | None = None
    ended: bool = False

    def value(self, name: SlotName) -> Any:
        return self.slots[name].value

    def is_filled(self, name: SlotName) -> bool:
        return self.slots[name].status != SlotStatus.EMPTY

    def set_slot(self, name: SlotName, value: Any) -> None:
        slot = self.slots[name]
        slot.value = value
        slot.status = SlotStatus.FILLED
        slot.turn_set = self.turn

    def clear_slot(self, name: SlotName) -> None:
        self.slots[name] = Slot()
        self.vague.pop(name, None)

    def clear_slots(self) -> None:
        self.slots = _empty_slots()
        self.vague = {}


class TurnResult(BaseModel):
    state: DialogueState
    reply: str
    trace: Trace
    ended: bool
