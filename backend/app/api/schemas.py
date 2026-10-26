"""PUBLIC WebSocket messages. The internal Trace / DialogueState are never sent as they are."""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.api.errors import ErrorCode, ProtocolError


class PublicEntity(BaseModel):
    type: str
    value: str | None  # personal values (name, title, phone, reference) are always "***"
    confidence: float


class PublicSlotChange(BaseModel):
    slot: str
    old: str | None
    new: str | None


class PublicTrace(BaseModel):
    turn: int
    intent: str
    intent_score: float
    ranked_intents: list[tuple[str, float]]
    entities: list[PublicEntity]
    slot_changes: list[PublicSlotChange]
    phase_from: str
    phase_to: str
    actions: list[str]
    reason: str
    duration_ms: float
    normalized: str | None = None  # only with EXPOSE_DEBUG_TRACE (development)


class PublicState(BaseModel):
    phase: str
    task: str | None
    turn: int
    # Non-personal slots show their value; personal ones only "filled".
    slots: dict[str, str | None]


class PublicTurn(BaseModel):
    type: Literal["turn"] = "turn"
    turn: int
    reply: str
    ended: bool
    transcript: str
    source: Literal["greeting", "text", "audio"]
    trace: PublicTrace
    state: PublicState


class ReadyMessage(BaseModel):
    type: Literal["ready"] = "ready"
    session_id: str
    sample_rate: int
    limits: dict[str, float]


class TranscriptMessage(BaseModel):
    type: Literal["transcript"] = "transcript"
    text: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class ClosingMessage(BaseModel):
    type: Literal["closing"] = "closing"
    reason: str


@dataclass(frozen=True)
class TextMessage:
    text: str


@dataclass(frozen=True)
class SimpleMessage:
    kind: Literal["silence", "barge_in", "hangup"]


def parse_client_message(raw: str) -> TextMessage | SimpleMessage:
    try:
        data = json.loads(raw)
    except ValueError:
        raise ProtocolError(ErrorCode.BAD_JSON) from None
    if not isinstance(data, dict):
        raise ProtocolError(ErrorCode.BAD_JSON)
    kind = data.get("type")
    if kind == "text":
        text = data.get("text")
        if not isinstance(text, str):
            raise ProtocolError(ErrorCode.BAD_JSON)
        return TextMessage(text)
    if kind == "silence":
        return SimpleMessage("silence")
    if kind == "barge_in":
        return SimpleMessage("barge_in")
    if kind == "hangup":
        return SimpleMessage("hangup")
    raise ProtocolError(ErrorCode.UNKNOWN_TYPE)
