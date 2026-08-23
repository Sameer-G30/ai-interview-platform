# AI Interview Intelligence Platform

Status: **Phase 2 of 15 complete (auth-data)**. Full architecture diagram, seed/demo scripts, and
deployment profile land in the hardening phase per the build plan.

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

## What's implemented so far

### Phase 1 — scaffolding

- Backend skeleton (`GET /health`), Docker Compose (Postgres+pgvector, Redis), Alembic baseline
  migration enabling the `vector` extension, CI (ruff + Alembic + pytest against real service
  containers), and a Vite+React+TS+Tailwind v4+shadcn (`radix-nova`) frontend shell.

### Phase 2 — auth and core data model

- **Data model** (`backend/app/models/`): `users`, `refresh_tokens`, `jobs`, `resumes`,
  `interview_sessions`, `answers`, `scores`, `async_jobs` — all created by the Alembic migration
  `0a764d64c629`. Roles are `candidate` / `recruiter`; `is_admin` is a flag on `recruiter`
  accounts, not a third role tree.
- **Auth** (`backend/app/auth/`): Argon2id password hashing (`argon2-cffi`), PyJWT access tokens
  (15 min default), opaque high-entropy refresh tokens that are hashed before storage and rotated
  on every use, with reuse detection — replaying an already-rotated refresh token revokes every
  refresh token that user currently holds. Rate limiting via `slowapi`, tighter on
  register/login (10/min) than refresh/logout (30/min) than the app-wide default (100/min).
- **Endpoints**: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`,
  `POST /auth/logout`, `GET /auth/me`.
- **Tests**: `backend/tests/test_auth.py`, 12 integration tests against the real Docker Postgres
  covering registration, duplicate-email rejection, login success/failure, refresh rotation, reuse
  detection, logout, and the `/auth/me` bearer-token dependency.

Not yet built: resume/job-matching/interview/speech/scoring pipelines, ARQ job queue, and all
frontend screens beyond the bare Vite+shadcn shell (no login/register UI yet — that's Phase 3).

## Local dev setup

```bash
cd "Project-2 MLIS/ai-interview-platform"
cp .env.example .env             # then fill in real secrets locally; .env is gitignored
uv sync                          # create .venv and install backend/ml dependencies
docker compose up -d             # start Postgres+pgvector and Redis
uv run alembic upgrade head      # apply all migrations
uv run uvicorn app.main:app --reload --app-dir backend   # start the API on :8000
```

In a second terminal, for the frontend:

```bash
cd "Project-2 MLIS/ai-interview-platform/frontend"
npm install
npm run dev                      # Vite dev server on :5173
```

## How to test what's implemented

### Backend — lint, migrations, unit/integration tests

```bash
cd "Project-2 MLIS/ai-interview-platform"

# Static checks
uv run ruff check .

# Migrations: run against the live Docker Postgres, and verify the round trip
docker compose up -d
uv run alembic upgrade head
uv run alembic downgrade -1      # rolls back Phase 2's table migration cleanly
uv run alembic upgrade head      # re-applies it; confirms no drift either direction
uv run alembic check             # confirms models == live schema, no missing migration

# Full test suite (health check + all auth flows), against the same live Postgres
uv run pytest -q
```

### Backend — exercising the auth API by hand

With the API running (`uv run uvicorn app.main:app --reload --app-dir backend`) and Postgres up:

```bash
# Register a candidate; note the access_token and refresh_token in the response
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "candidate@example.com", "password": "StrongPass123", "full_name": "Ada Lovelace"}'

# Register a recruiter
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "recruiter@example.com", "password": "StrongPass123", "role": "recruiter"}'

# Log in (works for either account created above)
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "candidate@example.com", "password": "StrongPass123"}'

# Call a protected endpoint with the access_token from register/login
curl -s http://localhost:8000/auth/me -H "Authorization: Bearer <ACCESS_TOKEN>"

# Rotate tokens with the refresh_token from register/login
curl -s -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<REFRESH_TOKEN>"}'

# Log out (revokes that refresh token; a second /auth/refresh with it now returns 401)
curl -s -X POST http://localhost:8000/auth/logout \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<REFRESH_TOKEN>"}'
```

Interactive OpenAPI docs (try every endpoint from the browser, including the "Authorize" button
for bearer tokens) are at `http://localhost:8000/docs` while the API is running.

### Frontend — lint and build

There is no auth UI yet (that's Phase 3), so the only meaningful checks right now are that the
scaffold itself is healthy:

```bash
cd "Project-2 MLIS/ai-interview-platform/frontend"
npm run lint     # oxlint
npm run build    # tsc -b && vite build
npm run dev      # manual check: http://localhost:5173 renders the shadcn placeholder shell
```

### ml/ — nothing runnable yet

`ml/{llm,resume,matching,speech,scoring}/` are still empty package stubs; there is no ML code to
test until the resume-pipeline, job-matching, llm-provider, and speech-pipeline phases land.

### CI

Every push/PR runs `.github/workflows/ci.yml`: brings up Postgres+pgvector and Redis as service
containers, runs `alembic upgrade head`, `ruff check .`, and `pytest -q` — the same commands as
above, against the same kind of database.

## Resuming from a clean shell

```bash
cd "/home/sam/projects/Project-2 MLIS/ai-interview-platform" && \
  uv sync && docker compose up -d && uv run alembic upgrade head && uv run pytest -q
```
