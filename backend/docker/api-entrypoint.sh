#!/bin/sh
# Start path for the deploy-profile API container only. The ARQ worker does not use this script.
set -eu
# alembic.ini lives at the repo root, which is WORKDIR /app.
cd /app
# Idempotent. A second start against an already-migrated database is a no-op.
alembic upgrade head
# Replace the shell so uvicorn is PID 1 and receives stop signals.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
