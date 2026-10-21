# syntax=docker/dockerfile:1
# Deploy image for the API and the ARQ worker. The dev workflow stays `uv run` on the host.
# This file does not download Whisper or MiniLM weights. The worker fetches them on first use.
FROM python:3.11.9-slim-bookworm

# WeasyPrint needs cairo/pango. The speech worker needs ffmpeg. pytest does not install these.
# Compose builds with network: host. The bridge drops connections to deb.debian.org.
# HTTPS plus a few whole-command retries survives a mirror that dies mid-download.
RUN set -eu \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'Acquire::Retries "5";' 'Acquire::https::Timeout "60";' > /etc/apt/apt.conf.d/80-retries \
    && n=0 \
    && until apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        shared-mime-info \
        fonts-liberation \
        ffmpeg; do \
        n=$((n + 1)); \
        if [ "$n" -ge 4 ]; then exit 1; fi; \
        echo "apt attempt ${n} failed; retrying"; \
        sleep 3; \
    done \
    && rm -rf /var/lib/apt/lists/*

# Same uv release as this machine so `uv sync --frozen` matches the lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

# Repo root. alembic.ini, backend/, and ml/ are all addressed from here.
WORKDIR /app

# Dependency metadata first so a source-only edit can reuse the wheel layer when the lockfile is unchanged.
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend
COPY ml ./ml

# Install the project into /app/.venv. --no-dev skips pytest/ruff. --no-editable copies the packages in.
# The cache mount keeps wheels when a retry has to run uv sync again.
# /etc/resolv.conf is mounted read-only by BuildKit, so DNS stays on the host network from compose.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_RETRIES=10 \
    UV_CONCURRENT_DOWNLOADS=4
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu \
    && n=0 \
    && until uv sync --frozen --no-dev --no-editable; do \
        n=$((n + 1)); \
        if [ "$n" -ge 4 ]; then exit 1; fi; \
        echo "uv sync attempt ${n} failed; retrying"; \
        sleep 5; \
    done

# The venv's uvicorn, alembic, and arq are the process entrypoints. No host Python is required.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Blob root inside the container. Compose mounts a volume here so API and worker share uploads.
RUN mkdir -p /data/blobs

# alembic.ini lives at the repo root. The API entrypoint runs `alembic upgrade head` from /app.
COPY alembic.ini ./

# Document the in-container listen port. Compose maps a host port onto it; this is not host 8001.
EXPOSE 8000

# Default process is the API without waiting on a migration. The compose API service overrides this
# with backend/docker/api-entrypoint.sh. The worker service overrides it with arq.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
