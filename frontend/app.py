"""
FastAPI app that renders the monthly absence calendar as a live CSS-grid page.

Data comes from the backend API (see api_client.py); the backend serves it
from PostgreSQL via the v_absences view, which pre-splits absences by month.

Run:
    uv run uvicorn app:app --reload

Then open:
    http://127.0.0.1:8000/                     -> current month, first group
    http://127.0.0.1:8000/05/2026?months=3     -> May-Jul 2026 ( /{month}/{year} )
    http://127.0.0.1:8000/05/2026?group=2      -> another group
"""

import calendar
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import api_client
from calendar_grid import build_context

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Absences calendar (CSS grid)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (year, month) shifted by `delta` months."""
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _month_absences(absences: list[dict], year: int, month: int) -> list[dict]:
    """Grid-shaped absences for one month.

    v_absences rows never cross a month boundary, so matching on the start
    month is exact.
    """
    key = f"{year:04d}-{month:02d}"
    return [
        {
            "object": a["object_name"],
            "day": int(a["abs_date_start"][8:10]),
            "duration": a["duration"],
            "color": a["color"] or "#7ec8e3",
            "caption": a["description"] or a["type_name"] or "",
        }
        for a in absences
        if a["abs_date_start"][:7] == key
    ]


def _month_holidays(holidays: list[dict], year: int, month: int) -> dict[int, str]:
    key = f"{year:04d}-{month:02d}"
    return {
        int(h["date"][8:10]): h["description"]
        for h in holidays
        if h["date"][:7] == key
    }


def _render(
    request: Request, year: int, month: int, months: int = 1, group: int | None = None
) -> HTMLResponse:
    if not (1 <= month <= 12):
        raise HTTPException(status_code=404, detail="Month must be 1-12")
    months = max(1, min(12, months))

    try:
        groups = api_client.get_groups()
        if not groups:
            raise HTTPException(status_code=503, detail="No groups defined")
        if group not in {g["id"] for g in groups}:
            group = groups[0]["id"]
        object_names = [o["name"] for o in api_client.get_objects(group)]

        # One backend round-trip for the whole shown span.
        last_y, last_m = _shift(year, month, months - 1)
        date_from = date(year, month, 1)
        date_to = date(last_y, last_m, calendar.monthrange(last_y, last_m)[1])
        absences = api_client.get_absences(group, date_from, date_to)
        holidays = api_client.get_holidays(date_from, date_to)
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")

    month_blocks = []
    for i in range(months):
        y, m = _shift(year, month, i)
        month_blocks.append(
            build_context(
                y,
                m,
                object_names,
                absences=_month_absences(absences, y, m),
                holidays=_month_holidays(holidays, y, m),
            )
        )

    # Nav selects: month/year of the first shown month, years centred on today.
    today = date.today()
    year_options = sorted({*range(today.year - 4, today.year + 5), year})
    py, pm = _shift(year, month, -months)
    ny, nm = _shift(year, month, +months)
    context = {
        "months": month_blocks,
        "title": f"{month_blocks[0]['month_name']} {year}",
        "sel_month": month,
        "sel_year": year,
        "sel_count": months,
        "sel_group": group,
        "groups": groups,
        "year_options": year_options,
        "prev_url": f"/{pm:02d}/{py}?months={months}&group={group}",
        "next_url": f"/{nm:02d}/{ny}?months={months}&group={group}",
    }
    # Starlette's current signature: request first, then template name, then context.
    return templates.TemplateResponse(request, "calendar.html", context)


@app.get("/", response_class=HTMLResponse)
def current_month(request: Request, months: int = 1, group: int | None = None):
    today = date.today()
    return _render(request, today.year, today.month, months, group)


@app.get("/{month}/{year}", response_class=HTMLResponse)
def month_view(
    request: Request, month: int, year: int, months: int = 1, group: int | None = None
):
    """e.g. /05/2026 -> May 2026, /05/2026?months=3&group=2 -> May-Jul, group 2."""
    return _render(request, year, month, months, group)
