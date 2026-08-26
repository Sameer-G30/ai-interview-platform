"""ARQ task functions registered on WorkerSettings.

Phase 4 shipped demo jobs only. The resume-pipeline phase adds `resume_parse`, the first task that
actually calls into `ml/`. Phase 9 adds `interview_generate` / `interview_evaluate`, which call
`ml.llm` inside `asyncio.to_thread` and never run in a FastAPI request handler.
"""

import asyncio  # optional sleep for the demo jobs; asyncio.to_thread runs the sync ml/ work
import logging  # worker-side log line when a resume fails to parse (short reason only, no traceback here)
import uuid  # resume_id / job_id / session_id in the job payload are UUID strings on the wire
from datetime import UTC, datetime  # started_at / completed_at written by the interview workers

from ml.interview import build_followup_messages, build_generate_messages, rubric_name_for_kind, should_follow_up
from ml.llm import (  # Phase 8 provider; constructed inside the handler, never at this module's import time
    AnswerEvaluation,
    GeneratedQuestions,
    InterviewQuestion,
    LLMProvider,
    config_from_settings,
    evaluate_answer,
    get_provider,
)
from ml.matching.embed import embed_text  # lazy-loaded SBERT singleton, used for both resumes and postings
from ml.resume import ResumeParseError, run_resume_pipeline  # PyMuPDF/pypdfium2 + spaCy + ESCO + ATS, one call
from sqlalchemy import func, select  # max(question_order) when appending a follow-up row

from app.core.config import get_settings  # Settings -> LLMConfig via config_from_settings (not os.environ)
from app.core.db import AsyncSessionLocal  # worker opens its own sessions; it is not a request
from app.models.answer import Answer  # rows generate writes and evaluate scores
from app.models.enums import InterviewSessionStatus, ResumeStatus  # session + resume lifecycle
from app.models.interview_session import InterviewSession  # row generate/evaluate advance
from app.models.job import Job  # row posting_embed loads and writes embedding onto; interview reads title/skills
from app.models.resume import Resume  # row this task advances through its lifecycle
from app.workers.tracked import run_tracked_job  # shared running/succeeded/failed status wrapper

logger = logging.getLogger(__name__)  # module logger, mirrors app.workers.tracked's convention


async def demo_echo(ctx: dict) -> dict:
    """Throwaway success path: echo payload["message"] after payload["sleep_ms"] (capped)."""

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}  # enqueue always stores a dict, but the column is nullable
        sleep_ms = int(body.get("sleep_ms") or 0)  # tests pass 0; the SPA demo may pass a short delay
        if sleep_ms > 0:
            await asyncio.sleep(min(sleep_ms, 5000) / 1000)  # cap at 5s so a bad payload cannot stall the worker
        message = body.get("message", "ok")  # default keeps the job useful even with an empty body
        return {"echo": message}  # JSON-safe result written to async_jobs.result

    return await run_tracked_job(ctx, _handle)  # ctx["job_id"] is the Postgres UUID string


async def demo_fail(ctx: dict) -> dict:
    """Throwaway failure path: always raises so tests can assert status=failed and error is set."""

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}  # optional reason from the test enqueue payload
        reason = str(body.get("reason") or "demo job failed on purpose")  # stable default for assertions
        raise RuntimeError(reason)  # run_tracked_job catches this, writes FAILED, then re-raises

    return await run_tracked_job(ctx, _handle)  # never returns; ARQ sees the exception after Postgres is updated


async def _set_resume_status(resume_id: uuid.UUID, status: ResumeStatus, **extra: object) -> None:
    """Load one `resumes` row in its own session and update status (+ optional extra columns)."""
    async with AsyncSessionLocal() as session:
        resume = await session.get(Resume, resume_id)
        if resume is None:
            raise RuntimeError(f"resume {resume_id} was not found")  # POST /resumes must commit before enqueue
        resume.status = status
        for column, value in extra.items():
            setattr(resume, column, value)
        await session.commit()


