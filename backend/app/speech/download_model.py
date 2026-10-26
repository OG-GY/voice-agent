"""Prepare the Whisper model ahead of time, so no customer request ever triggers a download.

    uv run python -m app.speech.download_model [--model base.en] [--output models/base.en]

In production set STT_MODEL_PATH to the output folder and STT_ALLOW_DOWNLOAD=false.
"""

import argparse

from app.config import load_settings


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Download a faster-whisper model.")
    parser.add_argument("--model", default=settings.stt_model)
    parser.add_argument("--output", default=None, help="folder to place the model in")
    args = parser.parse_args()

    from faster_whisper.utils import download_model

    path = download_model(args.model, output_dir=args.output)
    print(f"model ready at {path}")


if __name__ == "__main__":
    main()
