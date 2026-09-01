# Single image for both apps of the uv workspace; pick the service at run
# time via the entrypoint argument:
#
#   docker run ... ghcr.io/netlest/absences3 backend    # API on :8001
#   docker run ... ghcr.io/netlest/absences3 frontend   # UI  on :8000
#
# Configuration is environment-only (no .env files are baked in):
#   backend:  DATABASE_URL (required), SESSION_TTL_HOURS (default 48)
#   frontend: BACKEND_URL (default http://127.0.0.1:8001)
#   both:     PORT overrides the default listen port

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Dependency layer: only manifests, so code edits don't bust the cache.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/
COPY frontend/pyproject.toml frontend/
COPY models/pyproject.toml models/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace

# Application code, then install the workspace packages themselves.
COPY backend/ backend/
COPY frontend/ frontend/
COPY models/ models/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages


FROM python:3.13-slim-bookworm
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000 8001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["backend"]
