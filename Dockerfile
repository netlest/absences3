# Single image for both apps of the uv workspace; pick the service at run
# time via the entrypoint argument:
#
#   docker run ... ghcr.io/netlest/absences3 backend    # API on :8001
#   docker run ... ghcr.io/netlest/absences3 frontend   # UI  on :8000
#   docker run ... ghcr.io/netlest/absences3 migrate    # apply sql_ddl/migrations
#
# Configuration is environment-only (no .env files are baked in):
#   backend:  DATABASE_URL (required), SESSION_TTL_HOURS (default 48)
#   frontend: BACKEND_URL (default http://127.0.0.1:8001)
#   both:     PORT overrides the default listen port
#
# Build identity: CI passes GIT_SHA / BUILD_DATE as build args; both apps
# report them (frontend footer, GET /version). A plain local build says "dev".

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
COPY sql_ddl/ sql_ddl/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages


FROM python:3.13-slim-bookworm
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
# Declared last so a new commit only rebuilds this metadata-only layer.
ARG GIT_SHA=dev
ARG BUILD_DATE=
ENV APP_VERSION=$GIT_SHA APP_BUILD_DATE=$BUILD_DATE
USER app
EXPOSE 8000 8001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["backend"]
