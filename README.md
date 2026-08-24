# AI Interview Intelligence Platform

Status: **Phase 4 of 15 complete (job-queue)**. Full architecture diagram, seed/demo scripts, and
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

Not yet built: resume/job-matching/interview/speech/scoring pipelines, resume/interview
UI, dashboards, and admin ops (Phase 14). `ml/` is still empty stubs.

### Phase 3 — frontend shell

- **App layout**: shadcn sidebar (collapsible) + inset header, using the existing radix-nova theme
tokens. Light/dark toggle via `next-themes` (`class` on `<html>`).
- **Typed API client** (`frontend/src/api/`): `apiFetch` talks to FastAPI at
`VITE_API_BASE_URL`. Leave that empty in local `npm run dev` so `/auth`, `/health`, and `/jobs`
stay same-origin and Vite proxies them to uvicorn (`127.0.0.1:8001` on this machine). Access JWT
goes in `Authorization: Bearer`.
Refresh tokens are **opaque strings, not JWTs**; on a 401 the client POSTs `/auth/refresh` with
`{ refresh_token }` once (single-flight) so concurrent 401s cannot trigger reuse-detection, then
retries the original request. Failed refresh clears localStorage.
- **Auth UI**: React Hook Form + Zod login (`/login`) and register (`/register`) forms call
`POST /auth/login` and `POST /auth/register`. Registration can choose candidate or recruiter;
`is_admin` is never sent. After success the SPA loads `GET /auth/me` and lands on `/candidate`
or `/recruiter`.
- **Route guards**: guests hitting `/` go to `/login`; signed-in users hitting `/` or the auth
forms go to their role home. A candidate cannot open `/recruiter` and vice versa. Recruiter
`is_admin` shows a disabled Admin nav row (no admin dashboard yet — Phase 14).
- **Session restore**: tokens live in `localStorage` (`aiip.auth.tokens`). Reloading the app
rehydrates `/auth/me`. Sign out calls `POST /auth/logout` then always clears local state.

### Phase 4 — job queue (ARQ + Redis)

