"""faster-whisper implementation. The library is imported lazily so the app runs without it."""

import math
from typing import Any

from app.config import SAMPLE_RATE, Settings
from app.speech.base import Transcript

_PROMPT = (
    "Restaurant table booking. Words: table, booking, reservation, window, private, general, "
    "Friday, Saturday, seven thirty, party of four, Mr., Mrs., Ms."
)
_MAX_NO_SPEECH_PROB = 0.6
_MIN_AVG_LOGPROB = -1.0
_MIN_SILENCE_MS = 500


class WhisperSpeechToText:
    def __init__(self, settings: Settings) -> None:
        from faster_whisper import WhisperModel  # imported here: heavy, optional

        self._settings = settings
        self._model = WhisperModel(
            settings.stt_model_path or settings.stt_model,
            device=settings.stt_device,
            compute_type=settings.stt_compute_type,
            cpu_threads=settings.stt_cpu_threads,
            local_files_only=not settings.stt_allow_download,
        )

    def transcribe(self, audio: Any) -> Transcript:
        s = self._settings
        duration = len(audio) / SAMPLE_RATE
        segments, _ = self._model.transcribe(
            audio,
            language=s.stt_language,
            beam_size=s.stt_beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": _MIN_SILENCE_MS},
            condition_on_previous_text=False,
            initial_prompt=_PROMPT,
        )
        parts: list[str] = []
        logprobs: list[float] = []
        no_speech: list[float] = []
        for segment in segments:  # a generator: consuming it runs the model
            parts.append(segment.text.strip())
            logprobs.append(segment.avg_logprob)
            no_speech.append(segment.no_speech_prob)
        text = " ".join(p for p in parts if p).strip()
        if not text:
            return Transcript("", 0.0, duration)
        average = sum(logprobs) / len(logprobs)
        if max(no_speech) > _MAX_NO_SPEECH_PROB or average < _MIN_AVG_LOGPROB:
            return Transcript("", 0.0, duration)  # Whisper tends to invent text on noise
        return Transcript(text, math.exp(average), duration)
