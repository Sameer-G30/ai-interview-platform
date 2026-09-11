"""Typed errors for the speech pipeline (ASR / VAD / prosody / ffmpeg).

Workers catch these and fail the `transcribe` async job with a short message. They are never
raised from a FastAPI request handler — the API only enqueues after the WebM is on disk.
"""


class SpeechError(Exception):
    """Base class for every `ml.speech` failure so callers can catch broadly."""


class SpeechFfmpegError(SpeechError):
    """Raised when ffmpeg is missing or cannot transcode the uploaded WebM/Opus blob to WAV."""

    def __init__(self, message: str) -> None:  # message is the short reason stored on async_jobs.error
        super().__init__(message)  # Exception stores message as str(self)


class SpeechAsrError(SpeechError):
    """Raised when faster-whisper cannot load or cannot transcribe the transcoded WAV."""

    def __init__(self, message: str) -> None:  # missing weights, CUDA OOM, empty decode, etc.
        super().__init__(message)  # Exception stores message as str(self)


class SpeechVadError(SpeechError):
    """Raised when Silero VAD cannot load or cannot segment the WAV."""

    def __init__(self, message: str) -> None:  # missing torch / corrupt wav / model load failure
        super().__init__(message)  # Exception stores message as str(self)


class SpeechProsodyError(SpeechError):
    """Raised when parselmouth/Praat cannot measure pitch or intensity on the WAV."""

    def __init__(self, message: str) -> None:  # unreadable wav, Praat native error
        super().__init__(message)  # Exception stores message as str(self)


class SpeechTranscribeError(SpeechError):
    """Raised when the audio path is missing on disk or the pipeline has nothing to transcribe."""

    def __init__(self, message: str) -> None:  # missing file, empty wav after transcode
        super().__init__(message)  # Exception stores message as str(self)