- **Enqueue helper** (`backend/app/workers/enqueue.py`): inserts an `async_jobs` row with
`status=queued`, commits, then pushes an ARQ job whose `_job_id` is that UUID. Redis is never
the source of truth for status.
- **Worker** (`backend/app/workers/`): `uv run arq app.workers.settings.WorkerSettings` from the
repo root. The worker marks the row `running`, then `succeeded` (result JSON) or `failed` (short
`error` string; full traceback stays in worker logs). Demo job types `demo_echo` / `demo_fail`
only — `ml/` is not called.
- **HTTP**: `POST /jobs/demo` (authenticated) enqueues a throwaway job and returns immediately.
`GET /jobs/{id}` is owner-only (404 if missing or someone else's). No ML runs in a request handler.
- **Frontend**: `useJobStatus` polls `GET /jobs/{id}` until succeeded/failed. A small demo card on
`/candidate` proves the hook. Vite proxies `/jobs` same-origin like `/auth` and `/health`.
- **Tests**: `backend/tests/test_jobs.py` against live Docker Postgres **and** Redis (enqueue, poll
queued, succeed, fail, 401, owner-only 404).



## Local dev setup

```bash
cd "Project-2 MLIS/ai-interview-platform"
cp .env.example .env             # then fill in real secrets locally; .env is gitignored
uv sync                          # create .venv and install backend/ml dependencies
docker compose up -d             # start Postgres+pgvector and Redis
uv run alembic upgrade head      # apply all migrations
uv run uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8001
```

Uvicorn does **not** read `API_PORT` from `.env`; you must pass `--port`. This machine already uses
8000 for another project, so **8001** is the local default here.

In a second terminal, the ARQ worker (jobs stay `queued` until this is running):

```bash
cd "Project-2 MLIS/ai-interview-platform"
uv run arq app.workers.settings.WorkerSettings
```

In a third terminal, for the frontend:

```bash
cd "Project-2 MLIS/ai-interview-platform/frontend"
npm install
# Leave VITE_API_BASE_URL unset (do not copy a filled-in frontend/.env for local proxy mode).
npm run dev                      # pinned to http://localhost:5174 (strict; will not hop to 5175)
```

Type **http://localhost:5174** in a normal browser tab (do not use a Cursor-forwarded 5175). Postgres/Redis stay on 5432/6379 unless those are also taken.

### Ports, CORS, and sharing the machine with another app

Defaults are API **8000** and Vite **5173**. Those values in `.env` do **not** all do what they look like:

| Setting | File | What it actually does |
|---|---|---|
| `API_PORT` | repo `.env` | Documented default only. **Uvicorn ignores it** unless you pass `--port`. |
| `FRONTEND_ORIGIN` | repo `.env` | **CORS allow-list** (exact origin the browser sends). Does **not** start Vite. |
| `VITE_API_BASE_URL` | `frontend/.env` | Where the browser calls FastAPI. Does **not** set the Vite listen port. |
| Vite port | `frontend/vite.config.ts` + `npm run dev` | Pinned to **5174** with `strictPort` (will not hop to 5175). |

If another project already owns 8000/5173 (common on this machine), use **8001** and **5174**:

1. Repo `.env`:

   ```env
   API_PORT=8001
   FRONTEND_ORIGIN=http://localhost:5174
   ```

   CORS also allows the `127.0.0.1` twin of that origin. Do not drop that helper.

2. Leave `frontend/.env` `VITE_API_BASE_URL` **empty** in local `npm run dev`. Vite proxies
   `/auth`, `/health`, and `/jobs` to `http://127.0.0.1:8001`. Setting a cross-origin API URL
   reintroduces localhost vs 127.0.0.1 CORS traps.

3. Start the processes with matching flags (restart both after changing env):

   ```bash
   # terminal 1 — API
   uv run uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8001

   # terminal 2 — ARQ worker (same .env / Redis as the API)
   uv run arq app.workers.settings.WorkerSettings

   # terminal 3 — Vite is pinned to 5174 in vite.config.ts / package.json
   cd frontend
   npm run dev
   ```

4. Type **http://localhost:5174** in the browser (must match `FRONTEND_ORIGIN`). If Cursor's Ports panel shows **5175**, delete that forward — it is a remap, not this app. Do not use 5173 or 5175.

`FRONTEND_ORIGIN` and the Vite URL must match **exactly** (`http://localhost:5174` ≠ `http://localhost:5173`). A mismatch shows up as `OPTIONS /auth/register` **400** in the API log and a failed register/login in the UI.

`[Errno 98] Address already in use` on uvicorn means you bound 8000 (the default) while another process is already there — add `--port 8001`.

If `/health` or `/docs` belong to a **different** app (OpenAPI title should be
`AI Interview Intelligence Platform`), you are hitting the wrong process on that port.



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

# Full test suite (health + auth + job queue), against live Postgres and Redis
uv run pytest -q
```



### Backend — exercising the auth API by hand

With the API running (`uv run uvicorn app.main:app --reload --app-dir backend --port 8000`, or
`--port 8001` if 8000 is taken) and Postgres up. If you used 8001, swap the host in the curls below.

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

### Backend — exercising the job queue by hand

Postgres, Redis, the API, **and** the ARQ worker must all be running. Jobs stay `queued` until a
worker process picks them up.

```bash
# Enqueue a throwaway echo job (use the access_token from register/login)
curl -s -X POST http://localhost:8000/jobs/demo \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"message": "hello from curl", "sleep_ms": 500}'

# Poll status (only the owning user can read this id; anyone else gets 404)
curl -s http://localhost:8000/jobs/<JOB_ID> \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Swap `8000` for `8001` if that is the port you bound. Expected poll statuses: `queued` → `running`
→ `succeeded` with `"result": {"echo": "hello from curl"}`. A body of `{"fail": true}` ends as
`failed` with a short `error` string.

### Frontend — lint, build, and auth walkthrough

The Vite+shadcn scaffold now has a real shell. Backend, Postgres, Redis, and the ARQ worker must be
up for login/register and the demo job. CORS allows `FRONTEND_ORIGIN` and its `127.0.0.1` twin
(this machine: `http://localhost:5174`). See **Ports, CORS, and sharing the machine with another app** above.

```bash
cd "Project-2 MLIS/ai-interview-platform/frontend"
npm run lint     # oxlint — generated shadcn `button.tsx` may still warn about exporting buttonVariants
npm run build    # tsc -b && vite build
npm run dev      # pinned to http://localhost:5174 (strictPort)
```

Manual UI checks (with `npm run dev` and the API on `:8001`):

1. Open `http://localhost:5174` — you should be redirected to `/login` (not a 404; that 404 is only `GET /` on the API). Type that URL in a normal browser; a Cursor terminal link may remap 5174 to 5175.
2. Click through to **Create one**, register a **candidate** (password ≥ 8 chars). You should land on `/candidate` with the sidebar showing Overview (live) and Resume/Interview (disabled, later phases).
3. Sign out. Register a **recruiter**. You should land on `/recruiter`. Visiting `/candidate` as a recruiter should bounce you back to `/recruiter`.
4. Sign out, sign back in with the same account — session restore from localStorage should skip the forms.
5. Reload the page while signed in — `/auth/me` should repopulate the shell. If the access JWT has expired, the client will rotate the opaque refresh token via `POST /auth/refresh` without a visible logout.
6. A recruiter with `is_admin=true` (set in the database by an operator, never via register) shows a disabled **Admin** row. There is no admin dashboard in this phase.
7. On `/candidate`, click **Run demo job** (API + Redis + worker must be up). Status should move queued → running → succeeded and show the echo text. Leave `frontend/.env` `VITE_API_BASE_URL` empty so `/jobs` stays same-origin through the Vite proxy.

`GET /` on the API still 404s; use `/health` or `/docs` (and the port you actually bound).

### ml/ — nothing runnable yet

`ml/{llm,resume,matching,speech,scoring}/` are still empty package stubs; there is no ML code to
test until the resume-pipeline, job-matching, llm-provider, and speech-pipeline phases land.

### CI

Every push/PR runs `.github/workflows/ci.yml`:

- **Backend job**: Postgres+pgvector and Redis as service containers, then `alembic upgrade head`,
`ruff check .`, and `pytest -q`.
- **Frontend job**: `npm ci`, `npm run lint`, `npm run build` in `frontend/`.



## Resuming from a clean shell

```bash
cd "/home/sam/projects/Project-2 MLIS/ai-interview-platform" && \
  uv sync && docker compose up -d && uv run alembic upgrade head && uv run pytest -q
```

Worker (separate process, repo root): `uv run arq app.workers.settings.WorkerSettings`. SPA: `cd frontend && npm install && npm run dev`.

