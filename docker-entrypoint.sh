#!/bin/sh
# Select which app this container runs: `backend` (default) or `frontend`.
# Any other argument is executed as-is (e.g. a shell for debugging).
set -e

case "$1" in
  backend)
    cd /app/backend
    exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8001}"
    ;;
  frontend)
    cd /app/frontend
    exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  *)
    exec "$@"
    ;;
esac
