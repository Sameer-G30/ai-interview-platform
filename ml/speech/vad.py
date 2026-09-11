"""Silero VAD pause segmentation on a 16 kHz mono WAV.

This is a separate pass from Whisper's optional `vad_filter`. We own the pause list so
acoustic-derived fluency does not depend on Whisper dropping silence internally. The Silero
model is loaded lazily and released after each call (8GB VRAM budget — do not keep it next
to a 7-8B judge).
"""

from __future__ import annotations  # SpeechSegment / VadResult used as return types

import wave  # stdlib reader for the 16-bit PCM wav ffmpeg wrote; avoids a torchaudio I/O extra
from dataclasses import asdict, dataclass  # JSON-safe segment/pause dicts

import numpy as np  # int16 -> float32 conversion; already pinned <2 in pyproject.toml

from ml.speech.asr import _release_cuda  # same CUDA empty_cache helper Whisper uses
from ml.speech.errors import SpeechTranscribeError, SpeechVadError  # missing wav / VAD load failure


@dataclass(frozen=True)
class SpeechSegment:
    """One voiced island from Silero, in seconds from the start of the WAV."""

    start: float  # seconds
    end: float  # seconds; >= start


@dataclass(frozen=True)
class Pause:
    """One internal silence between voiced islands (leading/trailing silence is not a pause)."""

    start: float  # seconds, end of the previous island
    end: float  # seconds, start of the next island
    duration: float  # end - start; already >= min_pause_s


@dataclass(frozen=True)
class VadResult:
    """Voiced islands, internal pauses, and the wav duration used as the acoustic clock."""

    speech_segments: list[SpeechSegment]  # Silero output, sorted by start
    pauses: list[Pause]  # gaps between islands that passed min_pause_s
    duration_s: float  # wav length in seconds (nframes / framerate)


def _load_wav_mono_float32(wav_path: str) -> tuple[np.ndarray, int, float]:
    """Read a 16 kHz (or any PCM) mono WAV into float32 [-1, 1], returning (samples, sr, duration_s)."""
    try:
        with wave.open(wav_path, "rb") as handle:  # ffmpeg wrote PCM s16le
            channels = handle.getnchannels()  # we requested 1; still handle a stereo mistake
            sample_rate = handle.getframerate()  # expected 16000
            n_frames = handle.getnframes()  # sample frames, not bytes
            width = handle.getsampwidth()  # 2 for s16
            raw = handle.readframes(n_frames)  # bytes
    except (FileNotFoundError, wave.Error) as exc:
        raise SpeechTranscribeError(f"cannot read wav: {exc}") from exc  # missing or not a wav
    if n_frames <= 0 or not raw:
        raise SpeechTranscribeError("wav has no samples")  # empty transcode
    if width != 2:
        raise SpeechVadError(f"expected 16-bit PCM wav, got sample width {width}")  # ffmpeg -sample_fmt s16
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0  # [-1, 1]
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)  # mix down; should already be mono
    duration_s = float(n_frames) / float(sample_rate) if sample_rate else 0.0  # acoustic clock
    return samples, int(sample_rate), duration_s


def pauses_between_segments(segments: list[SpeechSegment], *, min_pause_s: float) -> list[Pause]:
    """Turn consecutive voiced islands into internal pauses. Leading/trailing silence is omitted."""
    ordered = sorted(segments, key=lambda item: item.start)  # Silero is usually sorted already
    pauses: list[Pause] = []  # only gaps that pass the floor
    for index in range(len(ordered) - 1):
        start = ordered[index].end  # end of this island
        end = ordered[index + 1].start  # start of the next
        duration = end - start  # may be slightly negative if Silero overlaps; treat as no pause
        if duration >= min_pause_s:
            pauses.append(Pause(start=start, end=end, duration=duration))  # acoustic hesitation
    return pauses


def count_acoustic_fillers(
    words: list[tuple[float, float]],
    segments: list[SpeechSegment],
    *,
    max_burst_s: float = 0.3,
) -> int:
    """Count short VAD islands that do not overlap any ASR word — a hesitation/filler proxy.

    Whisper often drops `um`/`uh`. Those still show up as brief voiced bursts. A burst that
    overlaps a real word is just a short token, not a filler.
    """
    count = 0  # acoustic filler proxy
    for segment in segments:
        length = segment.end - segment.start  # island duration
        if length <= 0.0 or length > max_burst_s:
            continue  # too long to be a filled pause, or empty
        overlaps_word = False  # True if any ASR word shares time with this island
        for start, end in words:
            if end > segment.start and start < segment.end:
                overlaps_word = True  # this burst is explained by a transcribed token
                break  # one overlap is enough
        if not overlaps_word:
            count += 1  # unlexicalized voiced burst
    return count


def segment_speech(wav_path: str, *, min_pause_s: float) -> VadResult:
    """Run Silero VAD on a transcoded WAV and return voiced islands plus internal pauses.

    `silero_vad` is imported here, not at module import, so fluency unit tests never load torch
    extra paths. The model is deleted before return.
    """
    samples, sample_rate, duration_s = _load_wav_mono_float32(wav_path)  # numpy float32
    model = None  # so finally can del even if load_silero_vad raises
    try:
        import torch  # silero_vad expects a 1-D float tensor
        from silero_vad import get_speech_timestamps, load_silero_vad  # official PyPI API

        model = load_silero_vad()  # JIT/ONNX; a few MB, still unloaded per the 8GB rule
        wav = torch.from_numpy(np.ascontiguousarray(samples))  # 1-D float32
        timestamps = get_speech_timestamps(
            wav,
            model,
            sampling_rate=sample_rate,  # 16000 from ffmpeg; Silero also supports 8000
            return_seconds=True,  # we want seconds, not sample indexes
        )  # list of {"start": float, "end": float}
    except Exception as exc:
        raise SpeechVadError(f"{type(exc).__name__}: {exc}") from exc  # missing package / load failure
    finally:
        if model is not None:
            del model  # drop the VAD network
        _release_cuda()  # return CUDA blocks if Silero used GPU

    segments = [
        SpeechSegment(start=float(item["start"]), end=float(item["end"]))  # dict from silero_vad
        for item in timestamps or []
        if float(item.get("end", 0.0)) > float(item.get("start", 0.0))  # drop empty islands
    ]
    pauses = pauses_between_segments(segments, min_pause_s=min_pause_s)  # internal only
    return VadResult(speech_segments=segments, pauses=pauses, duration_s=duration_s)


def segment_to_dict(segment: SpeechSegment) -> dict:
    """JSON-safe dict for `answers.speech_metrics.vad.speech_segments`."""
    return asdict(segment)  # start / end


def pause_to_dict(pause: Pause) -> dict:
    """JSON-safe dict for `answers.speech_metrics.vad.pauses`."""
    return asdict(pause)  # start / end / duration
