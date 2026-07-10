---
name: run-app
description: Launch and drive the FastAPI absences-calendar app (uv + uvicorn on port 8000). Use when asked to run, start, or verify the app in this repo.
---

# Run the absences-calendar app

FastAPI + Jinja2 app rendering the monthly absence calendar as an HTML/CSS
grid. No database, no env vars, no build step — uv creates the venv and
installs dependencies from `pyproject.toml` on the first `uv run`.

## Launch

From the repo root (`fastapi_calendar/`), start the server in the background:

```bash
uv run uvicorn app:app --reload --port 8000
```

(Same command as `./start.sh`, plus an explicit port.) `--reload` picks up
code changes automatically, so there is no need to restart after edits.

If port 8000 is taken, pick another port and adjust the URLs below.

## Verify it's up

Poll until the server answers, then check the homepage:

```bash
for i in $(seq 1 20); do
  curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ && break
  sleep 0.5
done
```

Expect `200` and an HTML body whose `<title>` is the current month
(e.g. `July 2026`).

## Drive it

- `/` — current month
- `/{month}/{year}` — a specific month (month first!), e.g. `curl -s http://127.0.0.1:8000/12/2026`
- Check a specific change by curling the affected route and grepping the
  rendered HTML (calendar cells are a CSS grid in the response body).

## Tests

```bash
uv run pytest
```

Installs the dev group (pytest, httpx) automatically and runs `tests/`.
