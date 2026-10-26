"""sir / ma'am, only once the caller's title is known (never guessed from voice or name)."""

from app.brain.config import BrainConfig
from app.brain.state import DialogueState
from app.brain.types import SlotName, Title

_ABBREVIATIONS = {
    Title.MR: "Mr.", Title.MRS: "Mrs.", Title.MS: "Ms.", Title.MISS: "Miss", Title.MX: "Mx.",
}


def honorific_word(state: DialogueState) -> str | None:
    if state.caller_title is Title.MR:
        return "sir"
    if state.caller_title in (Title.MRS, Title.MS, Title.MISS):
        return "ma'am"
    return None


def hon(state: DialogueState, config: BrainConfig, force: bool = False) -> str:
    """", sir" / ", ma'am" / "". Without `force`, at most once every few turns."""
    word = honorific_word(state)
    if word is None:
        return ""
    last = state.honorific_last_turn
    if not force and last is not None and state.turn - last < config.honorific_every:
        return ""
    state.honorific_last_turn = state.turn
    return f", {word}"


def full_name(state: DialogueState) -> str:
    """"Mr. Khan" for the read-back, or just "Khan" when no title."""
    name = state.value(SlotName.NAME) or ""
    title = _ABBREVIATIONS.get(state.caller_title) if state.caller_title else None
    return f"{title} {name}" if title else str(name)
