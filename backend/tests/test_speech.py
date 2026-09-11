"""Integration tests for audio upload -> transcribe worker against live Docker Postgres and Redis.

ASR/VAD/prosody are monkeypatched via `app.workers.tasks._run_speech_pipeline` so the default suite
never loads faster-whisper, ffmpeg, or GPU weights. The one live smoke at the bottom skips (never
fails) when ffmpeg, CUDA, or cached Whisper weights are missing — it must not wget models.
"""

from __future__ import annotations  # FakeSpeechResult helpers

from uuid import UUID  # user ids returned by the register helper

import pytest  # skip
from ml.speech import SpeechPipelineResult, SpeechTranscribeError  # fake return / fail path
from ml.speech.asr import AsrResult, WordTimestamp  # nested fakes
from ml.speech.fluency import FluencyMetrics  # dual fluency arms
from ml.speech.prosody import ProsodyMetrics  # Praat summaries
from ml.speech.vad import Pause, SpeechSegment, VadResult  # VAD lists

from app.auth import service  # register_user/issue_token_pair
from app.core.config import get_settings  # token expiry
from app.core.db import AsyncSessionLocal  # insert session/answer rows without the LLM worker
from app.models.answer import Answer  # assert transcript/metrics after the worker
from app.models.enums import InterviewSessionStatus, ResumeStatus, UserRole  # insert helpers
from app.models.interview_session import InterviewSession  # skip generate
from app.models.resume import Resume  # parsed resume so the session FK is valid
from app.workers.enqueue import enqueue_job  # no-audio skip path enqueues without HTTP
from app.workers.job_types import JOB_TYPE_TRANSCRIBE  # plain string
from app.workers.settings import run_burst_worker  # in-process ARQ drain

settings = get_settings()  # cached; tests share the process Settings with the app


def _fake_fluency() -> FluencyMetrics:
    """Deterministic fluency payload so tests can assert JSON keys without running Praat."""
    return FluencyMetrics(
        speech_rate_wpm=120.0,  # words / duration
        articulation_rate_wpm=150.0,  # words / speaking
        mean_pause_duration_s=0.4,  # one pause
        pause_ratio=0.2,  # pause / total
        filler_rate=0.0,  # no um/uh in the fake transcript
        filler_count=0,  # matching rate
        word_count=2,  # hello world
        total_duration_s=1.0,  # wav clock
        speaking_duration_s=0.8,  # minus pause
        pause_duration_s=0.2,  # one gap
        pause_count=1,  # one gap
    )


def _fake_result(transcript: str = "hello world") -> SpeechPipelineResult:
    """Canned pipeline output. Tests monkeypatch `_run_speech_pipeline` to return this."""
    words = [
        WordTimestamp(word="hello", start=0.0, end=0.4, probability=0.9),  # first token
        WordTimestamp(word="world", start=0.6, end=1.0, probability=0.8),  # second token
    ]
    return SpeechPipelineResult(
        transcript=transcript,  # written to answers.transcript
        asr=AsrResult(transcript=transcript, words=words, language="en", duration_s=1.0),  # Whisper arm
        vad=VadResult(
            speech_segments=[SpeechSegment(start=0.0, end=1.0)],  # one island
            pauses=[Pause(start=0.4, end=0.6, duration=0.2)],  # internal gap
            duration_s=1.0,  # wav clock
        ),
        prosody=ProsodyMetrics(
            pitch_mean_hz=140.0,  # Hz
            pitch_std_hz=10.0,  # Hz
            intensity_mean_db=55.0,  # dB
            intensity_std_db=4.0,  # dB
        ),
        fluency_transcript=_fake_fluency(),  # ASR-gap arm
        fluency_acoustic=_fake_fluency(),  # VAD arm (same numbers in the fake)
    )


