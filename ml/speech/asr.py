"""faster-whisper ASR with word timestamps, plus ffmpeg transcode of Chromium WebM/Opus.

Whisper is loaded lazily inside `transcribe_wav` and released before the function returns so an
8GB card is not holding a judge and Whisper at the same time. Do not call this from a FastAPI
request handler — the ARQ `transcribe` worker wraps it in `asyncio.to_thread`.
"""

from __future__ import annotations  # WordTimestamp used in return types before the class body ends

import gc  # collect after deleting the CTranslate2 model so VRAM can be reused by the next job
import shutil  # shutil.which locates ffmpeg when ffmpeg_path is a bare command name
import subprocess  # run ffmpeg; never shell=True
from dataclasses import asdict, dataclass  # JSON-safe word dicts for answers.speech_metrics
from pathlib import Path  # transcode destination is a .wav next to a temp dir

from ml.speech.config import SpeechConfig  # model / device / ffmpeg path
from ml.speech.errors import SpeechAsrError, SpeechFfmpegError, SpeechTranscribeError  # typed failures


@dataclass(frozen=True)
class WordTimestamp:
    """One ASR token with start/end seconds and Whisper's per-word probability."""

    word: str  # surface token, including any leading space Whisper emits
    start: float  # seconds from the start of the transcoded WAV
    end: float  # seconds; >= start
    probability: float  # 0-1 confidence from faster-whisper; 0 when the backend omitted it


@dataclass(frozen=True)
class AsrResult:
    """Full-utterance transcript plus the word list the fluency module needs."""

    transcript: str  # concatenated segment text, stripped; empty string when Whisper heard nothing
    words: list[WordTimestamp]  # flattened across segments, listen order
    language: str | None  # detected or forced language code
    duration_s: float  # Whisper's reported audio duration (seconds)


def _ffmpeg_binary(config: SpeechConfig) -> str:
    """Resolve the ffmpeg executable. Bare names go through PATH; absolute paths are used as-is."""
    configured = config.ffmpeg_path.strip() or "ffmpeg"  # empty string would confuse shutil.which
    if Path(configured).is_file():  # absolute or relative path that already exists
        return configured  # caller pointed at a downloaded static binary
    found = shutil.which(configured)  # search PATH for "ffmpeg"
    if found is None:
        raise SpeechFfmpegError(
            "ffmpeg is not installed; transcode Chromium WebM/Opus to WAV before Whisper"
        )  # plan Part 5: do not decode WebM inside the request handler either
    return found  # full path from PATH


