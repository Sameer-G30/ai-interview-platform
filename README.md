# AI Interview Intelligence Platform

Status: **Phase 7 of 15 complete (job-matching)**. Full architecture diagram, seed/demo scripts, and
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
`VITE_API_BASE_URL`. Leave that empty in local `npm run dev` so `/auth`, `/health`, `/jobs`, and
`/resumes` stay same-origin and Vite proxies them to uvicorn (`127.0.0.1:8001` on this machine). Access JWT
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
`/candidate` proves the hook. Vite proxies `/jobs` same-origin like `/auth`, `/health`, and `/resumes`.
- **Tests**: `backend/tests/test_jobs.py` against live Docker Postgres **and** Redis (enqueue, poll
queued, succeed, fail, 401, owner-only 404).



### Phase 5 — resume pipeline

- `ml/resume/` (shared by the worker below and, later, the research harness):
  - `parse.py` — `extract_text()` tries **PyMuPDF** first (approved primary parser; AGPL) and falls
  back to **pypdfium2** (MIT) if PyMuPDF raises, so a deployment that cannot accept AGPL can force
  the fallback with no other code change. `split_into_sections()` does header-line sectioning
  (summary/experience/education/skills/projects/...); `extract_contact_info()` regexes an email
  and phone out of the raw text.
  - `skills.py` — ESCO-style skill matching via spaCy's `PhraseMatcher` (exact, case-insensitive
  phrase matching against a taxonomy of `{preferred_label, aliases}`), **not** a trained NER
  model, per Part 0. The full ~13k-skill ESCO dump is **not** committed; `data/esco_skills_sample.json`
  is a ~50-skill curated sample enough for tests/local dev. Point `ESCO_SKILLS_PATH` at a larger
  exported file (same `{"skills": [...]}` JSON shape, or a bare JSON list) to use the real
  taxonomy in production — no code change needed.
  - `ats.py` — a transparent, weighted-checklist ATS score (section presence, contact info present,
  matched-skill count, resume length), **not** a learned model, so the score is explainable.
  - `__init__.py` exposes `run_resume_pipeline(file_path) -> (parsed_data, ats_score)`, the single
  entry point the worker (and later the research harness) calls.