def _resume_embedding_text(parsed_data: dict) -> str:
    """Concatenate a parsed resume's section bodies and matched skills into one string to embed.

    Sections carry the free-text substance (experience, summary, ...); skills are appended again on
    their own so a short resume with terse sections still gets skill-heavy signal in the embedding.
    """
    section_text = " ".join(body for body in parsed_data["sections"].values() if body)
    skills_text = ", ".join(parsed_data["skills"])
    return f"{section_text}\n\nSkills: {skills_text}".strip()


async def resume_parse(ctx: dict) -> dict:
    """Extract text, section it, match ESCO skills, ATS-score, and SBERT-embed one uploaded resume PDF.

    Mirrors `run_tracked_job`'s async_jobs bookkeeping but *also* advances the linked `resumes` row
    (uploaded -> processing -> parsed/failed) since the candidate-facing results endpoint reads
    `resumes`, not `async_jobs`, directly. `ml/resume` and `ml/matching.embed` are both synchronous
    (PyMuPDF, spaCy, sentence-transformers); `asyncio.to_thread` keeps them from blocking the
    worker's event loop for other concurrent jobs. The embedding step runs in this same task (no
    separate job type) so `/matches` never has to special-case a resume that parsed but isn't
    embedded yet - by the time status is `parsed`, `embedding` is always set too.
    """

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}
        resume_id = uuid.UUID(str(body["resume_id"]))  # enqueue helper always sets this key
        async with AsyncSessionLocal() as session:  # separate short session just to read file_path
            resume = await session.get(Resume, resume_id)
            if resume is None:
                raise RuntimeError(f"resume {resume_id} was not found")
            file_path = resume.file_path
        await _set_resume_status(resume_id, ResumeStatus.PROCESSING)  # visible to GET /resumes/{id} immediately
        try:
            parsed_data, ats_score = await asyncio.to_thread(run_resume_pipeline, file_path)
            embedding = await asyncio.to_thread(embed_text, _resume_embedding_text(parsed_data))
        except ResumeParseError as exc:
            logger.warning("resume %s failed to parse: %s", resume_id, exc)  # expected failure mode, not a bug
            await _set_resume_status(resume_id, ResumeStatus.FAILED)
            raise
        except Exception:
            logger.exception("resume %s parse worker crashed unexpectedly", resume_id)  # unexpected: full traceback
            await _set_resume_status(resume_id, ResumeStatus.FAILED)
            raise
        await _set_resume_status(
            resume_id, ResumeStatus.PARSED, parsed_data=parsed_data, ats_score=ats_score, embedding=embedding
        )
        return {"resume_id": str(resume_id), "ats_score": ats_score, "skill_count": len(parsed_data["skills"])}

    return await run_tracked_job(ctx, _handle)  # async_jobs row mirrors the same succeeded/failed outcome


async def _set_job_embedding(job_id: uuid.UUID, embedding: list[float]) -> None:
    """Load one `jobs` row in its own session and write its computed embedding."""
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise RuntimeError(f"job {job_id} was not found")  # POST /postings must commit before enqueue
        job.embedding = embedding
        await session.commit()


async def posting_embed(ctx: dict) -> dict:
    """Embed one job posting's title+description+required_skills text into `jobs.embedding`.

    Unlike `resume_parse`, this task does not flip a status column - `jobs.is_active` already exists
    and is unrelated to embedding progress; `jobs.embedding` being NULL *is* the "not embedded yet"
    signal `/matches` checks for. `run_tracked_job` still gives this a normal async_jobs row so the
    recruiter UI can poll `GET /jobs/{async_job_id}` the same way resume upload does.
    """

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}
        job_id = uuid.UUID(str(body["job_id"]))  # enqueue helper always sets this key
        async with AsyncSessionLocal() as session:  # separate short session just to read the posting text
            job = await session.get(Job, job_id)
            if job is None:
                raise RuntimeError(f"job {job_id} was not found")
            text = f"{job.title}\n\n{job.description}\n\nRequired skills: {job.required_skills or ''}".strip()
        embedding = await asyncio.to_thread(embed_text, text)
        await _set_job_embedding(job_id, embedding)
        return {"job_id": str(job_id), "embedding_dim": len(embedding)}

    return await run_tracked_job(ctx, _handle)  # async_jobs row mirrors the same succeeded/failed outcome


