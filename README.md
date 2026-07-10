# Absences calendar

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with
two packages:

- **`frontend/`** — FastAPI + Jinja2 app that renders the monthly absence
  calendar as an HTML/CSS grid instead of the static PNG produced by
  `app/image.py`. The grid layout, colours and proportions match the original
  image; the page around it (top navbar with month controls) is styled with
  Tailwind CSS (Play CDN).
- **`backend/`** — minimal FastAPI API (FastAPI + SQLAlchemy), the starting
  point for serving real absence data.
- **`models/`** — shared SQLAlchemy 2.0 models (users, groups, objects,
  absence types, absences, user_groups, holidays); the backend depends on it
  as a workspace package.

## Run with uv (recommended)

[uv](https://docs.astral.sh/uv/) reads the workspace `pyproject.toml`, creates
one shared virtual environment and installs everything on the first `uv run` —
no manual venv or `pip install` step. From the repo root:

```bash
uv run --directory frontend uvicorn app:app --reload --port 8000
uv run --directory backend  uvicorn app:app --reload --port 8001
```

Open http://127.0.0.1:8000/ (calendar) and http://127.0.0.1:8001/ (API health).

Run the frontend tests:

```bash
uv run --directory frontend pytest
```

(Optional: `uv sync --all-packages --group dev` pre-installs everything.)

### Fallback: plain pip

```bash
cd frontend
pip install -r requirements.txt
uvicorn app:app --reload
```

## Frontend URLs

| URL                          | Shows                       |
|------------------------------|-----------------------------|
| `/`                          | current month               |
| `/05/2026`                   | May 2026 (`/{month}/{year}`)|
| `/09/2026`                   | September 2026              |

## Files

- `pyproject.toml` — uv workspace root (members: `frontend`, `backend`,
  `models`); the shared `uv.lock` lives next to it.
- `frontend/app.py` — routes (`/` and `/{month}/{year}`) and prev/next navigation.
- `frontend/calendar_grid.py` — pure function `build_context(year, month, objects, absences, holidays)` that computes the grid (CW week bars, weekend shading, day numbers, holidays, absence blocks, current-day/month highlights). No framework dependencies, easy to unit-test.
- `frontend/templates/calendar.html` — the CSS-grid template with the Tailwind navbar. Fira Code is loaded from Google Fonts with a monospace fallback.
- `frontend/sample_data.py` — stand-in data (the 7 example rows + a few sample absences/holidays). Swap `get_month_data()` for your SQLAlchemy queries to wire it into the real `absences` app.
- `frontend/tests/test_app.py` — smoke tests (routes render, CW bars, 30-day pad, holidays, 404 on bad month).
- `backend/app.py` — minimal FastAPI app; `/` reports service status and the installed SQLAlchemy version.
- `models/src/models/__init__.py` — declarative models (`DeclarativeBase`/`Mapped`/`mapped_column`) mirroring the PostgreSQL DDL, importable as `from models import User, Absence, ...`.

## Calendar layout (mirrors `image.py`)

- Fixed width: one 250px label column + 31 day columns of 25px each; rows 35px tall.
- Row 1: ISO week (`CW nn`) bars over week-days only (`#ba90ba`).
- Row 2: day numbers; weekends shaded (`#a090a0`), holidays magenta (`#e121ff`).
- Rows 3+: one per object; absences drawn as coloured, captioned blocks that can span multiple days.
- Months shorter than 31 days get the dark padding column(s) (`#605060`) on the right.
- The current month gets a 2px white frame; the current day a 2px white outline.
- Grid lines are painted by a 1px gap over a `#808080` background.

## Wiring into the real app

Replace `sample_data.get_month_data()` with queries against your `Object`,
`VAbsence` and `Holiday` models, returning:

```python
objects  = ["Adam Zaleski", ...]                     # ordered row labels
absences = [{"object": "Adam Zaleski", "day": 6,
             "duration": 5, "color": "#7ec8e3",
             "caption": "Urlop"}, ...]
holidays = {1: "Swieto Pracy", ...}                  # day -> description
```

`build_context()` also accepts a `today=` argument if you need to freeze "today"
for tests.