def transcode_to_wav(src_path: str, dst_path: str, config: SpeechConfig) -> None:
    """Convert a Chromium `audio/webm;codecs=opus` blob to 16 kHz mono 16-bit PCM WAV.

    Silero VAD wants 16 kHz; Praat and faster-whisper are happy with the same file. Safari is
    unsupported — this is not a transcode-from-mp4 path.
    """
    source = Path(src_path)  # uploaded blob under storage_root/interviews/...
    if not source.is_file():
        raise SpeechTranscribeError(f"audio file is missing: {src_path}")  # overwrite/delete race
    ffmpeg = _ffmpeg_binary(config)  # raises SpeechFfmpegError if missing
    destination = Path(dst_path)  # worker writes this inside a TemporaryDirectory
    destination.parent.mkdir(parents=True, exist_ok=True)  # temp dir should already exist
    completed = subprocess.run(  # nosec: argv list, not a shell string
        [
            ffmpeg,  # resolved binary
            "-y",  # overwrite the temp wav if a retry reused the same dest name
            "-i",  # input flag
            str(source),  # WebM/Opus from MediaRecorder
            "-vn",  # drop any video track some Chromium builds attach to webm
            "-ac",  # audio channels
            "1",  # mono
            "-ar",  # sample rate
            "16000",  # 16 kHz, Silero's native rate
            "-sample_fmt",  # PCM format
            "s16",  # 16-bit signed, stdlib wave + Praat both accept this
            str(destination),  # output wav
        ],
        check=False,  # we map non-zero to SpeechFfmpegError ourselves
        capture_output=True,  # keep stderr for the short job error
        text=True,  # decode stderr as str
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip()[-400:]  # cap for async_jobs.error
        raise SpeechFfmpegError(f"ffmpeg failed ({completed.returncode}): {tail or 'no stderr'}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise SpeechFfmpegError("ffmpeg produced an empty WAV")  # should not happen on a real WebM


def _release_cuda() -> None:
    """Drop cached CUDA blocks after deleting a Whisper/VAD model. Safe to call when CUDA is absent."""
    gc.collect()  # run Python GC first so CTranslate2/torch objects are actually gone
    try:
        import torch  # already a transitive dep via sentence-transformers; do not add a second pin

        if torch.cuda.is_available():
            torch.cuda.empty_cache()  # return unused blocks to the driver for the next job
    except ImportError:
        return  # torch missing in a stripped env; nothing to empty


def transcribe_wav(wav_path: str, config: SpeechConfig) -> AsrResult:
    """Run faster-whisper with word timestamps on an already-transcoded WAV. Unloads the model after.

    openai-whisper is not used. Weights are loaded here, not at import, not in the API process.
    """
    from faster_whisper import WhisperModel  # heavy; deferred so `import ml.speech.fluency` stays light

    path = Path(wav_path)  # 16 kHz wav from transcode_to_wav
    if not path.is_file():
        raise SpeechTranscribeError(f"wav is missing: {wav_path}")  # temp dir cleaned up too early
    model = None  # so the finally block can del even if the constructor raises
    try:
        model = WhisperModel(
            config.whisper_model,  # "medium.en" or "distil-large-v3"
            device=config.whisper_device,  # cuda | cpu from Settings
            compute_type=config.whisper_compute_type,  # int8_float16 on this 8GB card
        )  # may download on first call; tests must not reach here without a skip
        segments_iter, info = model.transcribe(
            str(path),  # wav path
            language=config.language,  # force English; skip auto-detect
            word_timestamps=True,  # required for transcript-derived pauses and the later viewer
            vad_filter=False,  # Silero runs in vad.py so we own pause segmentation
            beam_size=5,  # faster-whisper default quality; short answers stay cheap
        )
        segments = list(segments_iter)  # generator is lazy; force the decode before we unload
    except Exception as exc:
        raise SpeechAsrError(f"{type(exc).__name__}: {exc}") from exc  # OOM, missing weights, CUDA
    finally:
        if model is not None:
            del model  # drop the CTranslate2 handle before the next LLM job
        _release_cuda()  # 8GB VRAM rule: do not keep Whisper resident

    words: list[WordTimestamp] = []  # flattened across segments
    texts: list[str] = []  # segment strings joined into transcript
    for segment in segments:
        texts.append(getattr(segment, "text", "") or "")  # faster-whisper Segment.text
        for item in getattr(segment, "words", None) or []:  # may be None if word_timestamps failed
            token = getattr(item, "word", "") or ""  # include leading space; fluency strips it
            start = float(getattr(item, "start", 0.0) or 0.0)  # seconds
            end = float(getattr(item, "end", start) or start)  # fallback to a zero-width token
            probability = float(getattr(item, "probability", 0.0) or 0.0)  # 0 when omitted
            words.append(WordTimestamp(word=token, start=start, end=end, probability=probability))
    transcript = " ".join(part.strip() for part in texts if part.strip()).strip()  # collapse segment gaps
    duration_s = float(getattr(info, "duration", 0.0) or 0.0)  # Whisper's duration; wav length is authoritative later
    language = getattr(info, "language", None)  # "en" when we forced it
    return AsrResult(transcript=transcript, words=words, language=language, duration_s=duration_s)


def word_to_dict(word: WordTimestamp) -> dict:
    """JSON-safe dict for `answers.speech_metrics.words`."""
    return asdict(word)  # word / start / end / probability
