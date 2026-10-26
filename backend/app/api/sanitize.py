"""Internal Trace / DialogueState -> public models. Personal data is masked, never copied over."""

from datetime import date, time
from enum import Enum
from typing import Any, Literal

from app.api.schemas import (
    PublicEntity,
    PublicSlotChange,
    PublicState,
    PublicTrace,
    PublicTurn,
)
from app.brain.state import DialogueState, TurnResult
from app.brain.types import DateOptions, Entity, SlotChange, SlotName, TimeRange, Trace
from app.observability.logging import redact

_NON_PERSONAL = frozenset({SlotName.SEATING, SlotName.DATE, SlotName.TIME, SlotName.PARTY_SIZE})
_MASK = "***"


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, TimeRange | DateOptions):
        return value.label
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


def public_entity(entity: Entity) -> PublicEntity:
    shown = _scalar(entity.value) if entity.type in _NON_PERSONAL else _MASK
    return PublicEntity(type=entity.type.value, value=shown, confidence=entity.confidence)


def public_change(change: SlotChange) -> PublicSlotChange:
    if change.slot in _NON_PERSONAL:
        return PublicSlotChange(slot=change.slot.value, old=_scalar(change.old), new=_scalar(change.new))
    return PublicSlotChange(
        slot=change.slot.value, old=None if change.old is None else _MASK, new=_MASK
    )


def public_trace(trace: Trace, expose_debug: bool) -> PublicTrace:
    return PublicTrace(
        turn=trace.turn,
        intent=trace.intent.value,
        intent_score=trace.intent_score,
        ranked_intents=[(i.value, s) for i, s in trace.ranked_intents],
        entities=[public_entity(e) for e in trace.entities],
        slot_changes=[public_change(c) for c in trace.slot_changes],
        phase_from=trace.phase_from.value,
        phase_to=trace.phase_to.value,
        actions=[a.type.value for a in trace.actions],
        reason=redact(trace.reason),
        duration_ms=trace.duration_ms,
        normalized=trace.normalized if expose_debug else None,
    )


def public_state(state: DialogueState) -> PublicState:
    slots: dict[str, str | None] = {}
    for name in SlotName:
        if not state.is_filled(name):
            slots[name.value] = None
        elif name in _NON_PERSONAL:
            slots[name.value] = _scalar(state.value(name))
        else:
            slots[name.value] = "filled"
    return PublicState(
        phase=state.phase.value,
        task=state.task.value if state.task else None,
        turn=state.turn,
        slots=slots,
    )


def public_turn(
    result: TurnResult,
    source: Literal["greeting", "text", "audio"],
    transcript: str,
    expose_debug: bool,
) -> PublicTurn:
    return PublicTurn(
        turn=result.trace.turn,
        reply=result.reply,
        ended=result.ended,
        transcript=transcript,
        source=source,
        trace=public_trace(result.trace, expose_debug),
        state=public_state(result.state),
    )
