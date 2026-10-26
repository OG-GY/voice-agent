"""Personal data must not leak into logs, the public trace, public state or readiness."""

import io
import json
import logging
from typing import Any

from app.api.sanitize import public_turn
from app.brain import Brain
from app.observability.logging import JsonFormatter, PiiFilter, redact, reset_session, set_session

SECRETS = ("Alex", "Sample", "1001", "1 0 0 1")


def test_redaction_masks_phone_numbers_and_references() -> None:
    text = redact("call 0300 123 4567 about CP-1001 and cp 1 0 0 1")
    assert "0300" not in text and "4567" not in text and "1001" not in text
    assert "1 0 0 1" not in text


def test_the_logging_filter_redacts_even_careless_messages() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(PiiFilter())
    logger = logging.getLogger("privacy-test")
    logger.propagate = False
    logger.addHandler(handler)
    token = set_session("abc123")
    try:
        logger.error("booking for 0300 123 4567 CP-1001", extra={"fields": {"note": "ref CP-1001"}})
        try:
            raise ValueError("secret name Alex")
        except ValueError:
            logger.exception("failed")
    finally:
        reset_session(token)
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert "4567" not in output and "1001" not in output
    assert "Alex" not in output  # stack traces and exception text are dropped
    assert json.loads(output.splitlines()[0])["session_id"] == "abc123"


def full_cancel_conversation(brain: Brain) -> list[Any]:
    result = brain.start("privacy")
    results = [result]
    for line in ["cancel my booking", "CP 1 0 0 1", "Alex Sample"]:
        result = brain.handle(result.state, line)
        results.append(result)
    return results


def test_the_public_turn_masks_personal_values(brain: Brain) -> None:
    results = full_cancel_conversation(brain)
    for result in results:
        public = public_turn(result, "text", "", expose_debug=False)
        hidden = json.dumps({"trace": public.trace.model_dump(), "state": public.state.model_dump()})
        for secret in SECRETS:
            assert secret not in hidden
        assert public.trace.normalized is None
    # the reply to the caller does read the booking back: that is the conversation itself
    assert "Alex Sample" in results[-1].reply


def test_the_debug_view_adds_the_normalized_text_but_still_masks_slots(brain: Brain) -> None:
    last = full_cancel_conversation(brain)[-1]
    public = public_turn(last, "text", "Alex Sample", expose_debug=True)
    assert public.trace.normalized is not None
    assert all(e.value == "***" for e in public.trace.entities if e.type in ("name", "booking_ref"))
    assert public.state.slots["name"] in (None, "filled")
    assert public.state.slots["booking_ref"] in (None, "filled")


def test_the_reason_never_holds_a_reference(brain: Brain) -> None:
    for result in full_cancel_conversation(brain):
        assert "1001" not in public_turn(result, "text", "", False).trace.reason