def _build_interview_provider() -> LLMProvider:
    """Construct the Phase 8 provider from Settings. Called inside a worker handler, never at import.

    Tests monkeypatch this name on `app.workers.tasks` so generate/evaluate never hit live Ollama.
    Product code uses `config_from_settings(get_settings())` because pydantic-settings does not copy
    `.env` into `os.environ`.
    """
    return get_provider(config_from_settings(get_settings()))  # still lazy: no HTTP until complete_json


def _generate_questions_sync(
    resume_skills: list[str],
    posting_title: str | None,
    posting_description: str | None,
    posting_required_skills: str | None,
) -> GeneratedQuestions:
    """Sync complete_json call; the async worker wraps this in asyncio.to_thread."""
    provider = _build_interview_provider()  # looked up at call time so tests can monkeypatch it
    try:
        messages = build_generate_messages(
            resume_skills=resume_skills,
            posting_title=posting_title,
            posting_description=posting_description,
            posting_required_skills=posting_required_skills,
        )
        return provider.complete_json(messages, GeneratedQuestions)  # LLMJSON/Schema/ProviderError propagate
    finally:
        provider.close()  # drop the owned httpx client even when complete_json raises


def _evaluate_and_maybe_followup_sync(
    question_text: str,
    answer_text: str,
    question_kind: str,
    is_follow_up: bool,
) -> tuple[AnswerEvaluation, InterviewQuestion | None]:
    """Score one answer; if should_follow_up, generate one InterviewQuestion in the same pass."""
    provider = _build_interview_provider()  # one provider for evaluate + optional follow-up
    try:
        evaluation = evaluate_answer(
            question_text,
            answer_text,
            rubric_name=rubric_name_for_kind(question_kind),
            provider=provider,  # honor Settings; do not construct from os.environ
        )
        follow_up: InterviewQuestion | None = None  # None means do not append a row
        if should_follow_up(evaluation, is_follow_up=is_follow_up):
            follow_up = provider.complete_json(
                build_followup_messages(
                    question_text=question_text,
                    answer_text=answer_text,
                    evaluation=evaluation,
                    question_kind=question_kind,
                ),
                InterviewQuestion,
            )
        return evaluation, follow_up
    finally:
        provider.close()  # unload keep_alive=0 still happens per backend call; close the HTTP client here


async def _abandon_session(session_id: uuid.UUID) -> None:
    """Mark a session abandoned when generate fails so it cannot sit in scheduled forever."""
    async with AsyncSessionLocal() as session:
        interview = await session.get(InterviewSession, session_id)
        if interview is None:
            return  # row vanished; generate will still fail via run_tracked_job
        interview.status = InterviewSessionStatus.ABANDONED
        await session.commit()


async def interview_generate(ctx: dict) -> dict:
    """Generate interview questions from posting + resume skills and persist them as answers rows.

    The request handler only inserts the session. This task calls `complete_json(GeneratedQuestions)`
    in a thread, writes one `answers` row per question (`answer_text` NULL), and flips the session
    `scheduled -> in_progress` with `started_at` set. LLMJSONError / LLMSchemaError / LLMProviderError
    mark the async job failed (via run_tracked_job) and the session abandoned.
    """

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}
        session_id = uuid.UUID(str(body["session_id"]))  # enqueue helper always sets this key
        async with AsyncSessionLocal() as session:  # short session to copy the facts the LLM needs
            interview = await session.get(InterviewSession, session_id)
            if interview is None:
                raise RuntimeError(f"interview session {session_id} was not found")
            resume = await session.get(Resume, interview.resume_id)
            if resume is None:
                raise RuntimeError(f"resume {interview.resume_id} was not found")
            posting = await session.get(Job, interview.job_id) if interview.job_id is not None else None
            resume_skills = list((resume.parsed_data or {}).get("skills") or [])  # ESCO preferred labels
            posting_title = posting.title if posting is not None else None
            posting_description = posting.description if posting is not None else None
            posting_required_skills = posting.required_skills if posting is not None else None
        try:
            generated = await asyncio.to_thread(
                _generate_questions_sync,
                resume_skills,
                posting_title,
                posting_description,
                posting_required_skills,
            )
        except Exception:
            await _abandon_session(session_id)  # generate failed: do not leave a scheduled shell
            raise  # run_tracked_job writes FAILED + a short error; no free-text fallback
        async with AsyncSessionLocal() as session:  # persist questions + flip in_progress in one commit
            interview = await session.get(InterviewSession, session_id)
            if interview is None:
                raise RuntimeError(f"interview session {session_id} disappeared")
            for order, item in enumerate(generated.questions):  # 0-based question_order
                session.add(
                    Answer(
                        session_id=session_id,
                        question_order=order,
                        question_text=item.question_text,
                        question_kind=item.question_kind,  # technical | behavioral from the schema
                        is_follow_up=False,
                    )
                )
            interview.status = InterviewSessionStatus.IN_PROGRESS  # first generated question is ready
            interview.started_at = datetime.now(UTC)  # distinct from created_at (row insert time)
            await session.commit()
        return {
            "session_id": str(session_id),
            "question_count": len(generated.questions),
            "session_status": InterviewSessionStatus.IN_PROGRESS.value,
        }

    return await run_tracked_job(ctx, _handle)


