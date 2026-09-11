"""Fluency metrics computed two ways: from ASR word timestamps, and from Silero VAD acoustics.

The product can later pick the better estimate; the research harness consumes the pair. Both
arms return the same five headline numbers: speech rate, articulation rate, mean pause duration,
pause ratio, and filler rate. Non-empty `improvements` on a judge score is unrelated — this
module never calls the LLM.
"""

from __future__ import annotations  # WordLike protocol uses quotes-free forward refs

from dataclasses import asdict, dataclass  # JSON-safe dicts written onto answers.speech_metrics

# Conservative English filled-pause tokens. Do not include "like"/"so"/"basically": those are
# ordinary words in technical answers and would inflate filler_rate on every Python explanation.
_FILLER_UNIGRAMS = frozenset({"um", "uh", "er", "ah", "hmm", "mm", "uhh", "umm", "err", "uhm"})
# One common two-word hedge kept as a bigram so "know" alone is not counted.
_FILLER_BIGRAMS = frozenset({("you", "know")})


@dataclass(frozen=True)
class FluencyMetrics:
    """One fluency estimate (transcript-derived *or* acoustic-derived). All rates are non-negative."""

    speech_rate_wpm: float  # words / total_duration_s * 60; 0 when duration is 0
    articulation_rate_wpm: float  # words / speaking_duration_s * 60; 0 when speaking duration is 0
    mean_pause_duration_s: float  # mean of pause lengths; 0 when there are no pauses
    pause_ratio: float  # pause_duration / total_duration; 0 when duration is 0
    filler_rate: float  # filler_count / word_count; 0 when there are no words
    filler_count: int  # how many filler tokens (or acoustic filler proxies) were counted
    word_count: int  # ASR word count used as the numerator for rates
    total_duration_s: float  # clock used for speech_rate (word span or wav duration)
    speaking_duration_s: float  # clock used for articulation_rate (minus pauses, or VAD voiced time)
    pause_duration_s: float  # sum of pause lengths included in mean_pause / pause_ratio
    pause_count: int  # number of pauses that passed the min_pause_s floor


def _normalize_token(raw: str) -> str:
    """Lower-case a word and strip punctuation so `Um,` matches the filler set."""
    stripped = raw.strip().lower()  # Whisper tokens often include a leading space
    return stripped.strip(".,!?;:\"'()[]{}")  # keep apostrophes out of fillers; um/uh never have them


def count_fillers(words: list[str]) -> int:
    """Count filled-pause unigrams plus `you know` bigrams in an ordered token list."""
    tokens = [_normalize_token(word) for word in words if _normalize_token(word)]  # drop empty after strip
    count = 0  # running filler total
    skip_next = False  # True after we consumed the second half of a bigram
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False  # the previous iteration already counted this as part of a bigram
            continue  # do not also count "know" as a unigram
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""  # lookahead for bigrams
        if (token, nxt) in _FILLER_BIGRAMS:
            count += 1  # one hedge, not two tokens
            skip_next = True  # consume the following "know"
            continue  # do not also count "you" as a unigram
        if token in _FILLER_UNIGRAMS:
            count += 1  # classic filled pause
    return count


def compute_fluency(
    *,
    word_count: int,
    total_duration_s: float,
    speaking_duration_s: float,
    pause_durations_s: list[float],
    filler_count: int,
) -> FluencyMetrics:
    """Turn counts and durations into the shared fluency schema. Never returns NaN."""
    safe_words = max(int(word_count), 0)  # negative word counts are a caller bug; clamp rather than crash
    safe_total = max(float(total_duration_s), 0.0)  # duration must not go negative
    safe_speaking = max(float(speaking_duration_s), 0.0)  # voiced/speaking time
    pauses = [max(float(item), 0.0) for item in pause_durations_s]  # each pause length in seconds
    pause_duration = sum(pauses)  # total pause time included in the ratio
    pause_count = len(pauses)  # how many pauses passed the caller's min_pause_s filter
    speech_rate = (safe_words / safe_total) * 60.0 if safe_total > 0.0 else 0.0  # WPM including pauses
    articulation = (safe_words / safe_speaking) * 60.0 if safe_speaking > 0.0 else 0.0  # WPM excluding pauses
    mean_pause = (pause_duration / pause_count) if pause_count else 0.0  # 0 when there were no pauses
    pause_ratio = (pause_duration / safe_total) if safe_total > 0.0 else 0.0  # fraction of the clock spent paused
    filler_rate = (float(filler_count) / safe_words) if safe_words else 0.0  # 0 when ASR produced no words
    return FluencyMetrics(
        speech_rate_wpm=speech_rate,  # headline speech rate
        articulation_rate_wpm=articulation,  # headline articulation rate
        mean_pause_duration_s=mean_pause,  # headline mean pause
        pause_ratio=pause_ratio,  # headline pause ratio
        filler_rate=filler_rate,  # headline filler rate
        filler_count=int(filler_count),  # raw count for the research harness
        word_count=safe_words,  # denominator for filler_rate
        total_duration_s=safe_total,  # clock for speech_rate
        speaking_duration_s=safe_speaking,  # clock for articulation_rate
        pause_duration_s=pause_duration,  # sum of pauses
        pause_count=pause_count,  # number of pauses
    )


