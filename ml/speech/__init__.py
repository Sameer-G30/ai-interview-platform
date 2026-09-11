"""Speech pipeline: ffmpeg transcode, faster-whisper ASR, Silero VAD, Praat prosody, dual fluency.

`run_speech_pipeline` is the single entry point the ARQ `transcribe` worker (and, later, the
research harness) calls. Whisper/VAD/Praat stay inside this function so a FastAPI request
handler never loads them. Both transcript-derived and acoustic-derived fluency are always
emitted; the product does not pick a winner here.
"""

from __future__ import annotations  # SpeechPipelineResult used as a return type

import tempfile  # WAV lives in a temp dir and is deleted after the pipeline returns
from dataclasses import dataclass  # result object the worker splits into transcript + JSON
from pathlib import Path  # source WebM path

from ml.speech.asr import (  # ffmpeg + faster-whisper
    AsrResult,
    transcode_to_wav,
    transcribe_wav,
    word_to_dict,
)
from ml.speech.config import SpeechConfig, config_from_settings  # Settings / env mapping
from ml.speech.errors import (  # re-exported so `from ml.speech import SpeechError` works
    SpeechAsrError,
    SpeechError,
    SpeechFfmpegError,
    SpeechProsodyError,
    SpeechTranscribeError,
    SpeechVadError,
)
from ml.speech.fluency import (  # dual fluency
    FluencyMetrics,
    fluency_from_vad,
    fluency_from_word_timestamps,
    fluency_to_dict,
)
from ml.speech.prosody import ProsodyMetrics, measure_prosody, prosody_to_dict  # Praat summaries
from ml.speech.vad import (  # Silero segmentation
    VadResult,
    count_acoustic_fillers,
    pause_to_dict,
    segment_speech,
    segment_to_dict,
)

__all__ = [  # public surface the worker and research harness should import from `ml.speech`
    "AsrResult",  # word timestamps + transcript string
    "FluencyMetrics",  # one fluency arm
    "ProsodyMetrics",  # pitch / intensity
    "SpeechAsrError",  # faster-whisper failure
    "SpeechConfig",  # Whisper / ffmpeg settings
    "SpeechError",  # base error
    "SpeechFfmpegError",  # missing ffmpeg / transcode failure
    "SpeechPipelineResult",  # run_speech_pipeline return
    "SpeechProsodyError",  # Praat failure
    "SpeechTranscribeError",  # missing audio / empty wav
    "SpeechVadError",  # Silero failure
    "VadResult",  # voiced islands + pauses
    "config_from_settings",  # Settings -> SpeechConfig
    "run_speech_pipeline",  # the one worker entry point
]


@dataclass(frozen=True)
class SpeechPipelineResult:
    """Everything persisted after a successful `transcribe` job (except the filesystem audio_path)."""

    transcript: str  # written to answers.transcript (plain text, not JSON)
    asr: AsrResult  # words / language / whisper duration
    vad: VadResult  # speech_segments / pauses / wav duration
    prosody: ProsodyMetrics  # pitch / intensity
    fluency_transcript: FluencyMetrics  # pauses from word-timestamp gaps
    fluency_acoustic: FluencyMetrics  # pauses / speaking time from Silero

    def to_metrics_dict(self) -> dict:
        """JSON object stored on `answers.speech_metrics` for the later analysis UI."""
        return {
            "words": [word_to_dict(word) for word in self.asr.words],  # word timings for the transcript viewer
            "language": self.asr.language,  # "en" when we forced it
            "duration_s": self.vad.duration_s,  # wav duration is the acoustic clock
            "fluency_transcript": fluency_to_dict(self.fluency_transcript),  # ASR-gap arm
            "fluency_acoustic": fluency_to_dict(self.fluency_acoustic),  # VAD arm
            "prosody": prosody_to_dict(self.prosody),  # Praat summaries
            "vad": {
                "speech_segments": [segment_to_dict(item) for item in self.vad.speech_segments],  # voiced islands
                "pauses": [pause_to_dict(item) for item in self.vad.pauses],  # internal pauses
            },
        }


def run_speech_pipeline(file_path: str, config: SpeechConfig | None = None) -> SpeechPipelineResult:
    """Transcode one WebM/Opus (or wav) blob and emit transcript + dual fluency + prosody.

    `file_path` is the on-disk MediaRecorder blob (`answers.audio_path`). Raises a `SpeechError`
    subclass if ffmpeg/Whisper/VAD/Praat fail. Callers must not invoke this in a request handler.
    """
    settings = config if config is not None else SpeechConfig()  # research harness can pass a config
    source = Path(file_path)  # Chromium webm under storage_root
    if not source.is_file():
        raise SpeechTranscribeError(f"audio file is missing: {file_path}")  # upload must commit the blob first
    with tempfile.TemporaryDirectory(prefix="aiip-speech-") as tmp:  # deleted even when ASR raises
        wav_path = str(Path(tmp) / "answer.wav")  # 16 kHz mono PCM
        transcode_to_wav(str(source), wav_path, settings)  # raises SpeechFfmpegError
        asr = transcribe_wav(wav_path, settings)  # loads and unloads faster-whisper
        vad = segment_speech(wav_path, min_pause_s=settings.min_pause_s)  # loads and unloads Silero
        prosody = measure_prosody(wav_path)  # Praat; no GPU model to unload
        word_tuples = [(word.word, word.start, word.end) for word in asr.words]  # fluency input
        fluency_transcript = fluency_from_word_timestamps(
            word_tuples,
            min_pause_s=settings.min_pause_s,  # same floor as VAD so the pair is comparable
            audio_duration_s=vad.duration_s,  # wav clock so a silent tail is visible
        )
        acoustic_fillers = count_acoustic_fillers(
            [(word.start, word.end) for word in asr.words],  # ASR intervals
            vad.speech_segments,  # Silero islands
        )
        fluency_acoustic = fluency_from_vad(
            word_tuples,
            [(item.start, item.end) for item in vad.speech_segments],  # voiced islands
            audio_duration_s=vad.duration_s,  # wav duration
            min_pause_s=settings.min_pause_s,  # same floor
            filler_count=acoustic_fillers,  # unaligned short bursts, not transcript um/uh
        )
        return SpeechPipelineResult(
            transcript=asr.transcript,  # may be empty if Whisper heard nothing; still a success
            asr=asr,  # words for GET session
            vad=vad,  # pauses for GET session
            prosody=prosody,  # pitch/intensity for GET session
            fluency_transcript=fluency_transcript,  # ASR-gap arm
            fluency_acoustic=fluency_acoustic,  # VAD arm
        )
