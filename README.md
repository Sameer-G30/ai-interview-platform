# AI Interview Intelligence Platform

Status: **early scaffolding (Phase 1 of 15)**. This is a placeholder README; the full
architecture diagram, setup guide, and demo script are written in the hardening phase
per the build plan.

## What this is

A FastAPI + ARQ + `ml/` backend and a React/Vite/shadcn frontend implementing an
end-to-end AI-assisted interview platform: resume parsing, job matching, an LLM-driven
interview engine, speech/prosody analysis, and weighted scoring with reports.

## Layout

- `backend/` — FastAPI app, Alembic migrations, tests
- `ml/` — pluggable ML code (LLM provider, resume parsing, matching, speech, scoring),
  shared by the backend workers and a separate research harness
- `frontend/` — React + Vite + TypeScript + Tailwind + shadcn/ui
- `docker-compose.yml` — local Postgres+pgvector and Redis

## Local dev (Phase 1 slice)

```bash
uv sync                 # create .venv and install backend/ml dependencies
docker compose up -d    # start Postgres+pgvector and Redis
uv run uvicorn app.main:app --reload --app-dir backend
```
