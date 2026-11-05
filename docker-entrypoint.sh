#!/bin/sh
# Select which app this container runs: `backend` (default) or `frontend`,
# or `migrate` to apply sql_ddl/migrations/ to DATABASE_URL and exit.
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
  migrate)
    cd /app/backend
    exec python migrate.py
    ;;
  *)
    exec "$@"
    ;;
esac
