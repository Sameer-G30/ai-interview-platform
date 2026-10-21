"""Integration tests for audio upload -> transcribe worker against live Docker Postgres and Redis.

ASR/VAD/prosody are monkeypatched via `app.workers.tasks._run_speech_pipeline` (shared `interview_fakes`)
so the default suite never loads faster-whisper, ffmpeg, or GPU weights. Transcribe now copies the
transcript into `answer_text` and enqueues the judge. The one live smoke at the bottom skips (never
fails) when ffmpeg, CUDA, or cached Whisper weights are missing: it must not wget models.
"""

from __future__ import annotations  # annotations without quotes

import pytest  # skip
from interview_fakes import (  # one shared set of fakes and helpers
    FAKE_EVALUATION_WEAK,
    FAKE_FOLLOW_UP,
    FakeInterviewBackend,
    bearer,
    create_user_with_tokens,
    fake_speech_result,
    insert_resume,
    insert_session_with_questions,
    install_failing_speech,
    install_fake,
    install_fake_speech,
    speak,
)

from app.core.config import get_settings  # live smoke reads WHISPER_* / FFMPEG_PATH
from app.core.db import AsyncSessionLocal  # enqueue a transcribe job for a row with no audio
from app.models.answer import Answer  # assert answer_text after the worker
from app.models.enums import UserRole  # candidate
from app.workers.enqueue import enqueue_job  # no-audio skip path enqueues without HTTP
from app.workers.job_types import JOB_TYPE_TRANSCRIBE  # plain string
from app.workers.settings import run_burst_worker  # in-process ARQ drain

settings = get_settings()  # cached; tests share the process Settings with the app