def fluency_from_word_timestamps(
    words: list[tuple[str, float, float]],
    *,
    min_pause_s: float,
    audio_duration_s: float | None = None,
) -> FluencyMetrics:
    """Transcript-derived fluency: pauses are gaps between consecutive ASR word timestamps.

    `words` is `(token, start_s, end_s)` in listen order. `audio_duration_s` is used as the
    speech-rate clock when provided (so a long silent tail counts); otherwise the last word end.
    """
    ordered = sorted(words, key=lambda item: item[1])  # start time; Whisper is usually already ordered
    tokens = [item[0] for item in ordered]  # surface forms for filler counting
    if not ordered:
        total = float(audio_duration_s or 0.0)  # empty transcript: still report duration if we have the wav
        return compute_fluency(
            word_count=0,  # no words
            total_duration_s=total,  # wav duration or 0
            speaking_duration_s=0.0,  # nothing voiced according to ASR
            pause_durations_s=[],  # no word-gap pauses
            filler_count=0,  # no tokens to classify
        )
    first_start = ordered[0][1]  # first word onset
    last_end = ordered[-1][2]  # last word offset
    span = max(last_end - first_start, 0.0)  # ASR timeline span
    total = float(audio_duration_s) if audio_duration_s is not None and audio_duration_s > 0 else span  # prefer wav
    pause_durations: list[float] = []  # gaps between words that pass min_pause_s
    for index in range(len(ordered) - 1):
        gap = ordered[index + 1][1] - ordered[index][2]  # next start minus this end
        if gap >= min_pause_s:
            pause_durations.append(gap)  # treated as a hesitation, not a micro-gap
    pause_sum = sum(pause_durations)  # time excluded from articulation rate
    speaking = max(total - pause_sum, 0.0)  # remaining time treated as speaking
    return compute_fluency(
        word_count=len(ordered),  # one token per ASR word
        total_duration_s=total,  # wav or word-span clock
        speaking_duration_s=speaking,  # total minus word-gap pauses
        pause_durations_s=pause_durations,  # the gaps themselves
        filler_count=count_fillers(tokens),  # um/uh/you know on the transcript
    )


def fluency_from_vad(
    words: list[tuple[str, float, float]],
    speech_segments: list[tuple[float, float]],
    *,
    audio_duration_s: float,
    min_pause_s: float,
    filler_count: int,
) -> FluencyMetrics:
    """Acoustic-derived fluency: pauses and speaking time come from Silero VAD, words still from ASR.

    `speech_segments` is `(start_s, end_s)` voiced islands. `filler_count` is the acoustic proxy
    (short unaligned bursts) — not a second pass over the transcript — so the pair can disagree.
    """
    voiced = sorted(speech_segments, key=lambda item: item[0])  # start time
    speaking = sum(max(end - start, 0.0) for start, end in voiced)  # Silero voiced duration
    pause_durations: list[float] = []  # internal gaps between voiced islands
    for index in range(len(voiced) - 1):
        gap = voiced[index + 1][0] - voiced[index][1]  # next island start minus this island end
        if gap >= min_pause_s:
            pause_durations.append(gap)  # acoustic pause
    return compute_fluency(
        word_count=len(words),  # ASR still supplies the word numerator
        total_duration_s=max(float(audio_duration_s), 0.0),  # wav duration is the acoustic clock
        speaking_duration_s=speaking,  # VAD phonation time
        pause_durations_s=pause_durations,  # VAD internal pauses
        filler_count=filler_count,  # acoustic filler proxy, not transcript fillers
    )


def fluency_to_dict(metrics: FluencyMetrics) -> dict:
    """JSON-safe dict for `answers.speech_metrics` (plain floats/ints, no NaN)."""
    return asdict(metrics)  # dataclass fields already have JSON-friendly names
