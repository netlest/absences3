---
name: run-app
description: Launch and drive the absences-calendar apps (uv workspace; frontend on 8000, backend on 8001, PostgreSQL behind the backend). Use when asked to run, start, or verify the apps in this repo.
---

# Run the absences-calendar apps

A uv workspace (`frontend`, `backend`, `models`) sharing one venv and lockfile
at the repo root. uv creates the venv and installs dependencies on the first
`uv run` — no build step.

- `frontend/` — the calendar UI (FastAPI + Jinja2, Tailwind via Play CDN,
  htmx). Holds no data: every page calls the backend at `BACKEND_URL`
  (default `http://127.0.0.1:8001`).
- `backend/` — JSON API (FastAPI + SQLAlchemy) on PostgreSQL.

## Prerequisites

The backend needs a PostgreSQL database and `DATABASE_URL`. There is no
default, so the backend won't start without it.

1. Check that `backend/.env` exists. If it doesn't, copy
   `backend/.env.example` (the local dev value is
   `DATABASE_URL=postgresql+psycopg:///kalendarz`, Unix socket, peer auth).
2. Check that the database is there:
   `psql -d kalendarz -c 'select count(*) from users'`.
   If it is missing, follow the one-time setup in README.md ("Local
   development database"): `createdb`, apply `sql_ddl/schema.sql` then
   `sql_ddl/v_absences.sql`, and run
   `uv run --directory backend python seed_dev.py`.
   Don't drop or reseed an existing database without asking: it may hold
   real data.

The seed creates the login `admin` / `admin` plus sample absences in
September 2026.

## Launch

From the repo root, start each server in the background:

```bash
uv run --directory backend  uvicorn app:app --reload --port 8001
uv run --directory frontend uvicorn app:app --reload --port 8000
```

`--reload` picks up code changes, so you don't need to restart after edits.
If a port is taken, pick another one. For the frontend, also set
`BACKEND_URL=http://127.0.0.1:<port>` if the backend port changed.

## Verify they're up

```bash
for i in $(seq 1 20); do
  curl -sf -o /dev/null http://127.0.0.1:8001/ && break; sleep 0.5
done
curl -s http://127.0.0.1:8001/          # {"service":"absences-backend","status":"ok",...}
curl -s http://127.0.0.1:8001/health/db # {"database":"ok","users":N,"objects":N} — proves the DB connection
```

## Drive the frontend

Every page except `/login` needs a session. Without a cookie, you get a
303 redirect to `/login`. Log in once and reuse the cookie jar (use the
scratchpad for the jar file):

```bash
JAR=<scratchpad>/cookies.txt
curl -s -c "$JAR" -o /dev/null -w '%{http_code}\n' \
  -d username=admin -d password=admin http://127.0.0.1:8000/login   # 303 = ok, 401 = bad login
curl -s -b "$JAR" http://127.0.0.1:8000/09/2026
```

- `/{month}/{year}` — a specific month (month first!), e.g. `/09/2026`.
  Optional `?months=N&group=ID`.
- `/` — resumes the session's last view (month, year, months, group are
  saved in the backend session on every render), else the current month.
  So a bare `/` after visiting `/09/2026` shows September, not today.
- `/manage` — admin CRUD (htmx). `/password` — change password.
- `/debug/session` — your own session payload as JSON.
- To check a change, curl the affected route and grep the rendered HTML
  (calendar cells are a CSS grid in the response body). For JS/htmx
  behaviour, use a browser (e.g. the playwright-cli skill) and log in
  through the form.

The backend API can also be called directly. `POST /auth/login` with JSON
`{"username","password"}` returns a `token`, which you send as
`Authorization: Bearer <token>`.

## Tests

```bash
uv run --directory frontend pytest
```

These run without a database or backend, because `api_client` is
monkeypatched. They install the dev group (pytest, httpx2) automatically
and run `frontend/tests/`.
