"""Run the API.

    uv run python -m app.serve            # one worker; frame-size cap and graceful shutdown applied
    uv run python -m app.serve --reload   # development only
"""

import argparse
from types import FrameType

import uvicorn

from app import runtime
from app.config import ConfigError, load_settings, validate_runtime
from app.services.restaurant import DEFAULT_RESTAURANT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Copper Pot voice receptionist API.")
    parser.add_argument("--reload", action="store_true", help="auto-reload (development only)")
    args = parser.parse_args()
    try:
        settings = load_settings()
        validate_runtime(settings, DEFAULT_RESTAURANT)
    except ConfigError as exc:
        raise SystemExit(f"Invalid configuration: {exc}") from None
    if args.reload and settings.app_env == "production":
        raise SystemExit("--reload is not allowed when APP_ENV=production")

    options = {
        "factory": True,
        "host": settings.bind_host,
        "port": settings.port,
        "ws_max_size": settings.ws_max_message_bytes,  # oversize frames are refused before the app
        "timeout_graceful_shutdown": int(settings.shutdown_grace_seconds),
        "log_config": None,
        "access_log": False,  # access logs hold client IP addresses
    }
    if args.reload:
        uvicorn.run("app.main:create_app", reload=True, **options)  # type: ignore[arg-type]
        return

    server = uvicorn.Server(uvicorn.Config("app.main:create_app", **options))  # type: ignore[arg-type]
    original_exit = server.handle_exit

    def handle_exit(sig: int, frame: FrameType | None) -> None:
        runtime.begin_shutdown()  # mark not-ready and warn active calls first
        original_exit(sig, frame)

    server.handle_exit = handle_exit  # type: ignore[method-assign]
    server.run()


if __name__ == "__main__":
    main()
