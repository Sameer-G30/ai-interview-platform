"""parselmouth (Praat) pitch and intensity on a 16 kHz WAV.

Acoustic fluency uses VAD pauses; this module only records F0 / intensity summaries for the
later analysis UI and the research harness. Praat is loaded lazily and not kept resident.
"""

from __future__ import annotations  # ProsodyMetrics used as a return type

from dataclasses import asdict, dataclass  # JSON-safe dict for answers.speech_metrics.prosody

import numpy as np  # mean/std on voiced frames; pinned <2 in pyproject.toml

from ml.speech.errors import SpeechProsodyError, SpeechTranscribeError  # Praat failures / missing wav


@dataclass(frozen=True)
class ProsodyMetrics:
    """Utterance-level pitch (Hz) and intensity (dB). Zeros when the wav is unvoiced or empty."""

    pitch_mean_hz: float  # mean F0 over voiced frames; 0 when none
    pitch_std_hz: float  # stdev of F0 over voiced frames; 0 when <2 voiced frames
    intensity_mean_db: float  # mean intensity; 0 when Praat returns no frames
    intensity_std_db: float  # stdev of intensity; 0 when <2 frames


def measure_prosody(wav_path: str) -> ProsodyMetrics:
    """Run Praat pitch + intensity via parselmouth. Import is deferred so unit tests stay light."""
    try:
        import parselmouth  # Praat bindings; not imported at FastAPI startup
    except ImportError as exc:
        raise SpeechProsodyError(f"parselmouth is not installed: {exc}") from exc  # missing extra
    try:
        sound = parselmouth.Sound(wav_path)  # reads the ffmpeg WAV
    except Exception as exc:
        raise SpeechTranscribeError(f"parselmouth could not open wav: {exc}") from exc  # missing/corrupt
    try:
        pitch = sound.to_pitch()  # Praat To Pitch (ac) with library defaults
        pitch_values = np.array(pitch.selected_array["frequency"], dtype=np.float64)  # Hz; 0 = unvoiced
        voiced = pitch_values[pitch_values > 0.0]  # drop unvoiced frames so mean is not pulled to 0
        if voiced.size == 0:
            pitch_mean = 0.0  # unvoiced utterance (silence, whisper-level, or failed F0)
            pitch_std = 0.0  # no spread
        else:
            pitch_mean = float(np.mean(voiced))  # Hz
            pitch_std = float(np.std(voiced)) if voiced.size > 1 else 0.0  # 0 for a single frame
        intensity = sound.to_intensity()  # Praat To Intensity
        intensity_values = np.array(intensity.values, dtype=np.float64).reshape(-1)  # dB, 1 x n
        finite = intensity_values[np.isfinite(intensity_values)]  # drop NaN/inf if Praat emitted them
        if finite.size == 0:
            intensity_mean = 0.0  # no intensity frames
            intensity_std = 0.0  # no spread
        else:
            intensity_mean = float(np.mean(finite))  # dB
            intensity_std = float(np.std(finite)) if finite.size > 1 else 0.0  # 0 for a single frame
    except SpeechTranscribeError:
        raise  # keep typed errors
    except Exception as exc:
        raise SpeechProsodyError(f"{type(exc).__name__}: {exc}") from exc  # Praat native failure
    return ProsodyMetrics(
        pitch_mean_hz=pitch_mean,  # F0 mean
        pitch_std_hz=pitch_std,  # F0 spread
        intensity_mean_db=intensity_mean,  # loudness mean
        intensity_std_db=intensity_std,  # loudness spread
    )


def prosody_to_dict(metrics: ProsodyMetrics) -> dict:
    """JSON-safe dict for `answers.speech_metrics.prosody`."""
    return asdict(metrics)  # pitch_mean_hz / pitch_std_hz / intensity_mean_db / intensity_std_db
