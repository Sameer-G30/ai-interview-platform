"""Speech-pipeline config: Whisper model/device plus ffmpeg, independent of FastAPI Settings.

Mirrors `ml.llm.provider.LLMConfig`: product code uses `config_from_settings(get_settings())`
because pydantic-settings does not copy `.env` into `os.environ`. A research harness can
construct `SpeechConfig` directly or call `from_env()` after `load_dotenv()`.
"""

from __future__ import annotations  # SpeechConfig forward refs in helpers without quotes

import os  # SpeechConfig.from_env reads the same names as .env.example / Settings
from dataclasses import dataclass  # SpeechConfig is a plain value object, not a Pydantic Settings subclass
from typing import Any  # config_from_settings is duck-typed so ml/ does not import app.core.config

# Defaults match .env.example. medium.en fits an 8GB card with int8_float16; distil-large-v3 is also valid.
DEFAULT_WHISPER_MODEL = "medium.en"  # faster-whisper size/tag; must already be cached for the live smoke
DEFAULT_WHISPER_DEVICE = "cuda"  # cuda | cpu; product default is GPU because CPU Whisper is too slow for the queue
DEFAULT_WHISPER_COMPUTE_TYPE = "int8_float16"  # CTranslate2 quantized type sized for 8GB VRAM
DEFAULT_FFMPEG_PATH = "ffmpeg"  # looked up on PATH unless Settings.ffmpeg_path is an absolute binary
DEFAULT_MIN_PAUSE_S = 0.2  # gaps shorter than this are not counted as pauses (breath, not hesitation)
DEFAULT_LANGUAGE = "en"  # Chromium interview audio is English; skip Whisper language detection


@dataclass(frozen=True)
class SpeechConfig:
    """Whisper / ffmpeg / pause-threshold settings. Same field names as Settings / .env.example."""

    whisper_model: str = DEFAULT_WHISPER_MODEL  # faster-whisper model size or Hub id
    whisper_device: str = DEFAULT_WHISPER_DEVICE  # "cuda" or "cpu"
    whisper_compute_type: str = DEFAULT_WHISPER_COMPUTE_TYPE  # CTranslate2 compute_type string
    ffmpeg_path: str = DEFAULT_FFMPEG_PATH  # binary name or absolute path
    min_pause_s: float = DEFAULT_MIN_PAUSE_S  # pause floor for both transcript-gap and VAD-gap fluency
    language: str = DEFAULT_LANGUAGE  # passed to Whisper as language= so we skip auto-detect

    @classmethod
    def from_env(cls) -> SpeechConfig:
        """Build from process env using the same names as `.env.example`.

        Product code must prefer `config_from_settings(get_settings())`. This helper is for a
        research harness that exported the vars (or called `load_dotenv`) itself.
        """
        return cls(
            whisper_model=os.environ.get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL) or DEFAULT_WHISPER_MODEL,  # model tag
            whisper_device=(
                os.environ.get("WHISPER_DEVICE", DEFAULT_WHISPER_DEVICE).strip().lower() or DEFAULT_WHISPER_DEVICE
            ),  # cuda | cpu
            whisper_compute_type=(
                os.environ.get("WHISPER_COMPUTE_TYPE", DEFAULT_WHISPER_COMPUTE_TYPE) or DEFAULT_WHISPER_COMPUTE_TYPE
            ),  # CTranslate2 type
            ffmpeg_path=os.environ.get("FFMPEG_PATH", DEFAULT_FFMPEG_PATH) or DEFAULT_FFMPEG_PATH,  # binary
            min_pause_s=float(os.environ.get("SPEECH_MIN_PAUSE_S", str(DEFAULT_MIN_PAUSE_S))),  # pause floor
            language=os.environ.get("WHISPER_LANGUAGE", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE,  # ISO 639-1
        )


def config_from_settings(settings: Any) -> SpeechConfig:
    """Map a Settings-like object onto `SpeechConfig` without importing FastAPI."""
    return SpeechConfig(
        whisper_model=str(settings.whisper_model),  # Settings field whisper_model <- WHISPER_MODEL
        whisper_device=str(settings.whisper_device).strip().lower(),  # Settings field whisper_device
        whisper_compute_type=str(settings.whisper_compute_type),  # Settings field whisper_compute_type
        ffmpeg_path=str(getattr(settings, "ffmpeg_path", DEFAULT_FFMPEG_PATH) or DEFAULT_FFMPEG_PATH),  # optional
        min_pause_s=float(getattr(settings, "speech_min_pause_s", DEFAULT_MIN_PAUSE_S)),  # optional pause floor
        language=str(getattr(settings, "whisper_language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE),  # optional
    )
