"""State tracker: apply an NLU result to the dialogue state (slots, corrections, counters).

The engine passes a copy of the state with `turn` already advanced; this mutates it in place.
"""

from typing import Any

from app.brain.state import DialogueState
from app.brain.types import (
    DateOptions,
    Intent,
    NLUResult,
    Option,
    Phase,
    SlotChange,
    SlotName,
    TimeRange,
)

# Changing these after the table was checked means availability must be re-checked.
_RECHECK_SLOTS = {SlotName.SEATING, SlotName.DATE, SlotName.TIME, SlotName.PARTY_SIZE}
_RECHECK_PHASES = {Phase.COLLECT_CONTACT, Phase.CONFIRM_BOOKING}
_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "last": -1, "latter": -1,
}
_PICK_INTENTS = {Intent.AFFIRM, Intent.INFORM, Intent.CORRECT}
# An explicit date/time/seating in the same breath beats "the second one".
_BLOCKS_PICK = {SlotName.DATE, SlotName.TIME, SlotName.SEATING}


def _update_counters(state: DialogueState, nlu: NLUResult) -> None:
    intent = nlu.intent
    state.nomatch_count = state.nomatch_count + 1 if intent is Intent.NOMATCH else 0
    state.out_of_scope_count = state.out_of_scope_count + 1 if intent is Intent.OUT_OF_SCOPE else 0
    if nlu.is_noise:
        return  # nothing was really said, so the silence and hold state stay as they were
    state.silence_count = 0
    state.hold_mode = intent is Intent.HOLD


def _apply_value(
    state: DialogueState, slot: SlotName, value: Any, changes: list[SlotChange]
) -> None:
    if isinstance(value, DateOptions | TimeRange):
        state.vague[slot] = value
        return
    old = state.value(slot) if state.is_filled(slot) else None
    if old == value:
        return
    state.set_slot(slot, value)
    state.slots[slot].attempts = 0
    state.vague.pop(slot, None)
    changes.append(SlotChange(slot=slot, old=old, new=value))
    if state.phase in _RECHECK_PHASES and slot in _RECHECK_SLOTS:
        state.needs_recheck = True
    if slot is SlotName.TITLE:
        state.caller_title = value
        state.title_corrected = old is not None


def _pick_option(state: DialogueState, nlu: NLUResult) -> Option | None:
    """Resolve "the first one" / "the last one" / a lone "yes" against what we offered."""
    options = state.offered_options
    if not options or nlu.intent not in _PICK_INTENTS:
        return None
    if any(e.type in _BLOCKS_PICK for e in nlu.entities):
        return None
    for token in nlu.normalized.split():
        index = _ORDINALS.get(token)
        if index is not None:
            return options[index] if -len(options) <= index < len(options) else None
    if len(options) == 1 and nlu.intent is Intent.AFFIRM:
        return options[0]
    return None


def apply_nlu(state: DialogueState, nlu: NLUResult) -> list[SlotChange]:
    """Update slots and counters; return every slot that was filled or changed."""
    state.needs_recheck = False
    state.title_corrected = False
    changes: list[SlotChange] = []
    _update_counters(state, nlu)
    for entity in nlu.entities:
        if nlu.intent is Intent.FAQ_SEATING and entity.type is SlotName.SEATING:
            continue  # "what is a window table?" is a question, not a choice
        _apply_value(state, entity.type, entity.value, changes)
    if state.phase is Phase.OFFER_ALTERNATIVES and (option := _pick_option(state, nlu)):
        _apply_value(state, SlotName.SEATING, option.seating, changes)
        _apply_value(state, SlotName.DATE, option.date, changes)
        _apply_value(state, SlotName.TIME, option.time, changes)
        state.offered_options = []
    return changes
