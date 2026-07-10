"""
FastAPI app that renders the monthly absence calendar as a live CSS-grid page,
reproducing the look of the static PNG from app/image.py.

Run:
    pip install -r requirements.txt
    uvicorn app:app --reload

Then open:
    http://127.0.0.1:8000/            -> current month
    http://127.0.0.1:8000/05/2026     -> May 2026   ( /{month}/{year} )
    http://127.0.0.1:8000/09/2026     -> September 2026
"""

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from calendar_grid import build_context
from sample_data import get_month_data

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Absences calendar (CSS grid)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (year, month) shifted by `delta` months."""
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _render(request: Request, year: int, month: int) -> HTMLResponse:
    if not (1 <= month <= 12):
        raise HTTPException(status_code=404, detail="Month must be 1-12")

    objects, absences, holidays = get_month_data(year, month)
    context = build_context(year, month, objects, absences=absences, holidays=holidays)

    # Prev / next navigation metadata.
    py, pm = _shift(year, month, -1)
    ny, nm = _shift(year, month, +1)
    context.update(
        prev_year=py, prev_month=pm, prev_name=date(py, pm, 1).strftime("%b"),
        next_year=ny, next_month=nm, next_name=date(ny, nm, 1).strftime("%b"),
    )
    # Starlette's current signature: request first, then template name, then context.
    return templates.TemplateResponse(request, "calendar.html", context)


@app.get("/", response_class=HTMLResponse)
def current_month(request: Request):
    today = date.today()
    return _render(request, today.year, today.month)


@app.get("/{month}/{year}", response_class=HTMLResponse)
def month_view(request: Request, month: int, year: int):
    """e.g. /05/2026 -> May 2026."""
    return _render(request, year, month)