async def interview_evaluate(ctx: dict) -> dict:
    """Score one submitted text answer and maybe append a follow-up question in the same pass.

    Follow-up rule: `should_follow_up` is True when score <= 2 and the question is not already a
    follow-up. The follow-up is generated here (not in the request handler) via complete_json.
    When every current question has answer_text and no follow-up was appended, the session becomes
    completed. LLM errors fail the async job; they do not clamp scores or store prose.
    """

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}
        answer_id = uuid.UUID(str(body["answer_id"]))  # enqueue helper always sets this key
        async with AsyncSessionLocal() as session:  # copy strings; do not pass ORM objects into to_thread
            answer = await session.get(Answer, answer_id)
            if answer is None:
                raise RuntimeError(f"answer {answer_id} was not found")
            if answer.answer_text is None:
                raise RuntimeError(f"answer {answer_id} has no answer_text")  # submit must commit first
            question_text = answer.question_text
            answer_text = answer.answer_text
            question_kind = answer.question_kind
            is_follow_up = answer.is_follow_up
            session_id = answer.session_id
        evaluation, follow_up = await asyncio.to_thread(
            _evaluate_and_maybe_followup_sync,
            question_text,
            answer_text,
            question_kind,
            is_follow_up,
        )
        async with AsyncSessionLocal() as session:
            answer = await session.get(Answer, answer_id)
            interview = await session.get(InterviewSession, session_id)
            if answer is None or interview is None:
                raise RuntimeError(f"answer {answer_id} or session {session_id} disappeared")
            answer.evaluation = evaluation.model_dump()  # {score, rationale, strengths, improvements}
            follow_up_appended = False  # stays False unless we insert a new answers row below
            if follow_up is not None:
                max_order = await session.scalar(
                    select(func.max(Answer.question_order)).where(Answer.session_id == session_id)
                )
                next_order = int(max_order) + 1 if max_order is not None else 0  # append after current last
                session.add(
                    Answer(
                        session_id=session_id,
                        question_order=next_order,
                        question_text=follow_up.question_text,
                        question_kind=follow_up.question_kind,
                        is_follow_up=True,  # should_follow_up will refuse to chain off this row
                    )
                )
                follow_up_appended = True
            if not follow_up_appended:
                unanswered = await session.scalar(
                    select(func.count())
                    .select_from(Answer)
                    .where(Answer.session_id == session_id, Answer.answer_text.is_(None))
                )
                if int(unanswered or 0) == 0:  # every current question has text; no new follow-up
                    interview.status = InterviewSessionStatus.COMPLETED
                    interview.completed_at = datetime.now(UTC)
            session_status = interview.status.value  # copy before commit; expire_on_commit would lazy-load
            await session.commit()
        return {
            "session_id": str(session_id),
            "answer_id": str(answer_id),
            "score": evaluation.score,
            "follow_up_appended": follow_up_appended,
            "session_status": session_status,  # in_progress or completed after this pass
        }

    return await run_tracked_job(ctx, _handle)
