"""Error codes and WebSocket close codes in one place. Messages are fixed, generic strings."""

from enum import IntEnum, StrEnum


class ErrorCode(StrEnum):
    BAD_JSON = "bad_json"
    UNKNOWN_TYPE = "unknown_type"
    TEXT_TOO_LONG = "text_too_long"
    AUDIO_TOO_LONG = "audio_too_long"
    AUDIO_INVALID = "audio_invalid"
    STT_UNAVAILABLE = "stt_unavailable"
    STT_BUSY = "stt_busy"
    STT_TIMEOUT = "stt_timeout"
    RATE_LIMITED = "rate_limited"
    SERVICE_UNAVAILABLE = "service_unavailable"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.BAD_JSON: "The message could not be understood.",
    ErrorCode.UNKNOWN_TYPE: "Unknown message type.",
    ErrorCode.TEXT_TOO_LONG: "That message is too long.",
    ErrorCode.AUDIO_TOO_LONG: "That recording is too long.",
    ErrorCode.AUDIO_INVALID: "The audio could not be used.",
    ErrorCode.STT_UNAVAILABLE: "Speech recognition is not available right now.",
    ErrorCode.STT_BUSY: "Speech recognition is busy. Please try again.",
    ErrorCode.STT_TIMEOUT: "Speech recognition took too long. Please try again.",
    ErrorCode.RATE_LIMITED: "You are sending messages too quickly.",
    ErrorCode.SERVICE_UNAVAILABLE: "Something went wrong. Please try again.",
}


class CloseCode(IntEnum):
    NORMAL = 1000
    GOING_AWAY = 1001
    POLICY = 1008
    TOO_BIG = 1009
    INTERNAL = 1011
    TRY_LATER = 1013


class ProtocolError(Exception):
    """A client message that cannot be accepted."""

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code
