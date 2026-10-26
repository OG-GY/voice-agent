"""Settings (environment / .env) with startup validation.

Unsafe or inconsistent settings stop the app from starting. Error messages name the setting
and never print its value, so a bad secret can't leak through a startup error.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.restaurant import RestaurantConfig

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
_FIXED_NOW_FORMAT = "%Y-%m-%d %H:%M"
_MIN_SECRET_CHARS = 32
_FRAME_OVERHEAD_BYTES = 1024


class ConfigError(Exception):
    """The configuration is unsafe or inconsistent. The message never contains values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    # app
    app_env: Literal["development", "test", "production"] = "development"
    bind_host: str = "127.0.0.1"
    port: PositiveInt = 8000
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_transcripts: bool = False
    log_stacktraces: bool = False
    expose_debug_trace: bool = False
    brain_fixed_now: str = ""

    # network
    cors_origins: str = "http://localhost:3000"
    trusted_proxies: str = ""
    ws_max_message_bytes: PositiveInt = 1_048_576
    caller_key_secret: SecretStr = SecretStr("")

    # database
    repository_backend: Literal["sqlite", "memory"] = "sqlite"
    database_path: str = "data/copper_pot.db"
    db_busy_timeout_ms: PositiveInt = 3000
    seed_demo_data: bool = False

    # speech
    stt_enabled: bool = True
    stt_model: str = "base.en"
    stt_model_path: str = ""
    stt_allow_download: bool = True
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_language: str = "en"
    stt_beam_size: PositiveInt = 1
    stt_cpu_threads: NonNegativeInt = 0
    stt_workers: PositiveInt = 1
    stt_queue_max: PositiveInt = 4
    stt_queue_per_ip: PositiveInt = 2
    stt_queue_wait_seconds: PositiveFloat = 5.0
    stt_timeout_seconds: PositiveFloat = 15.0

    # limits
    max_concurrent_calls: PositiveInt = 10
    max_calls_per_ip: PositiveInt = 3
    connects_per_minute_per_ip: PositiveInt = 10
    connect_burst: PositiveInt = 5
    messages_per_10s: PositiveInt = 30
    audio_seconds_per_minute: PositiveInt = 120
    invalid_before_close: PositiveInt = 5
    ip_penalty_invalid: PositiveInt = 20
    ip_penalty_seconds: PositiveInt = 300
    waiting_messages_per_call: PositiveInt = 2
    max_text_chars: PositiveInt = 500
    text_frame_max_bytes: PositiveInt = 4096
    max_utterance_seconds: PositiveFloat = 30.0
    min_utterance_seconds: PositiveFloat = 0.2
    idle_timeout_seconds: PositiveFloat = 120.0
    turn_timeout_seconds: PositiveFloat = 10.0
    shutdown_grace_seconds: PositiveFloat = 20.0

    # cancel verification
    verify_max_per_caller: PositiveInt = 5
    verify_max_global: PositiveInt = 30
    verify_window_minutes: PositiveInt = 15

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def max_audio_bytes(self) -> int:
        return int(self.max_utterance_seconds * SAMPLE_RATE * BYTES_PER_SAMPLE)

    def fixed_now(self) -> datetime:
        return datetime.strptime(self.brain_fixed_now, _FIXED_NOW_FORMAT)

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        problems: list[str] = []
        if self.brain_fixed_now:
            try:
                self.fixed_now()
            except ValueError:
                problems.append("BRAIN_FIXED_NOW must look like 2026-10-30 18:00")
        if self.ws_max_message_bytes < self.max_audio_bytes + _FRAME_OVERHEAD_BYTES:
            problems.append("WS_MAX_MESSAGE_BYTES is too small for MAX_UTTERANCE_SECONDS of audio")
        if self.text_frame_max_bytes < self.max_text_chars:
            problems.append("TEXT_FRAME_MAX_BYTES must be at least MAX_TEXT_CHARS")
        if self.min_utterance_seconds >= self.max_utterance_seconds:
            problems.append("MIN_UTTERANCE_SECONDS must be below MAX_UTTERANCE_SECONDS")
        if self.app_env == "production":
            problems += self._production_problems()
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _production_problems(self) -> list[str]:
        problems: list[str] = []
        if self.brain_fixed_now:
            problems.append("BRAIN_FIXED_NOW must be empty in production")
        for name in ("seed_demo_data", "log_transcripts", "expose_debug_trace", "stt_allow_download"):
            if getattr(self, name):
                problems.append(f"{name.upper()} must be false in production")
        if self.repository_backend != "sqlite":
            problems.append("REPOSITORY_BACKEND must be sqlite in production")
        if len(self.caller_key_secret.get_secret_value()) < _MIN_SECRET_CHARS:
            problems.append(f"CALLER_KEY_SECRET must be set ({_MIN_SECRET_CHARS}+ characters) in production")
        origins = self.cors_origin_list
        if not origins or any(not o.startswith("https://") for o in origins):
            problems.append("CORS_ORIGINS must list explicit https:// origins in production")
        if self.stt_enabled and not self.stt_model_path:
            problems.append("STT_MODEL_PATH must be set when speech is enabled in production")
        return problems


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'settings'}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(details) from None


def validate_runtime(settings: Settings, restaurant: RestaurantConfig) -> None:
    """Checks that need the filesystem or the restaurant definition."""
    problems: list[str] = []
    if restaurant.sitting_minutes % restaurant.slot_minutes:
        problems.append("the restaurant's sitting length must be a multiple of its slot length")
    if settings.repository_backend == "sqlite":
        folder = Path(settings.database_path).resolve().parent
        if not folder.exists() and not folder.parent.exists():
            problems.append("DATABASE_PATH is in a folder that cannot be created")
    needs_model = settings.app_env == "production" and settings.stt_enabled
    if needs_model and not Path(settings.stt_model_path).exists():
        problems.append("STT_MODEL_PATH does not exist (run the model preparation step)")
    if problems:
        raise ConfigError("; ".join(problems))