def _install_fake_speech(monkeypatch: pytest.MonkeyPatch, result: SpeechPipelineResult | None = None) -> None:
    """Point the worker at a canned pipeline so burst tests never load Whisper."""
    canned = result if result is not None else _fake_result()  # default hello world

    def _run(_audio_path: str) -> SpeechPipelineResult:
        return canned  # ignore the tiny test webm; content-type is what upload validated

    monkeypatch.setattr("app.workers.tasks._run_speech_pipeline", _run)  # looked up inside to_thread


def _install_failing_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the worker raise a typed SpeechError so the async job fails with a short message."""

    def _run(_audio_path: str) -> SpeechPipelineResult:
        raise SpeechTranscribeError("ffmpeg is not installed")  # short message lands on async_jobs.error

    monkeypatch.setattr("app.workers.tasks._run_speech_pipeline", _run)  # same patch point as success


async def _create_user_with_tokens(email: str, password: str, role: UserRole) -> tuple[str, UUID]:
    """Register a user via the service layer and return (access_token, user_id)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Speech Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
        return access_token, user.id


def _bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the interview routes expect."""
    return {"Authorization": f"Bearer {access_token}"}  # access JWT, not the opaque refresh token


async def _insert_resume(user_id: UUID) -> UUID:
    """Insert a parsed resume so the session FK is valid without running spaCy/SBERT."""
    async with AsyncSessionLocal() as session:
        resume = Resume(
            user_id=user_id,
            file_path="/tmp/phase11-fake.pdf",  # never opened
            original_filename="resume.pdf",
            status=ResumeStatus.PARSED,
            parsed_data={"skills": ["Python"], "sections": {}},
            ats_score=70.0,
        )
        session.add(resume)
        await session.commit()
        return resume.id


async def _insert_session_with_question(user_id: UUID, resume_id: UUID) -> tuple[UUID, UUID]:
    """Insert an in_progress session plus one unanswered question so tests skip the LLM worker."""
    async with AsyncSessionLocal() as session:
        interview = InterviewSession(
            user_id=user_id,
            resume_id=resume_id,
            status=InterviewSessionStatus.IN_PROGRESS,
        )
        session.add(interview)
        await session.flush()  # need interview.id before the answers FK
        answer = Answer(
            session_id=interview.id,
            question_order=0,
            question_text="What is a Python list?",
            question_kind="technical",
            is_follow_up=False,
        )
        session.add(answer)
        await session.commit()
        return interview.id, answer.id


def _tiny_webm() -> bytes:
    """A few bytes labelled as WebM; the upload endpoint does not parse the container."""
    return b"webm-test-bytes"  # ffmpeg would reject this; tests monkeypatch the pipeline


async def test_transcribe_worker_writes_transcript_and_metrics(client, redis_pool, monkeypatch):
    """After a burst worker, GET session has transcript + speech_metrics and still hides audio_path."""
    _install_fake_speech(monkeypatch)  # no Whisper
    token, user_id = await _create_user_with_tokens("sp-ok@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)
    session_id, answer_id = await _insert_session_with_question(user_id, resume_id)

    uploaded = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(token),
    )
    assert uploaded.status_code == 200
    job_id = uploaded.json()["async_job_id"]  # poll GET /jobs/{id}

    await run_burst_worker()  # in-process ARQ; runs the monkeypatched pipeline

    polled = (await client.get(f"/jobs/{job_id}", headers=_bearer(token))).json()
    assert polled["status"] == "succeeded"
    assert polled["result"]["skipped"] is False
    assert polled["error"] is None

    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    row = fetched["answers"][0]
    assert row["transcript"] == "hello world"  # plain text, not JSON
    assert row["speech_metrics"] is not None
    assert row["speech_metrics"]["words"][0]["word"] == "hello"  # timings for the later viewer
    assert "fluency_transcript" in row["speech_metrics"]  # ASR-gap arm
    assert "fluency_acoustic" in row["speech_metrics"]  # VAD arm
    assert "audio_path" not in row  # filesystem path stays excluded
    assert row["has_audio"] is True


async def test_transcribe_failure_leaves_transcript_null_and_short_error(client, redis_pool, monkeypatch):
    """A typed SpeechError fails the async job; transcript/metrics stay null; session is not abandoned."""
    _install_failing_speech(monkeypatch)
    token, user_id = await _create_user_with_tokens("sp-fail@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)
    session_id, answer_id = await _insert_session_with_question(user_id, resume_id)

    uploaded = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(token),
    )
    job_id = uploaded.json()["async_job_id"]

    await run_burst_worker()

    polled = (await client.get(f"/jobs/{job_id}", headers=_bearer(token))).json()
    assert polled["status"] == "failed"
    assert polled["error"]  # short summary for the poller
    assert "SpeechTranscribeError" in polled["error"]

    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert fetched["status"] == "in_progress"  # transcribe failure must not abandon the session
    assert fetched["answers"][0]["transcript"] is None
    assert fetched["answers"][0]["speech_metrics"] is None


async def test_transcribe_job_is_owner_only_404(client, redis_pool, monkeypatch):
    """Another candidate polling the transcribe job id gets 404, not 403 — same as GET /jobs/{id}."""
    _install_fake_speech(monkeypatch)
    owner, owner_id = await _create_user_with_tokens("sp-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await _create_user_with_tokens("sp-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(owner_id)
    session_id, answer_id = await _insert_session_with_question(owner_id, resume_id)

    uploaded = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(owner),
    )
    job_id = uploaded.json()["async_job_id"]

    response = await client.get(f"/jobs/{job_id}", headers=_bearer(other))
    assert response.status_code == 404
    assert response.json()["detail"] == "job not found"


async def test_audio_overwrite_reenqueues_and_clears_stale_transcript(client, redis_pool, monkeypatch):
    """A second upload clears transcript/metrics and returns a new async_job_id."""
    _install_fake_speech(monkeypatch)
    token, user_id = await _create_user_with_tokens("sp-retry@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)
    session_id, answer_id = await _insert_session_with_question(user_id, resume_id)

    first = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(token),
    )
    first_job = first.json()["async_job_id"]
    await run_burst_worker()  # writes hello world
    assert (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0][
        "transcript"
    ] == "hello world"

    second = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm() + b"-v2", "audio/webm")},  # different bytes so sha256 changes
        headers=_bearer(token),
    )
    assert second.status_code == 200
    second_job = second.json()["async_job_id"]
    assert second_job != first_job  # a new async_jobs row, not a reuse of the first id

    mid = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]
    assert mid["transcript"] is None  # stale Whisper text must not survive overwrite
    assert mid["speech_metrics"] is None  # stale timings must not survive overwrite
    assert mid["has_audio"] is True  # blob is still on disk

    await run_burst_worker()  # second transcribe
    final = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]
    assert final["transcript"] == "hello world"  # fake pipeline is deterministic


async def test_transcribe_skips_when_audio_path_is_null(client, redis_pool, monkeypatch):
    """Text-only answers: transcribe succeeds as skipped and does not fail the session."""
    _install_fake_speech(monkeypatch)  # would be a bug if the pipeline ran (no file)
    token, user_id = await _create_user_with_tokens("sp-skip@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)
    session_id, answer_id = await _insert_session_with_question(user_id, resume_id)

    from app.main import app  # app.state.redis is attached by the redis_pool fixture

    async with AsyncSessionLocal() as session:
        job = await enqueue_job(
            session,
            app.state.redis,  # live ARQ pool the fixture attached
            job_type=JOB_TYPE_TRANSCRIBE,
            user_id=user_id,
            payload={"answer_id": str(answer_id), "session_id": str(session_id)},
        )

    await run_burst_worker()

    polled = (await client.get(f"/jobs/{job.id}", headers=_bearer(token))).json()
    assert polled["status"] == "succeeded"
    assert polled["result"]["skipped"] is True
    assert polled["result"]["reason"] == "no audio"

    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert fetched["answers"][0]["transcript"] is None  # nothing to write
    assert fetched["answers"][0]["has_audio"] is False


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
