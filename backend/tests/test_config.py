"""Unsafe or inconsistent settings must stop the app from starting, without leaking values."""

from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import ConfigError, Settings, load_settings, validate_runtime
from app.services.restaurant import DEFAULT_RESTAURANT

PRODUCTION: dict[str, Any] = {
    "app_env": "production",
    "caller_key_secret": "x" * 40,
    "cors_origins": "https://app.example",
    "stt_enabled": False,
    "stt_allow_download": False,
}


def make(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**PRODUCTION, **overrides})  # type: ignore[call-arg]


def test_a_safe_production_configuration_loads() -> None:
    assert make().app_env == "production"


@pytest.mark.parametrize(
    "override",
    [
        {"brain_fixed_now": "2026-10-30 18:00"},
        {"seed_demo_data": True},
        {"log_transcripts": True},
        {"expose_debug_trace": True},
        {"stt_allow_download": True},
        {"repository_backend": "memory"},
        {"caller_key_secret": "too-short"},
        {"cors_origins": "http://app.example"},
        {"cors_origins": "*"},
        {"cors_origins": ""},
        {"stt_enabled": True},  # needs STT_MODEL_PATH
    ],
)
def test_unsafe_production_settings_are_refused(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make(**override)


def test_the_demo_clock_is_allowed_in_development_only() -> None:
    Settings(_env_file=None, brain_fixed_now="2026-10-30 18:00")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        make(brain_fixed_now="2026-10-30 18:00")


def test_a_malformed_demo_clock_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, brain_fixed_now="tomorrow")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "override",
    [
        {"ws_max_message_bytes": 1000},  # cannot hold the longest recording
        {"text_frame_max_bytes": 10, "max_text_chars": 500},
        {"min_utterance_seconds": 40.0},
        {"max_concurrent_calls": 0},
    ],
)
def test_inconsistent_limits_are_refused(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **override)  # type: ignore[call-arg]


def test_startup_errors_never_print_the_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.chdir(tmp_path)  # no stray .env
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CALLER_KEY_SECRET", "hunter2-not-long-enough")
    with pytest.raises(ConfigError) as error:
        load_settings()
    assert "hunter2" not in str(error.value)
    assert "CALLER_KEY_SECRET" in str(error.value)


def test_the_sitting_must_be_a_whole_number_of_slots() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    broken = replace(DEFAULT_RESTAURANT, sitting_minutes=100)
    with pytest.raises(ConfigError):
        validate_runtime(settings, broken)
    validate_runtime(settings, DEFAULT_RESTAURANT)