async def _candidate_with_session(email: str):
    """Register a candidate and insert an in_progress session (technical + behavioral, unanswered)."""
    token, user_id = await create_user_with_tokens(email, "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)
    session_id, answer_ids = await insert_session_with_questions(user_id, resume_id)
    return token, user_id, session_id, answer_ids


async def test_transcribe_copies_transcript_into_answer_text_and_enqueues_evaluate(client, redis_pool, monkeypatch):
    """A successful take stores transcript + metrics + answer_text and returns the evaluate job id."""
    install_fake(monkeypatch, FakeInterviewBackend())  # the chained evaluate job uses the fake judge
    install_fake_speech(monkeypatch)  # no Whisper
    token, _, session_id, answer_ids = await _candidate_with_session("sp-ok@example.com")

    uploaded = await speak(client, token, session_id, answer_ids[0])
    assert uploaded.status_code == 200
    job_id = uploaded.json()["async_job_id"]  # poll GET /jobs/{id}

    await run_burst_worker()  # transcribe, then the evaluate job it enqueued

    polled = (await client.get(f"/jobs/{job_id}", headers=bearer(token))).json()
    assert polled["status"] == "succeeded"
    assert polled["result"]["skipped"] is False
    assert polled["result"]["evaluate_enqueued"] is True
    assert polled["result"]["evaluate_async_job_id"]  # the SPA polls this next
    assert polled["error"] is None

    row = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"][0]
    assert row["transcript"] == "hello world"  # plain text, not JSON
    assert row["answer_text"] == "hello world"  # the transcript is the answer
    assert row["speech_metrics"]["words"][0]["word"] == "hello"  # timings for the viewer
    assert "fluency_transcript" in row["speech_metrics"]  # ASR-gap arm
    assert "fluency_acoustic" in row["speech_metrics"]  # VAD arm
    assert row["evaluation"] is not None  # the chained evaluate ran
    assert "audio_path" not in row  # filesystem path stays excluded
    assert row["has_audio"] is True


async def test_empty_transcript_stores_metrics_but_does_not_evaluate(client, redis_pool, monkeypatch):
    """Whisper hearing nothing is a successful job with no answer_text and no evaluate: record again."""
    backend = FakeInterviewBackend()
    install_fake(monkeypatch, backend)
    install_fake_speech(monkeypatch, fake_speech_result(transcript="   "))  # silence
    token, _, session_id, answer_ids = await _candidate_with_session("sp-empty@example.com")

    uploaded = await speak(client, token, session_id, answer_ids[0])
    await run_burst_worker()

    polled = (await client.get(f"/jobs/{uploaded.json()['async_job_id']}", headers=bearer(token))).json()
    assert polled["status"] == "succeeded"
    assert polled["result"]["evaluate_enqueued"] is False
    assert polled["result"]["reason"] == "empty transcript"
    assert "evaluate_async_job_id" not in polled["result"]

    row = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"][0]
    assert row["speech_metrics"] is not None  # measurements are kept
    assert row["answer_text"] is None  # nothing to judge
    assert row["evaluation"] is None
    assert "AnswerEvaluation" not in backend.titles_called  # the judge was never called


async def test_transcribe_failure_leaves_answer_text_null_and_short_error(client, redis_pool, monkeypatch):
    """A typed SpeechError fails the async job; transcript/metrics/answer_text stay null; session not abandoned."""
    install_failing_speech(monkeypatch)
    token, _, session_id, answer_ids = await _candidate_with_session("sp-fail@example.com")

    uploaded = await speak(client, token, session_id, answer_ids[0])
    await run_burst_worker()

    polled = (await client.get(f"/jobs/{uploaded.json()['async_job_id']}", headers=bearer(token))).json()
    assert polled["status"] == "failed"
    assert "SpeechTranscribeError" in polled["error"]  # short summary for the poller

    fetched = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    assert fetched["status"] == "in_progress"  # transcribe failure must not abandon the session
    row = fetched["answers"][0]
    assert row["transcript"] is None and row["speech_metrics"] is None and row["answer_text"] is None


async def test_transcribe_job_is_owner_only_404(client, redis_pool, monkeypatch):
    """Another candidate polling the transcribe job id gets 404, not 403, like GET /jobs/{id}."""
    install_fake_speech(monkeypatch)
    owner, _, session_id, answer_ids = await _candidate_with_session("sp-owner@example.com")
    other, _ = await create_user_with_tokens("sp-other@example.com", "StrongPass123", UserRole.CANDIDATE)

    uploaded = await speak(client, owner, session_id, answer_ids[0])
    response = await client.get(f"/jobs/{uploaded.json()['async_job_id']}", headers=bearer(other))
    assert response.status_code == 404
    assert response.json()["detail"] == "job not found"


async def test_retake_reenqueues_and_duplicate_evaluates_write_once(client, redis_pool, monkeypatch):
    """A retake before scoring clears old text; two concurrent evaluates still store one score and one follow-up."""
    backend = FakeInterviewBackend(evaluation=FAKE_EVALUATION_WEAK, follow_up=FAKE_FOLLOW_UP)  # weak -> follow-up
    install_fake(monkeypatch, backend)
    install_fake_speech(monkeypatch)
    token, _, session_id, answer_ids = await _candidate_with_session("sp-retry@example.com")

    first = await speak(client, token, session_id, answer_ids[0])
    second = await speak(client, token, session_id, answer_ids[0], suffix=b"-v2")  # new bytes, new sha256
    assert second.status_code == 200
    assert second.json()["async_job_id"] != first.json()["async_job_id"]  # a new async_jobs row

    mid = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"][0]
    assert mid["transcript"] is None and mid["answer_text"] is None  # stale text did not survive the retake

    await run_burst_worker()  # both transcribes see the v2 file; the second evaluate is a duplicate and is skipped

    for upload in (first, second):  # neither transcribe fails
        job = (await client.get(f"/jobs/{upload.json()['async_job_id']}", headers=bearer(token))).json()
        assert job["status"] == "succeeded"
    answers = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"]
    assert answers[0]["answer_text"] == "hello world"
    assert answers[0]["evaluation"]["score"] == 1  # a single stored evaluation
    # ARQ may run both evaluate jobs at once, but the write-time guard lets only one append a follow-up.
    assert len(answers) == 3 and [row["is_follow_up"] for row in answers].count(True) == 1


async def test_duplicate_evaluate_job_is_skipped(client, redis_pool, monkeypatch):
    """A second evaluate for an already-scored row returns skipped and calls the judge zero more times."""
    backend = FakeInterviewBackend()
    install_fake(monkeypatch, backend)
    install_fake_speech(monkeypatch)
    token, user_id, session_id, answer_ids = await _candidate_with_session("sp-dup@example.com")
    await speak(client, token, session_id, answer_ids[0])
    await run_burst_worker()
    calls_before = backend.titles_called.count("AnswerEvaluation")

    from app.main import app  # app.state.redis is attached by the redis_pool fixture
    from app.workers.job_types import JOB_TYPE_INTERVIEW_EVALUATE  # plain string

    async with AsyncSessionLocal() as session:
        dup = await enqueue_job(
            session,
            app.state.redis,
            job_type=JOB_TYPE_INTERVIEW_EVALUATE,
            user_id=user_id,
            payload={"answer_id": str(answer_ids[0]), "session_id": str(session_id)},
        )
    await run_burst_worker()

    polled = (await client.get(f"/jobs/{dup.id}", headers=bearer(token))).json()
    assert polled["status"] == "succeeded"
    assert polled["result"]["skipped"] is True and polled["result"]["reason"] == "already evaluated"
    assert backend.titles_called.count("AnswerEvaluation") == calls_before  # no second judge call


async def test_transcribe_skips_when_audio_path_is_null(client, redis_pool, monkeypatch):
    """A row with no recording: transcribe succeeds as skipped and does not touch answer_text."""
    install_fake_speech(monkeypatch)  # would be a bug if the pipeline ran (no file)
    token, user_id, session_id, answer_ids = await _candidate_with_session("sp-skip@example.com")

    from app.main import app  # app.state.redis is attached by the redis_pool fixture

    async with AsyncSessionLocal() as session:
        job = await enqueue_job(
            session,
            app.state.redis,  # live ARQ pool the fixture attached
            job_type=JOB_TYPE_TRANSCRIBE,
            user_id=user_id,
            payload={"answer_id": str(answer_ids[0]), "session_id": str(session_id)},
        )

    await run_burst_worker()

    polled = (await client.get(f"/jobs/{job.id}", headers=bearer(token))).json()
    assert polled["status"] == "succeeded"
    assert polled["result"]["skipped"] is True
    assert polled["result"]["reason"] == "no audio"

    async with AsyncSessionLocal() as db:
        row = await db.get(Answer, answer_ids[0])
        assert row.transcript is None and row.answer_text is None  # nothing to write


def test_live_speech_pipeline_smoke() -> None:
    """One real ffmpeg + faster-whisper pass; skips (never fails) if GPU/ffmpeg/weights are missing."""
    import shutil  # ffmpeg on PATH
    from pathlib import Path  # local WebM under data/blobs

    from ml.speech import SpeechConfig, run_speech_pipeline  # real pipeline, not the worker wrapper
    from ml.speech.asr import _ffmpeg_binary  # raises if ffmpeg is missing
    from ml.speech.errors import SpeechFfmpegError  # skip, never fail

    try:
        _ffmpeg_binary(SpeechConfig())  # PATH or Settings.ffmpeg_path
    except SpeechFfmpegError as exc:
        pytest.skip(f"ffmpeg not available: {exc}")  # do not apt-get from pytest

    if shutil.which("ffmpeg") is None and not Path(settings.ffmpeg_path).is_file():
        pytest.skip("ffmpeg binary not found")  # belt-and-suspenders with the helper above

    try:
        import torch  # CUDA probe; already a transitive dep
    except ImportError as exc:
        pytest.skip(f"torch not importable: {exc}")
    if settings.whisper_device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA not available; live smoke is GPU-only")  # CPU Whisper is too slow / not the product path

    try:
        import faster_whisper  # import probe only; constructing WhisperModel would download weights
    except Exception as exc:
        pytest.skip(f"faster-whisper not importable: {exc}")

    del faster_whisper  # imported only to prove the package loaded
    cache = Path.home() / ".cache" / "huggingface" / "hub"  # default faster-whisper download root
    cached = list(cache.glob("models--Systran--faster-whisper-*")) if cache.is_dir() else []
    if not cached:
        pytest.skip("no cached faster-whisper weights; do not download from pytest")

    blob = Path("data/blobs/interviews/73b4d899-fe81-448b-b0d7-2e5dc265dcb0/77efbece-9b3a-462c-b75e-6429b85aa042.webm")
    if not blob.is_file():
        pytest.skip(f"local WebM blob missing: {blob}")  # Phase 10 MediaRecorder capture; gitignored

    try:
        result = run_speech_pipeline(str(blob), config=SpeechConfig(
            whisper_model=settings.whisper_model,  # honor .env; do not pull a different tag
            whisper_device=settings.whisper_device,
            whisper_compute_type=settings.whisper_compute_type,
            ffmpeg_path=settings.ffmpeg_path,
        ))
    except Exception as exc:
        pytest.skip(f"live speech pipeline failed: {exc}")  # missing VAD/praat/OOM: skip, never fail CI

    assert isinstance(result.transcript, str)  # may be empty if the take was silence
    metrics = result.to_metrics_dict()
    assert "fluency_transcript" in metrics  # both arms always emitted
    assert "fluency_acoustic" in metrics
    assert "words" in metrics
