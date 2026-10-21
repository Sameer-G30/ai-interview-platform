"""Shared interview LLM fakes for tests. Not collected by pytest (name does not start with test_).

The single home for every interview/speech/score test double: the fake LLM backend (technical +
behavioral by default), the fake speech pipeline (`install_fake_speech`), and the helpers that
register users, insert parsed resumes/sessions, and upload a spoken answer. Tests monkeypatch
`_build_interview_provider` and `_run_speech_pipeline` so no MiniLM, Ollama, or Whisper ever loads.
"""

from __future__ import annotations  # FakeInterviewBackend forward refs

import json  # fake backend returns JSON strings complete_json will parse
from typing import Any  # evaluation dict in fake payloads
from uuid import UUID  # user ids returned by the register helper

import pytest  # MonkeyPatch type
from ml.llm import LLMProvider  # fake wraps LLMProvider
from ml.speech import SpeechPipelineResult, SpeechTranscribeError  # canned pipeline result / typed failure
from ml.speech.asr import AsrResult, WordTimestamp  # nested fakes
from ml.speech.fluency import FluencyMetrics  # dual fluency arms
from ml.speech.prosody import ProsodyMetrics  # Praat summaries
from ml.speech.vad import Pause, SpeechSegment, VadResult  # VAD lists

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import get_settings  # Settings for tokens
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.answer import Answer  # session helpers insert question rows directly
from app.models.enums import InterviewSessionStatus, ResumeStatus, UserRole  # lifecycle + role
from app.models.interview_session import InterviewSession  # session helpers insert sessions directly
from app.models.job import Job  # optional posting
from app.models.resume import Resume  # parsed resume so FKs are valid without spaCy/SBERT

settings = get_settings()  # cached; tests share the process Settings with the app

# Default judge payload: score 4 so follow-up does not fire unless a test overrides it.
FAKE_EVALUATION_OK = {
    "score": 4,  # 0–5
    "rationale": "Covers the core idea with a clear definition.",  # judge prose
    "strengths": ["correct definition"],  # list
    "improvements": ["add a concrete example"],  # list; does not spawn a follow-up
}
# Weak judge payload: score 1 so should_follow_up is True on an original question.
FAKE_EVALUATION_WEAK = {
    "score": 1,  # triggers follow-up
    "rationale": "Does not address the question.",  # judge prose
    "strengths": [],  # empty
    "improvements": ["define the data structure and give an example"],  # coaching
}
# Follow-up question the fake returns when evaluate also calls complete_json(InterviewQuestion).
FAKE_FOLLOW_UP = {
    "question_text": "Can you give a concrete example of using a list versus a tuple?",  # probe
    "question_kind": "technical",  # keep kind
}


class FakeInterviewBackend:
    """Test double: JSON per schema title. Tests monkeypatch `_build_interview_provider` to wrap this."""

    name = "fake"  # not a real LLM_PROVIDER value; only injected via get_provider(backend=...)

    def __init__(
        self,
        *,
        questions: list[dict[str, str]] | None = None,
        evaluation: dict[str, Any] | None = None,
        follow_up: dict[str, str] | None = None,
        raw_by_title: dict[str, str] | None = None,
    ) -> None:
        self.questions = questions if questions is not None else [
            {"question_text": "What is a Python list?", "question_kind": "technical"},
            {"question_text": "Tell me about a time you resolved a conflict.", "question_kind": "behavioral"},
        ]
        self.evaluation = evaluation if evaluation is not None else dict(FAKE_EVALUATION_OK)  # AnswerEvaluation
        self.follow_up = follow_up if follow_up is not None else dict(FAKE_FOLLOW_UP)  # InterviewQuestion
        self.raw_by_title = raw_by_title or {}  # optional invalid JSON per schema title
        self.titles_called: list[str] = []  # order of complete_json schemas this backend saw
        self.last_messages: list[dict[str, str]] | None = None  # last generate() messages, for prompt assertions

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        del temperature  # fake is deterministic
        self.last_messages = messages  # includes the JSON-contract system turn prepended by complete_json
        title = (json_schema or {}).get("title") or ""  # Pydantic v2 uses the class name
        self.titles_called.append(title)  # generate then evaluate then maybe follow-up
        if title in self.raw_by_title:
            return self.raw_by_title[title]  # not valid JSON -> LLMJSONError
        if title == "GeneratedQuestions":
            return json.dumps({"questions": self.questions})  # 1-6 InterviewQuestion items
        if title == "AnswerEvaluation":
            return json.dumps(self.evaluation)  # score 0-5 + rationale + lists
        if title == "InterviewQuestion":
            return json.dumps(self.follow_up)  # single follow-up question
        raise AssertionError(f"unexpected json_schema title {title!r}")  # unexpected response_model

    def close(self) -> None:
        return None  # production backends close an owned httpx.Client; the fake owns nothing


def install_fake(monkeypatch: pytest.MonkeyPatch, backend: FakeInterviewBackend) -> FakeInterviewBackend:
    """Point the worker's provider factory at this fake so burst workers never open HTTP."""
    monkeypatch.setattr(
        "app.workers.tasks._build_interview_provider",
        lambda: LLMProvider(backend),  # same facade the product uses; complete_json still enforces Pydantic
    )
    return backend  # caller may assert titles_called