- **Upload endpoint**: `POST /resumes` (candidate-only; recruiters get 403) validates
`Content-Type: application/pdf` and a 10 MiB size cap, writes the file under
`Settings.storage_root` (`./data/blobs/resumes/<resume_id>.pdf`, gitignored — **never commit
uploaded PDFs**), inserts a `resumes` row (`status=uploaded`), enqueues `resume_parse` via the
existing `enqueue_job` helper, and returns `{resume_id, async_job_id, status}` immediately. No ML
runs in the request handler.
- **Worker** (`app/workers/tasks.py::resume_parse`, registered in `WorkerSettings` with a 60s
`job_timeout`): sets the resume `processing`, runs `ml.resume.run_resume_pipeline` in a thread
(`asyncio.to_thread`, since PyMuPDF/spaCy are synchronous), then writes `parsed_data` + `ats_score`
and sets the resume `parsed`, or sets it `failed` if parsing raised. The linked `async_jobs` row is
updated `succeeded`/`failed` the same way `demo_echo`/`demo_fail` already were.
- **Results endpoint**: `GET /resumes/{id}` is owner-only (404 if missing or someone else's,
mirroring `GET /jobs/{id}`'s not-403 convention so ids stay non-enumerable).
- **No new Alembic migration** — `resumes` (`file_path`, `original_filename`, `status`,
`parsed_data`, `ats_score`) and `async_jobs` already had every column this phase needed;
`alembic check` reports no drift.
- **Tests**: `backend/tests/test_resumes.py`, 8 integration tests against live Docker Postgres and
Redis — upload + queued, worker success with skill/ATS assertions, worker failure on a
no-extractable-text PDF, owner-only 404, unknown-id 404, recruiter-forbidden upload, wrong
content-type rejected, unauthenticated upload rejected. PDFs are generated in-memory with
PyMuPDF, never written to the repo.
- **Frontend in Phase 5**: upload/results UI was still later (`frontend-resume`). Phase 6 now owns that
UI; the `/candidate` job-queue demo card is unchanged.



### Phase 6 — candidate resume UI

- **Vite proxy**: `/resumes` is proxied to `http://127.0.0.1:8001` next to `/auth`, `/health`, and
`/jobs`. Leave `frontend/.env` `VITE_API_BASE_URL` empty in local `npm run dev` so the SPA stays
same-origin (avoids localhost vs 127.0.0.1 CORS traps).
- **Typed client** (`frontend/src/api/resumes.ts`): `uploadResume` POSTs multipart field `file` via
`apiUpload` (XHR, so the bar can show 0–100). `fetchResume` GETs `/resumes/{id}`. `apiFetch` still
JSON-stringifies bodies, so FormData cannot go through it.
- **Upload page** (`/candidate/resume`): drag-and-drop plus a file-picker fallback, PDF-only, 10 MiB
client check, progress while bytes leave the browser. After `201` the SPA navigates to
`/candidate/resume/:resumeId?job=:asyncJobId`.
- **Results page**: polls `GET /jobs/{id}` with the existing `useJobStatus` hook (no second poller).
Shows queued / running / failed. Once the job is `succeeded` or `failed` (or `?job=` is missing),
it GETs `/resumes/{id}` and renders sections, skill chips, and the ATS score card — including
empty, pending, and failed states.
- **Nav**: candidate **Resume** is enabled. Overview and the `/candidate` queue demo stay. No
recruiter resume UI, interview screens, or admin screens.
- **Tests**: backend pytest is unchanged this phase (26 passed). Frontend `npm run lint` (existing
oxlint warnings on generated shadcn `button.tsx` / `sidebar.tsx` only) and `npm run build`.



### Phase 7 — job matching

- `ml/matching/` (shared by the workers below and, later, the research harness):
  - `embed.py` — lazy-loaded, process-cached `sentence-transformers/all-MiniLM-L6-v2` singleton;
  `embed_texts()`/`embed_text()` return plain Python `list[float]` (384-d), no numpy leaking into
  callers. The heavy `sentence-transformers` import is deferred until the model is actually used.
  - `similarity.py` — `cosine_similarity()` (pure Python, no numpy dependency) and `skill_gap()`, a
  case-insensitive matched/missing diff between a resume's ESCO skills and a posting's.
  - `__init__.py` — one `MatchingBackend` protocol implemented by two classes: `SbertBackend`
  (production; cosine similarity over precomputed pgvector embeddings, 0.0 for a not-yet-embedded
  posting rather than raising) and `TfidfBackend` (the plan's required baseline arm; fits
  `sklearn.feature_extraction.text.TfidfVectorizer` over `[resume_text] + posting_texts` on the fly,
  no persistence). `/matches` only calls `SbertBackend`; `TfidfBackend` is proven callable through the
  identical interface by `backend/tests/test_ml_matching.py`, not wired into the API.
- **Schema**: new Alembic revision `de258b209b24` adds nullable `Vector(384)` columns —
`jobs.embedding` and `resumes.embedding` (pgvector, via the `pgvector` Python package's SQLAlchemy
type). Verified upgrade → downgrade → upgrade round trip and `alembic check` clean.
- **Workers** (`app/workers/tasks.py`): `resume_parse` now also computes and writes
`resumes.embedding` (section text + skills, joined) right after `parsed_data`/`ats_score` succeed —
by the time a resume is `status=parsed`, it is always embedded too, no separate polling needed. A
new `posting_embed` task (job type `posting_embed`, registered in `WorkerSettings`) embeds one
posting's `title + description + required_skills` text into `jobs.embedding`; `POST /postings`
enqueues it the same way `POST /resumes` enqueues `resume_parse`.
- **Recruiter API** (`app/routers/postings.py`, prefix `/postings`, `require_recruiter`):
`POST /postings` (create + enqueue embedding, returns `{posting, async_job_id}`), `GET /postings`
(caller's own postings, newest first), `GET /postings/{id}` and `PATCH /postings/{id}`
(`{is_active}` only — no hard delete), both owner-only via 404 (not 403) for someone else's id.
- **Candidate API** (`app/routers/matches.py`, prefix `/matches`, `require_candidate`):
`GET /matches[?resume_id=]` ranks every active, embedded posting against one resume by SBERT cosine
similarity, plus a per-posting `matched_skills`/`missing_skills` diff (ESCO skills extracted from
`required_skills` via the same `ml.resume.skills.extract_skills` resumes use). Resume selection: an
explicit `resume_id` must belong to the caller and be `status=parsed` (404 if missing/not owned, 409
if owned but still parsing); omitted `resume_id` uses the caller's own most recently created `parsed`
resume (404 if none exists) — there is still no "list my resumes" endpoint, by design.
- **Frontend**: typed `frontend/src/api/{postings,matches}.ts` + `types.ts` additions, a hand-written
`components/ui/textarea.tsx` (matches `input.tsx`'s conventions, not a generated shadcn primitive).
Recruiter **Jobs** page (`/recruiter/jobs`, enabled in the sidebar): RHF+Zod create-posting form
(title/description/optional freeform required-skills textarea) plus a list of the recruiter's own
postings with Active/Inactive + Embedding…/Embedded badges and a Deactivate button (`PATCH`).
Candidate **Matches** page (`/candidate/matches`, new sidebar item): loading skeleton, a "no parsed
resume yet" empty state (the `GET /matches` 404 case) linking to `/candidate/resume`, a generic error
state, and — once loaded — a ranked list of postings with a similarity-score bar plus matched
(green-ish) and missing (destructive) skill chip rows.
- **Vite proxy**: `/postings` and `/matches` added next to `/auth`, `/health`, `/jobs`, `/resumes`.
- **Tests**: `backend/tests/test_postings.py` (7 cases: create+get, owner-only list, deactivate,
owner-only 404, unknown-id 404, candidate-forbidden, unauthenticated), `backend/tests/test_matches.py`
(8 cases: ranks a similar posting above a dissimilar one, skill-gap diff, implicit latest-parsed-resume
lookup, 404 with no parsed resume, owner-only 404 for a foreign `resume_id`, 409 for a not-yet-parsed
`resume_id`, recruiter-forbidden), `backend/tests/test_ml_matching.py` (13 cases: cosine similarity
edge cases, `skill_gap`, both backends' `.rank()` including a direct `TfidfBackend` call, the
`get_backend` factory, and one real-`all-MiniLM-L6-v2` smoke test that `pytest.skip()`s — never
fails — if the model cannot be loaded offline). Tests that go through the worker monkeypatch
`app.workers.tasks.embed_text` to a deterministic hashing-trick embedder so they never need real
model weights or network access; the one real-model test lives only in `test_ml_matching.py`.
**53 passed** (26 prior + 27 new) against live Docker Postgres and Redis; `ruff check .` clean;
`alembic check` clean; frontend `npm run lint` (existing shadcn oxlint warnings only) and
`npm run build` clean. Full browser walkthrough (recruiter creates a posting → worker embeds it →
candidate uploads/parses a resume → candidate's Matches page shows the ranked posting with matched
skill chips) verified on both a desktop and a mobile viewport.



## Local dev setup

```bash
cd "Project-2 MLIS/ai-interview-platform"
cp .env.example .env             # then fill in real secrets locally; .env is gitignored
uv sync                          # create .venv and install backend/ml dependencies (includes the
                                  # en_core_web_sm spaCy model, pinned as a direct wheel URL in
                                  # pyproject.toml so `uv sync` alone is enough — no separate
                                  # `spacy download` step needed in local dev or CI)
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

Type **[http://localhost:5174](http://localhost:5174)** in a normal browser tab (do not use a Cursor-forwarded 5175). Postgres/Redis stay on 5432/6379 unless those are also taken.

### Ports, CORS, and sharing the machine with another app

Defaults are API **8000** and Vite **5173**. Those values in `.env` do **not** all do what they look like:


| Setting             | File                                      | What it actually does                                                          |
| ------------------- | ----------------------------------------- | ------------------------------------------------------------------------------ |
| `API_PORT`          | repo `.env`                               | Documented default only. **Uvicorn ignores it** unless you pass `--port`.      |
| `FRONTEND_ORIGIN`   | repo `.env`                               | **CORS allow-list** (exact origin the browser sends). Does **not** start Vite. |
| `VITE_API_BASE_URL` | `frontend/.env`                           | Where the browser calls FastAPI. Does **not** set the Vite listen port.        |
| Vite port           | `frontend/vite.config.ts` + `npm run dev` | Pinned to **5174** with `strictPort` (will not hop to 5175).                   |


If another project already owns 8000/5173 (common on this machine), use **8001** and **5174**:

1. Repo `.env`:
  ```env
   API_PORT=8001
   FRONTEND_ORIGIN=http://localhost:5174
  ```
   CORS also allows the `127.0.0.1` twin of that origin. Do not drop that helper.
2. Leave `frontend/.env` `VITE_API_BASE_URL` **empty** in local `npm run dev`. Vite proxies
  `/auth`, `/health`, `/jobs`, `/resumes`, `/postings`, and `/matches` to `http://127.0.0.1:8001`.
   Setting a cross-origin API URL reintroduces localhost vs 127.0.0.1 CORS traps.
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
4. Type **[http://localhost:5174](http://localhost:5174)** in the browser (must match `FRONTEND_ORIGIN`). If Cursor's Ports panel shows **5175**, delete that forward — it is a remap, not this app. Do not use 5173 or 5175.

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

### Backend — exercising the resume pipeline by hand

Postgres, Redis, the API, **and** the ARQ worker must all be running (same processes as the job
queue above). Have any PDF file locally to upload — a real resume works, or generate a throwaway
one:

```bash
uv run python -c "
import pymupdf
doc = pymupdf.open()
page = doc.new_page()
page.insert_text((50, 50), 'Jane Doe\njane@example.com\n\nSkills\nPython, Docker, SQL')
doc.save('/tmp/sample_resume.pdf')
"
```

```bash
# Upload (use the access_token from register/login above; candidates only — recruiters get 403)
curl -s -X POST http://localhost:8000/resumes \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -F "file=@/tmp/sample_resume.pdf;type=application/pdf"
# -> {"resume_id": "...", "async_job_id": "...", "status": "uploaded"}

# Poll the async job (same GET /jobs/{id} as the queue demo) until it is succeeded/failed
curl -s http://localhost:8000/jobs/<ASYNC_JOB_ID> -H "Authorization: Bearer <ACCESS_TOKEN>"

# Once succeeded, read the parsed sections, matched ESCO skills, and ATS score
curl -s http://localhost:8000/resumes/<RESUME_ID> -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Expected resume poll statuses: `uploaded` → `processing` → `parsed` (with `parsed_data.sections`,
`parsed_data.skills`, and `ats_score`) or `failed` (e.g. a PDF with no extractable text) with
`ats_score`/`parsed_data` staying `null`. Swap `8000` for `8001` if that is the port you bound.
Once `parsed`, the same worker pass has also written `resumes.embedding` (not exposed in the JSON
response — it backs `/matches` only).

### Backend — exercising job matching by hand

Postgres, Redis, the API, and the ARQ worker must all be running. This needs a **recruiter** account
(to create a posting) and a **candidate** account with an already-`parsed` resume (see the resume
walkthrough above).

```bash
# Create a posting as the recruiter (candidates get 403 here)
curl -s -X POST http://localhost:8000/postings \
  -H "Authorization: Bearer <RECRUITER_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Backend Engineer", "description": "Build APIs with FastAPI and Postgres.", "required_skills": "Python, FastAPI, PostgreSQL, Docker"}'
# -> {"posting": {...,"has_embedding": false}, "async_job_id": "..."}

# Poll the embedding job (same GET /jobs/{id} as every other async job)
curl -s http://localhost:8000/jobs/<ASYNC_JOB_ID> -H "Authorization: Bearer <RECRUITER_ACCESS_TOKEN>"

# Once succeeded, has_embedding flips to true
curl -s http://localhost:8000/postings/<POSTING_ID> -H "Authorization: Bearer <RECRUITER_ACCESS_TOKEN>"

# Recruiter lists their own postings, newest first
curl -s http://localhost:8000/postings -H "Authorization: Bearer <RECRUITER_ACCESS_TOKEN>"

# Deactivate a posting (is_active only; no hard delete)
curl -s -X PATCH http://localhost:8000/postings/<POSTING_ID> \
  -H "Authorization: Bearer <RECRUITER_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'

# As the candidate, rank active+embedded postings against your latest parsed resume
curl -s http://localhost:8000/matches -H "Authorization: Bearer <CANDIDATE_ACCESS_TOKEN>"
# -> {"resume_id": "...", "matches": [{"posting_id": "...", "title": "...", "score": 0.8x,
#      "matched_skills": [...], "missing_skills": [...]}, ...]} sorted best-first

# Or target a specific resume explicitly
curl -s "http://localhost:8000/matches?resume_id=<RESUME_ID>" -H "Authorization: Bearer <CANDIDATE_ACCESS_TOKEN>"
```

`GET /matches` is 404 if the candidate has no `parsed` resume at all (or the given `resume_id`
doesn't belong to them), and 409 if a given `resume_id` exists and is owned but hasn't finished
parsing yet. Swap `8000` for `8001` if that is the port you bound.

### Frontend — lint, build, auth, and resume walkthrough

The Vite+shadcn scaffold now has a real shell plus candidate resume upload/results. Backend, Postgres,
Redis, and the ARQ worker must be up for login/register, the demo job, and resume parsing. CORS allows
`FRONTEND_ORIGIN` and its `127.0.0.1` twin (this machine: `http://localhost:5174`). See **Ports, CORS,
and sharing the machine with another app** above.

```bash
cd "Project-2 MLIS/ai-interview-platform/frontend"
npm run lint     # oxlint — generated shadcn `button.tsx` may still warn about exporting buttonVariants
npm run build    # tsc -b && vite build
npm run dev      # pinned to http://localhost:5174 (strictPort)
```

Manual UI checks (with `npm run dev` and the API on `:8001`):

1. Open `http://localhost:5174` — you should be redirected to `/login` (not a 404; that 404 is only `GET /` on the API). Type that URL in a normal browser; a Cursor terminal link may remap 5174 to 5175.
2. Click through to **Create one**, register a **candidate** (password ≥ 8 chars). You should land on `/candidate` with the sidebar showing Overview (live), **Resume** (live), and Interview (disabled, later phases).
3. Sign out. Register a **recruiter**. You should land on `/recruiter`. Visiting `/candidate` as a recruiter should bounce you back to `/recruiter`. Recruiters have no Resume nav.
4. Sign out, sign back in with the same account — session restore from localStorage (`aiip.auth.tokens`) should skip the forms.
5. Reload the page while signed in — `/auth/me` should repopulate the shell. If the access JWT has expired, the client will rotate the opaque refresh token via `POST /auth/refresh` without a visible logout.
6. A recruiter with `is_admin=true` (set in the database by an operator, never via register) shows a disabled **Admin** row. There is no admin dashboard in this phase.
7. On `/candidate`, click **Run demo job** (API + Redis + worker must be up). Status should move queued → running → succeeded and show the echo text. Leave `frontend/.env` `VITE_API_BASE_URL` empty so `/jobs`, `/resumes`, `/postings`, and `/matches` stay same-origin through the Vite proxy.
8. Click **Resume** (or **Open resume upload**). Drop or pick a text-based PDF (≤ 10 MiB). A non-PDF should be rejected in the dropzone. After **Upload and parse**, you should land on the results page, see queued → running → succeeded, then sections, skill chips, and an ATS score. A PDF with no extractable text should show the failed job/resume states instead of a blank page.
9. Sign out, sign in (or register) as a **recruiter**, open **Jobs** in the sidebar, and create a posting (title + description + optional comma-separated required skills). It should appear at the top of "Your postings" with an **Active** badge and an **Embedding…** badge; reload after a few seconds and the badge flips to **Embedded** once the worker finishes. Click **Deactivate** and confirm the badge flips to **Inactive**.
10. Sign back in as the candidate whose resume you parsed in step 8, open **Matches** in the sidebar. You should see the posting from step 9 (if still active) with a similarity-score bar and skill chips split into "You have" (matched) and "Skill gap" (missing). A candidate with no parsed resume yet should see the "no parsed resume yet" empty state with a link back to `/candidate/resume` instead of an error.

`GET /` on the API still 404s; use `/health` or `/docs` (and the port you actually bound).

### ml/ — resume + matching pipelines are runnable; llm/speech/scoring are still stubs

`ml/resume/` (parsing, ESCO skill matching, ATS scoring) and `ml/matching/` (SBERT embeddings,
cosine similarity, skill-gap diff, TF-IDF baseline) are implemented and covered end to end by
`backend/tests/test_resumes.py`, `backend/tests/test_postings.py`, `backend/tests/test_matches.py`
(via the workers), and `backend/tests/test_ml_matching.py` (direct unit tests). `ml/{llm,speech,scoring}/`
are still empty package stubs; there is no ML code to test there until the llm-provider and
speech-pipeline phases land.

You can also exercise `ml/resume` and `ml/matching` directly, without the API/worker, for quick iteration:

```bash
uv run python -c "
from ml.resume import run_resume_pipeline
parsed_data, ats_score = run_resume_pipeline('/tmp/sample_resume.pdf')
print(parsed_data['skills'], ats_score)
"

uv run python -c "
from ml.matching.embed import embed_texts
from ml.matching.similarity import cosine_similarity
a, b = embed_texts(['Python backend engineer', 'Marine biologist'])
print(cosine_similarity(a, b))
"
```



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

Worker (separate process, repo root): `uv run arq app.workers.settings.WorkerSettings`. SPA: `cd frontend && npm install && npm run dev` (leave `VITE_API_BASE_URL` empty so `/auth`, `/health`, `/jobs`, `/resumes`, `/postings`, and `/matches` stay same-origin via the Vite proxy).