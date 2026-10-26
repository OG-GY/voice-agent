"""The /ws/call WebSocket, /health and /ready, through the real app with fakes behind it."""

import json
import logging
from collections.abc import Callable
from typing import Any

import pytest
from helpers import FakeStt, FlakyRepository
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.restaurant import DEFAULT_RESTAURANT
from app.services.seed import seeded_repository

AUDIO_1S = b"\x01\x00" * 16000


def start(ws: Any) -> dict[str, Any]:
    """Skip `ready`, return the greeting turn."""
    assert ws.receive_json()["type"] == "ready"
    return ws.receive_json()  # type: ignore[no-any-return]


def say(ws: Any, text: str) -> dict[str, Any]:
    ws.send_json({"type": "text", "text": text})
    return ws.receive_json()  # type: ignore[no-any-return]


def test_ready_then_greeting(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["sample_rate"] == 16000
        greeting = ws.receive_json()
        assert greeting["source"] == "greeting" and "Copper Pot" in greeting["reply"]


def test_a_text_turn_gets_a_reply_and_a_sanitized_trace(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        turn = say(ws, "what are your timings")
        assert turn["type"] == "turn" and "open" in turn["reply"].lower()
        assert turn["trace"]["intent"] == "faq_hours"
        assert turn["trace"]["normalized"] is None  # debug view is off by default


def test_malformed_and_unknown_messages_get_errors_and_the_call_goes_on(
    app_factory: Callable[..., Any],
) -> None:
    app, _ = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        ws.send_text("{")
        assert ws.receive_json()["code"] == "bad_json"
        ws.send_json({"type": "nope"})
        assert ws.receive_json()["code"] == "unknown_type"
        ws.send_json({"type": "text", "text": 5})
        assert ws.receive_json()["code"] == "bad_json"
        assert say(ws, "hello")["type"] == "turn"


def test_long_text_is_refused(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        assert say(ws, "x" * 600)["code"] == "text_too_long"  # over MAX_TEXT_CHARS
        ws.send_text("x" * 5000)  # over the frame cap
        assert ws.receive_json()["code"] == "text_too_long"


def test_audio_is_refused_when_speech_is_off(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        ws.send_bytes(AUDIO_1S)
        assert ws.receive_json()["code"] == "stt_unavailable"
        ws.send_bytes(b"\x01")  # odd length cannot be PCM16
        assert ws.receive_json()["code"] == "audio_invalid"
        ws.send_bytes(b"\x00\x00" * (16000 * 31))
        assert ws.receive_json()["code"] == "audio_too_long"


def test_audio_is_transcribed_then_answered(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(stt_enabled=True, stt_factory=lambda: FakeStt("what are your timings"))
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        ws.send_bytes(AUDIO_1S)
        transcript = ws.receive_json()
        assert transcript == {"type": "transcript", "text": "what are your timings"}
        turn = ws.receive_json()
        assert turn["source"] == "audio" and "open" in turn["reply"].lower()


def test_a_very_short_clip_is_treated_as_not_understood(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(stt_enabled=True, stt_factory=lambda: FakeStt())
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        ws.send_bytes(b"\x01\x00" * 100)  # 6 ms
        assert "catch" in ws.receive_json()["reply"].lower()


def test_hangup_ends_the_call_with_a_normal_close(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        ws.send_json({"type": "hangup"})
        assert ws.receive_json()["ended"] is True
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1000


def test_a_forbidden_origin_is_refused(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            client.websocket_connect("/ws/call", headers={"origin": "http://evil.example"}),
        ):
            pass
        assert closed.value.code == 1008
        with client.websocket_connect("/ws/call", headers={"origin": "http://localhost:3000"}) as ws:
            assert ws.receive_json()["type"] == "ready"


def test_the_call_limit_closes_with_try_again_later(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(max_concurrent_calls=1)
    with TestClient(app) as client, client.websocket_connect("/ws/call") as first:
        start(first)
        with client.websocket_connect("/ws/call") as second:
            with pytest.raises(WebSocketDisconnect) as closed:
                second.receive_json()
            assert closed.value.code == 1013


def test_too_many_messages_get_rate_limited(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(messages_per_10s=3)
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        # An understood question each time: three "not understood" in a row would end the call.
        replies = [say(ws, "what are your timings") for _ in range(6)]
        assert [r["type"] for r in replies].count("turn") == 3
        assert all(r["code"] == "rate_limited" for r in replies if r["type"] == "error")


def test_repeated_invalid_messages_close_the_connection(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(invalid_before_close=2)
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        for _ in range(2):
            ws.send_text("{")
            assert ws.receive_json()["code"] == "bad_json"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008


def test_a_silent_caller_is_asked_if_they_are_still_there(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(idle_timeout_seconds=0.3)
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        turn = ws.receive_json()  # sent by the server when nothing arrives
        assert "still there" in turn["reply"]


def test_shutdown_warns_active_calls_and_refuses_new_ones(app_factory: Callable[..., Any]) -> None:
    app, container = app_factory()
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        container.begin_shutdown()
        assert ws.receive_json() == {"type": "closing", "reason": "restart"}
        with client.websocket_connect("/ws/call") as late:
            with pytest.raises(WebSocketDisconnect) as closed:
                late.receive_json()
            assert closed.value.code == 1013
        assert client.get("/ready").status_code == 503


def test_health_and_readiness(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory()
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {
            "status": "degraded", "database": "ok", "speech": "disabled", "shutting_down": False,
        }


def test_ready_is_ok_when_speech_is_loaded(app_factory: Callable[..., Any]) -> None:
    app, _ = app_factory(stt_enabled=True, stt_factory=lambda: FakeStt())
    with TestClient(app) as client:
        assert client.get("/ready").json()["status"] == "ready"


def test_a_speech_model_that_fails_to_load_leaves_text_calls_working(
    app_factory: Callable[..., Any],
) -> None:
    def broken() -> FakeStt:
        raise OSError("model missing")

    app, _ = app_factory(stt_enabled=True, stt_factory=broken)
    with TestClient(app) as client:
        assert client.get("/ready").json()["speech"] == "failed"
        with client.websocket_connect("/ws/call") as ws:
            start(ws)
            assert say(ws, "what are your timings")["type"] == "turn"
            ws.send_bytes(AUDIO_1S)
            assert ws.receive_json()["code"] == "stt_unavailable"


def test_a_database_outage_keeps_the_call_up(
    app_factory: Callable[..., Any], clock: Any
) -> None:
    flaky = FlakyRepository(seeded_repository(DEFAULT_RESTAURANT, clock))
    app, _ = app_factory(repository=flaky)
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        flaky.down = True
        outage = say(ws, "do you have tables tonight")
        assert "isn't available right now" in outage["reply"]
        assert outage["ended"] is False
        assert "open" in say(ws, "what are your timings")["reply"].lower()  # needs no database
        ready = client.get("/ready")
        assert ready.status_code == 503 and ready.json()["database"] == "unavailable"
        assert client.get("/health").status_code == 200
        flaky.down = False


def test_no_personal_data_in_logs_or_the_public_trace(
    app_factory: Callable[..., Any], caplog: pytest.LogCaptureFixture
) -> None:
    app, _ = app_factory()
    caplog.set_level(logging.DEBUG)
    turns = []
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        start(ws)
        for line in ["cancel my booking", "CP 1 0 0 1", "Alex Sample"]:
            turns.append(say(ws, line))
    assert "Alex Sample" in turns[-1]["reply"]  # the read-back to the caller is allowed
    for turn in turns:
        exposed = json.dumps({"trace": turn["trace"], "state": turn["state"]})
        for secret in ("Alex", "Sample", "1001"):
            assert secret not in exposed
    for secret in ("Alex", "Sample", "1001", "cancel my booking"):
        assert secret not in caplog.text
