---
name: run-app
description: Launch and drive the absences-calendar apps (uv workspace; frontend on 8000, backend on 8001). Use when asked to run, start, or verify the apps in this repo.
---

# Run the absences-calendar apps

A uv workspace with two packages sharing one venv and lockfile at the repo
root. No database, no env vars, no build step — uv creates the venv and
installs dependencies on the first `uv run`.

- `frontend/` — the calendar UI (FastAPI + Jinja2, Tailwind via Play CDN)
- `backend/` — minimal API (FastAPI + SQLAlchemy)

## Launch

From the repo root, start each server in the background:

```bash
uv run --directory frontend uvicorn app:app --reload --port 8000
uv run --directory backend  uvicorn app:app --reload --port 8001
```

`--reload` picks up code changes automatically, so there is no need to
restart after edits. If a port is taken, pick another and adjust the URLs.

## Verify they're up

Poll until the servers answer:

```bash
for i in $(seq 1 20); do
  curl -sf -o /dev/null http://127.0.0.1:8000/ && break; sleep 0.5
done
```

- Frontend `/` returns 200 HTML whose `<title>` is the current month
  (e.g. `July 2026`).
- Backend `/` returns `{"service":"absences-backend","status":"ok",...}`.

## Drive the frontend

- `/` — current month
- `/{month}/{year}` — a specific month (month first!), e.g. `curl -s http://127.0.0.1:8000/12/2026`
- Check a specific change by curling the affected route and grepping the
  rendered HTML (calendar cells are a CSS grid in the response body).

## Tests

```bash
uv run --directory frontend pytest
```

Installs the dev group (pytest, httpx2) automatically and runs `frontend/tests/`.
