# Absences calendar — CSS-grid version

A FastAPI + Jinja2 app that renders the monthly absence calendar as an HTML/CSS
grid instead of the static PNG produced by `app/image.py`. The layout, colours
and proportions match the original image.

## Run with uv (recommended)

[uv](https://docs.astral.sh/uv/) reads `pyproject.toml`, creates the virtual
environment and installs everything on the first `uv run` — no manual venv or
`pip install` step.

```bash
cd fastapi_calendar
uv run uvicorn app:app --reload
```

That's it — open http://127.0.0.1:8000/ in a browser.

Run the tests:

```bash
uv run pytest            # installs the dev group (pytest, httpx) and runs the suite
```

(Optional: `uv sync` pre-installs deps, `uv sync --group dev` adds the test deps.)

### Fallback: plain pip

```bash
cd fastapi_calendar
pip install -r requirements.txt
uvicorn app:app --reload
```

## URLs

| URL                          | Shows                       |
|------------------------------|-----------------------------|
| `/`                          | current month               |
| `/05/2026`                   | May 2026 (`/{month}/{year}`)|
| `/09/2026`                   | September 2026              |

## Files

- `app.py` — routes (`/` and `/{month}/{year}`) and prev/next navigation.
- `calendar_grid.py` — pure function `build_context(year, month, objects, absences, holidays)` that computes the grid (CW week bars, weekend shading, day numbers, holidays, absence blocks, current-day/month highlights). No framework dependencies, easy to unit-test.
- `templates/calendar.html` — the CSS-grid template. Fira Code is loaded from Google Fonts with a monospace fallback.
- `sample_data.py` — stand-in data (the 7 example rows + a few sample absences/holidays). Swap `get_month_data()` for your SQLAlchemy queries to wire it into the real `absences` app.
- `pyproject.toml` — uv/PEP 621 project metadata: runtime deps and a `dev` group (pytest, httpx).
- `tests/test_app.py` — smoke tests (routes render, CW bars, 30-day pad, holidays, 404 on bad month).

## Layout (mirrors `image.py`)

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