async def create_user_with_tokens(email: str, password: str, role: UserRole) -> tuple[str, UUID]:
    """Register a user via the service layer and return (access_token, user_id)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Scoring Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
        return access_token, user.id


def bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the score/report routes expect."""
    return {"Authorization": f"Bearer {access_token}"}


def fake_fluency() -> FluencyMetrics:
    """Deterministic fluency payload so tests can assert JSON keys without running Praat."""
    return FluencyMetrics(
        speech_rate_wpm=130.0,  # inside the 110-160 plateau
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


def fake_speech_result(transcript: str = "hello world") -> SpeechPipelineResult:
    """Canned pipeline output. `install_fake_speech` returns this from `_run_speech_pipeline`."""
    words = [
        WordTimestamp(word="hello", start=0.0, end=0.4, probability=0.9),  # first token
        WordTimestamp(word="world", start=0.6, end=1.0, probability=0.8),  # second token
    ]
    return SpeechPipelineResult(
        transcript=transcript,  # written to answers.transcript and copied into answer_text
        asr=AsrResult(transcript=transcript, words=words, language="en", duration_s=1.0),  # Whisper arm
        vad=VadResult(
            speech_segments=[SpeechSegment(start=0.0, end=1.0)],  # one island
            pauses=[Pause(start=0.4, end=0.6, duration=0.2)],  # internal gap
            duration_s=1.0,  # wav clock
        ),
        prosody=ProsodyMetrics(pitch_mean_hz=140.0, pitch_std_hz=10.0, intensity_mean_db=55.0, intensity_std_db=4.0),
        fluency_transcript=fake_fluency(),  # ASR-gap arm
        fluency_acoustic=fake_fluency(),  # VAD arm (same numbers in the fake)
    )


def install_fake_speech(
    monkeypatch: pytest.MonkeyPatch, result: SpeechPipelineResult | None = None
) -> SpeechPipelineResult:
    """Point the worker at a canned pipeline so burst tests never load Whisper."""
    canned = result if result is not None else fake_speech_result()  # default "hello world"

    def _run(_audio_path: str) -> SpeechPipelineResult:
        return canned  # ignore the tiny test webm; content-type is what upload validated

    monkeypatch.setattr("app.workers.tasks._run_speech_pipeline", _run)  # looked up inside to_thread
    return canned


def install_failing_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the worker raise a typed SpeechError so the async job fails with a short message."""

    def _run(_audio_path: str) -> SpeechPipelineResult:
        raise SpeechTranscribeError("ffmpeg is not installed")  # short message lands on async_jobs.error

    monkeypatch.setattr("app.workers.tasks._run_speech_pipeline", _run)  # same patch point as success


def tiny_webm(suffix: bytes = b"") -> bytes:
    """A few bytes labelled as WebM; upload does not parse the container and the pipeline is faked."""
    return b"webm-test-bytes" + suffix  # a different suffix changes the sha256 for retake tests


async def insert_resume(user_id: UUID, *, parsed: bool = True, ats_score: float | None = 70.0) -> UUID:
    """Insert a resume row directly so tests never run spaCy or MiniLM."""
    async with AsyncSessionLocal() as session:
        resume = Resume(
            user_id=user_id,
            file_path="/tmp/fake-resume.pdf",  # never opened
            original_filename="resume.pdf",
            status=ResumeStatus.PARSED if parsed else ResumeStatus.UPLOADED,
            parsed_data={"skills": ["Python"], "sections": {}} if parsed else None,
            ats_score=ats_score if parsed else None,
        )
        session.add(resume)
        await session.commit()
        return resume.id


async def insert_posting(
    recruiter_id: UUID,
    *,
    title: str = "Backend Engineer",
    description: str = "Build APIs",
    required_skills: str = "Python, SQL",
    is_active: bool = True,
) -> UUID:
    """Insert a posting without an embedding (interviews do not need one)."""
    async with AsyncSessionLocal() as session:
        posting = Job(
            recruiter_id=recruiter_id,
            title=title,
            description=description,
            required_skills=required_skills,
            is_active=is_active,
        )
        session.add(posting)
        await session.commit()
        return posting.id


async def insert_session_with_questions(
    user_id: UUID,
    resume_id: UUID,
    *,
    kinds: tuple[str, ...] = ("technical", "behavioral"),
    job_id: UUID | None = None,
) -> tuple[UUID, list[UUID]]:
    """Insert an in_progress session with one unanswered question per kind (skips the generate worker)."""
    async with AsyncSessionLocal() as session:
        interview = InterviewSession(
            user_id=user_id, resume_id=resume_id, job_id=job_id, status=InterviewSessionStatus.IN_PROGRESS
        )
        session.add(interview)
        await session.flush()  # need interview.id before the answers FK
        answers = [
            Answer(
                session_id=interview.id,
                question_order=order,
                question_text=f"Question {order} ({kind})?",
                question_kind=kind,
                is_follow_up=False,
            )
            for order, kind in enumerate(kinds)
        ]
        session.add_all(answers)
        await session.commit()
        return interview.id, [row.id for row in answers]


async def speak(client, token: str, session_id: UUID | str, answer_id: UUID | str, *, suffix: bytes = b""):
    """POST a (fake) WebM for one answer exactly as the SPA's recorder does; returns the HTTP response."""
    return await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", tiny_webm(suffix), "audio/webm")},
        headers=bearer(token),
    )
