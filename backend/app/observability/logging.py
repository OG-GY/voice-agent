"""Structured logs that never carry personal data.

Allowed: event name, session id, turn, phase, intent, action names, error category, timings.
Never: transcripts, replies, names, phone numbers, references, raw IPs. A filter redacts digit
runs and booking references as a last line of defense, and strips stack traces unless asked.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_LONG_DIGITS = re.compile(r"(?<![\w.])\+?\d[\d \-]{5,}\d(?!\w)")
_REFERENCE = re.compile(r"\bCP[- ]?(?:\d[ -]?){3,}\d\b", re.IGNORECASE)
_REDACTED = "[redacted]"
_HANDLER_NAME = "copper-pot"


def redact(text: str) -> str:
    """Mask phone-like digit runs and booking references."""
    return _LONG_DIGITS.sub(_REDACTED, _REFERENCE.sub(_REDACTED, text))


def set_session(session_id: str | None) -> Token[str | None]:
    return _session_id.set(session_id)


def reset_session(token: Token[str | None]) -> None:
    _session_id.reset(token)


class PiiFilter(logging.Filter):
    def __init__(self, allow_stacktraces: bool = False) -> None:
        super().__init__()
        self._allow_traces = allow_stacktraces

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            record.fields = {k: redact(v) if isinstance(v, str) else v for k, v in fields.items()}
        if not self._allow_traces:
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if (session := _session_id.get()) is not None:
            entry["session_id"] = session
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        if record.exc_info:
            entry["error_category"] = record.exc_info[0].__name__ if record.exc_info[0] else "error"
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", None)
        extra = " ".join(f"{k}={v}" for k, v in fields.items()) if isinstance(fields, dict) else ""
        session = _session_id.get()
        prefix = f"[{session}] " if session else ""
        return f"{record.levelname} {prefix}{record.getMessage()} {extra}".rstrip()


def log_event(
    logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any
) -> None:
    """One structured, non-personal event: a fixed category plus numbers and names only."""
    logger.log(level, event, extra={"fields": fields})


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    handler.addFilter(PiiFilter(settings.log_stacktraces))
    handler.set_name(_HANDLER_NAME)
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == _HANDLER_NAME:  # replace ours only; leave other handlers alone
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    # Server access logs contain client IP addresses.
    logging.getLogger("uvicorn.access").disabled = True
