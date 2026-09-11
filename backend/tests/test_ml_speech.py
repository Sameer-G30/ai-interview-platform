"""Unit tests for `ml.speech` fluency math and pause helpers. No Whisper, ffmpeg, or GPU.

The default suite must stay offline-safe: these functions take plain tuples/lists. Live faster-whisper
is covered by the skippable smoke in `test_speech.py`, never from here.
"""

import pytest  # approx for float pause math
from ml.speech.fluency import (  # dual-fluency helpers
    compute_fluency,
    count_fillers,
    fluency_from_vad,
    fluency_from_word_timestamps,
)
from ml.speech.vad import SpeechSegment, count_acoustic_fillers, pauses_between_segments  # pause helpers


def test_count_fillers_unigrams_and_you_know() -> None:
    """um/uh count; `you know` is one filler; `like` is not a filler in technical answers."""
    assert count_fillers(["Um", "I", "use", "Python"]) == 1  # leading filled pause
    assert count_fillers(["you", "know", "lists", "are", "mutable"]) == 1  # one bigram
    assert count_fillers(["I", "like", "Python"]) == 0  # "like" is a real verb here


def test_compute_fluency_zero_duration_is_zero_not_nan() -> None:
    """Empty audio must not emit NaN into JSON speech_metrics."""
    metrics = compute_fluency(
        word_count=0,  # no ASR tokens
        total_duration_s=0.0,  # empty wav
        speaking_duration_s=0.0,  # nothing voiced
        pause_durations_s=[],  # no pauses
        filler_count=0,  # no fillers
    )
    assert metrics.speech_rate_wpm == 0.0  # not NaN
    assert metrics.articulation_rate_wpm == 0.0  # not NaN
    assert metrics.pause_ratio == 0.0  # not NaN
    assert metrics.filler_rate == 0.0  # not NaN


def test_fluency_from_word_timestamps_counts_gaps() -> None:
    """A 1s gap between two words is a pause; speech rate uses the wav clock when provided."""
    words = [("hello", 0.0, 0.4), ("world", 1.4, 1.8)]  # 1.0s gap
    metrics = fluency_from_word_timestamps(words, min_pause_s=0.2, audio_duration_s=2.0)
    assert metrics.word_count == 2  # two ASR tokens
    assert metrics.pause_count == 1  # one gap above the floor
    assert metrics.pause_duration_s == pytest.approx(1.0)  # 1.4 - 0.4 (float subtraction)
    assert metrics.speech_rate_wpm == pytest.approx(2 / 2.0 * 60.0)  # wav clock
    assert metrics.speaking_duration_s == pytest.approx(1.0)  # 2.0 - 1.0 pause


def test_fluency_from_word_timestamps_ignores_tiny_gaps() -> None:
    """Sub-floor gaps are coarticulation, not pauses."""
    words = [("a", 0.0, 0.2), ("b", 0.25, 0.4)]  # 50ms gap
    metrics = fluency_from_word_timestamps(words, min_pause_s=0.2, audio_duration_s=0.4)
    assert metrics.pause_count == 0  # below 200ms
    assert metrics.pause_duration_s == 0.0  # nothing subtracted


def test_fluency_from_vad_uses_voiced_duration_for_articulation() -> None:
    """Acoustic articulation rate divides by Silero voiced time, not the wav clock."""
    words = [("hello", 0.1, 0.4), ("there", 1.0, 1.3)]  # two words
    segments = [(0.1, 0.5), (0.9, 1.4)]  # 0.4 + 0.5 = 0.9s voiced; 0.4s internal gap
    metrics = fluency_from_vad(
        words,
        segments,
        audio_duration_s=2.0,  # wav clock for speech rate
        min_pause_s=0.2,
        filler_count=1,  # acoustic proxy, not transcript um/uh
    )
    assert metrics.speech_rate_wpm == pytest.approx(2 / 2.0 * 60.0)  # words / wav
    assert metrics.articulation_rate_wpm == pytest.approx(2 / 0.9 * 60.0)  # words / VAD voiced
    assert metrics.pause_count == 1  # one internal gap
    assert metrics.filler_count == 1  # the proxy we passed in
    assert metrics.filler_rate == 0.5  # 1 / 2 words


def test_pauses_between_segments_skips_leading_and_trailing() -> None:
    """Fluency pauses are internal; leading/trailing silence is not a hesitation."""
    segments = [SpeechSegment(start=0.5, end=1.0), SpeechSegment(start=1.5, end=2.0)]  # 0.5s gap
    pauses = pauses_between_segments(segments, min_pause_s=0.2)
    assert len(pauses) == 1  # only the middle gap
    assert pauses[0].duration == 0.5  # 1.5 - 1.0


def test_count_acoustic_fillers_short_unaligned_burst() -> None:
    """A short VAD island with no overlapping ASR word counts as an acoustic filler."""
    segments = [SpeechSegment(start=0.0, end=0.2), SpeechSegment(start=0.5, end=1.5)]  # 200ms then a real word
    words = [(0.5, 1.5)]  # only the second island is lexicalized
    assert count_acoustic_fillers(words, segments, max_burst_s=0.3) == 1  # first island is the proxy
    assert count_acoustic_fillers(words, segments, max_burst_s=0.1) == 0  # 200ms is above this tighter cap
