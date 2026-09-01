"""
FastAPI app that renders the monthly absence calendar as a live CSS-grid page.

Data comes from the backend API (see api_client.py); the backend serves it
from PostgreSQL via the v_absences view, which pre-splits absences by month.

Authentication: the backend issues an opaque session token on login, which
this app stores in an HttpOnly cookie and forwards as a Bearer header on
every backend call. No cookie / expired session -> redirect to /login.

Run:
    uv run uvicorn app:app --reload

Then open:
    http://127.0.0.1:8000/                     -> current month, first group
    http://127.0.0.1:8000/05/2026?months=3     -> May-Jul 2026 ( /{month}/{year} )
    http://127.0.0.1:8000/05/2026?group=2      -> another group
"""

import calendar
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import api_client
from calendar_grid import build_context

BASE_DIR = Path(__file__).resolve().parent
SESSION_COOKIE = "session"
# Cookie lifetime tracks the backend session TTL: both read SESSION_TTL_HOURS,
# so one env var keeps them in sync (a cookie outliving its session would
# just bounce the user to /login).
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "48"))
COOKIE_MAX_AGE = SESSION_TTL_HOURS * 3600

app = FastAPI(title="Absences calendar (CSS grid)")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (year, month) shifted by `delta` months."""
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _month_absences(
    absences: list[dict],
    year: int,
    month: int,
    months: int,
    group: int,
    view: tuple[int, int] | None = None,
) -> list[dict]:
    """Grid-shaped absences for one month.

    v_absences rows never cross a month boundary, so matching on the start
    month is exact. Rows the user may modify become links to the edit form,
    carrying `view` — the (year, month) the calendar starts on — so saving
    returns to the same span rather than jumping to the absence's month.
    """
    back = f"&month={view[1]}&year={view[0]}" if view else ""
    key = f"{year:04d}-{month:02d}"
    return [
        {
            "object": a["object_name"],
            "day": int(a["abs_date_start"][8:10]),
            "duration": a["duration"],
            "color": a["color"] or "#7ec8e3",
            "caption": a["description"] or a["type_name"] or "",
            "href": (
                f"/absences/{a['id']}/edit?months={months}&group={group}{back}"
                if a.get("editable")
                else None
            ),
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


def _login_redirect() -> RedirectResponse:
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


def _render(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    months: int | None = None,
    group: int | None = None,
) -> Response:
    """Render the calendar; None arguments fall back to the session's prefs.

    Whatever the request ends up showing is written back to the session, so
    the next visit without query parameters resumes here (last view wins).
    """
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=404, detail="Month must be 1-12")

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()

    try:
        me = api_client.get_me(token)
        prefs = me.get("prefs") or {}
        today = date.today()
        year = year if year is not None else prefs.get("year") or today.year
        month = month if month is not None else prefs.get("month") or today.month
        months = months if months is not None else prefs.get("months") or 1
        group = group if group is not None else prefs.get("group")
        months = max(1, min(12, months))

        groups = api_client.get_groups(token)
        if not groups:
            raise HTTPException(status_code=503, detail="No groups visible")
        if group not in {g["id"] for g in groups}:
            group = groups[0]["id"]

        # Persist the resolved view (best effort — a failed save must not
        # cost the user the page they asked for).
        shown = {"months": months, "month": month, "year": year, "group": group}
        if shown != prefs:
            try:
                api_client.save_prefs(token, shown)
            except api_client.ApiError:
                pass

        group_objects = api_client.get_objects(token, group)
        editable_objects = api_client.get_editable_objects(token)
        editable_ids = {o["id"] for o in editable_objects}
        # Rows of objects the user may manage get add-absence links on
        # their empty day cells (calendar_grid appends &date=...).
        objects_ctx = [
            {
                "name": o["name"],
                "add_base": (
                    f"/absences/new?object_id={o['id']}&months={months}"
                    f"&group={group}&month={month}&year={year}"
                    if o["id"] in editable_ids
                    else None
                ),
            }
            for o in group_objects
        ]

        # One backend round-trip for the whole shown span.
        last_y, last_m = _shift(year, month, months - 1)
        date_from = date(year, month, 1)
        date_to = date(last_y, last_m, calendar.monthrange(last_y, last_m)[1])
        absences = api_client.get_absences(token, group, date_from, date_to)
        holidays = api_client.get_holidays(token, date_from, date_to)
        absence_types = api_client.get_absence_types(token)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")

    month_blocks = []
    for i in range(months):
        y, m = _shift(year, month, i)
        month_blocks.append(
            build_context(
                y,
                m,
                objects_ctx,
                absences=_month_absences(
                    absences, y, m, months, group, view=(year, month)
                ),
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
        "absence_types": absence_types,
        # Modal object choices: editable objects within the shown group.
        "editable_objects": [
            o for o in group_objects if o["id"] in editable_ids
        ],
        "username": me["username"],
        "year_options": year_options,
        "prev_url": f"/{pm:02d}/{py}?months={months}&group={group}",
        "next_url": f"/{nm:02d}/{ny}?months={months}&group={group}",
        "add_url": f"/absences/new?month={month}&year={year}&months={months}&group={group}",
    }
    # Starlette's current signature: request first, then template name, then context.
    return templates.TemplateResponse(request, "calendar.html", context)


# --- auth routes --------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    try:
        result = api_client.login(username, password)
    except api_client.Unauthorized:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=401,
        )
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")

    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        result["token"],
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            api_client.logout(token)
        except (api_client.Unauthorized, api_client.BackendUnavailable):
            pass  # session already gone or backend down — clear the cookie anyway
    return _login_redirect()


@app.get("/password", response_class=HTMLResponse)
def password_page(request: Request):
    if not request.cookies.get(SESSION_COOKIE):
        return _login_redirect()
    return templates.TemplateResponse(
        request, "password.html", {"error": None, "done": False}
    )


@app.post("/password")
def password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()

    def _form(error: str | None, done: bool = False, status_code: int = 200):
        return templates.TemplateResponse(
            request, "password.html", {"error": error, "done": done},
            status_code=status_code,
        )

    if new_password != confirm_password:
        return _form("New passwords do not match", status_code=400)
    try:
        api_client.change_password(token, current_password, new_password)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.ApiError as exc:
        return _form(str(exc), status_code=400)
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    return _form(None, done=True)


@app.post("/password/change")
def password_change_api(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    """JSON variant used by the password modal (fetch submit)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="New passwords do not match")
    try:
        api_client.change_password(token, current_password, new_password)
    except api_client.Unauthorized:
        raise HTTPException(status_code=401, detail="Session expired")
    except api_client.ApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    return {"status": "ok"}


# --- absence add / edit / delete ----------------------------------------------


def _absence_form(
    request: Request,
    token: str,
    *,
    absence: dict | None,
    error: str | None,
    months: int,
    group: int,
    form: dict | None = None,
    status_code: int = 200,
    month: int | None = None,
    year: int | None = None,
) -> Response:
    """Render the add/edit form. `form` re-fills fields after an error."""
    try:
        objects = api_client.get_editable_objects(token)
        types = api_client.get_absence_types(token)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    values = form or absence or {}
    context = {
        "absence": absence,
        "objects": objects,
        "types": types,
        "values": values,
        "error": error,
        "months": months,
        "group": group,
        "month": month,
        "year": year,
    }
    return templates.TemplateResponse(
        request, "absence_form.html", context, status_code=status_code
    )


def _back_url(
    months: int,
    group: int,
    month: int | None = None,
    year: int | None = None,
    start: date | None = None,
) -> str:
    """Calendar view to return to after saving.

    Prefers the view the user came from — its first month, not the month the
    absence happens to fall in — so a 4-month view starting in October comes
    back unchanged after adding an absence in November. Falls back to the
    absence's own month for callers that don't carry the view.
    """
    if month is None or year is None:
        if start is None:
            return f"/?months={months}&group={group}"
        month, year = start.month, start.year
    return f"/{month:02d}/{year}?months={months}&group={group}"


@app.get("/absences/new", response_class=HTMLResponse)
def absence_new(
    request: Request,
    months: int = 1,
    group: int = 1,
    object_id: int | None = None,
    date: date | None = None,
    month: int | None = None,
    year: int | None = None,
):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()
    prefill = {}
    if object_id is not None:
        prefill["object_id"] = object_id
    if date is not None:
        prefill["abs_date_start"] = date.isoformat()
        prefill["abs_date_end"] = date.isoformat()
    return _absence_form(
        request, token, absence=None, error=None,
        months=months, group=group, form=prefill or None,
        month=month, year=year,
    )


@app.post("/absences/new")
def absence_create(
    request: Request,
    object_id: int = Form(...),
    type_id: int = Form(...),
    abs_date_start: date = Form(...),
    abs_date_end: date = Form(...),
    description: str = Form(""),
    months: int = Form(1),
    group: int = Form(1),
    month: int | None = Form(None),
    year: int | None = Form(None),
):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()
    payload = {
        "object_id": object_id,
        "type_id": type_id,
        "abs_date_start": abs_date_start.isoformat(),
        "abs_date_end": abs_date_end.isoformat(),
        "description": description.strip() or None,
    }
    try:
        api_client.create_absence(token, payload)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.ApiError as exc:
        return _absence_form(
            request, token, absence=None, error=str(exc),
            months=months, group=group, form=payload, status_code=400,
            month=month, year=year,
        )
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    return RedirectResponse(
        _back_url(months, group, month, year, abs_date_start), status_code=303
    )


@app.get("/absences/{absence_id}/data")
def absence_data(request: Request, absence_id: int):
    """Raw absence as JSON — used by the edit modal to prefill its fields
    (grid blocks only carry month-clipped dates)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        absence = api_client.get_absence(token, absence_id)
    except api_client.Unauthorized:
        raise HTTPException(status_code=401, detail="Session expired")
    except api_client.ApiError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    if not absence["editable"]:
        raise HTTPException(status_code=403, detail="Not your absence")
    return absence


@app.get("/absences/{absence_id}/edit", response_class=HTMLResponse)
def absence_edit(
    request: Request,
    absence_id: int,
    months: int = 1,
    group: int = 1,
    month: int | None = None,
    year: int | None = None,
):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()
    try:
        absence = api_client.get_absence(token, absence_id)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.ApiError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    if not absence["editable"]:
        raise HTTPException(status_code=403, detail="Not your absence")
    return _absence_form(
        request, token, absence=absence, error=None, months=months, group=group,
        month=month, year=year,
    )


@app.post("/absences/{absence_id}/edit")
def absence_update(
    request: Request,
    absence_id: int,
    object_id: int = Form(...),
    type_id: int = Form(...),
    abs_date_start: date = Form(...),
    abs_date_end: date = Form(...),
    description: str = Form(""),
    months: int = Form(1),
    group: int = Form(1),
    month: int | None = Form(None),
    year: int | None = Form(None),
):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()
    payload = {
        "object_id": object_id,
        "type_id": type_id,
        "abs_date_start": abs_date_start.isoformat(),
        "abs_date_end": abs_date_end.isoformat(),
        "description": description.strip() or None,
    }
    try:
        api_client.update_absence(token, absence_id, payload)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.ApiError as exc:
        return _absence_form(
            request, token, absence={"id": absence_id, **payload},
            error=str(exc), months=months, group=group, form=payload,
            status_code=400, month=month, year=year,
        )
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    return RedirectResponse(
        _back_url(months, group, month, year, abs_date_start), status_code=303
    )


@app.post("/absences/{absence_id}/delete")
def absence_delete(
    request: Request,
    absence_id: int,
    months: int = Form(1),
    group: int = Form(1),
    abs_date_start: date | None = Form(None),
    month: int | None = Form(None),
    year: int | None = Form(None),
):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _login_redirect()
    try:
        api_client.delete_absence(token, absence_id)
    except api_client.Unauthorized:
        return _login_redirect()
    except api_client.ApiError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")
    return RedirectResponse(
        _back_url(months, group, month, year, abs_date_start), status_code=303
    )


# --- manage pages ---------------------------------------------------------------
# Registered before the /{month}/{year} route below, which would otherwise
# swallow /manage/* paths.

import manage  # noqa: E402  (needs `templates` above)

app.include_router(manage.router)


# --- calendar routes ----------------------------------------------------------


@app.get("/debug/session")
def debug_session(request: Request) -> JSONResponse:
    """Dump the caller's own session as JSON, for debugging.

    Shows the session cookie this request carried and the payload the backend
    keeps for that token in `sessions.data` (user_id / username / admin).
    Scoped to the caller: it reads only the cookie the browser sent, so it
    cannot reveal anyone else's session. Always answers 200 — `status` says
    what happened, so a failure is readable in the browser instead of an
    error page.
    """
    token = request.cookies.get(SESSION_COOKIE)
    info: dict = {
        "status": "ok",
        "cookie_name": SESSION_COOKIE,
        "cookie_present": token is not None,
        "token": token,
        "cookie_max_age": COOKIE_MAX_AGE,
        "backend_url": api_client.BACKEND_URL,
        "data": None,
    }

    if token is None:
        info["status"] = "no-cookie"
        return JSONResponse(info)

    try:
        info["data"] = api_client.get_me(token)
    except api_client.Unauthorized as exc:
        info["status"] = "invalid-or-expired"
        info["error"] = str(exc)
    except api_client.BackendUnavailable as exc:
        info["status"] = "backend-unavailable"
        info["error"] = str(exc)

    return JSONResponse(info)


@app.get("/", response_class=HTMLResponse)
def current_month(
    request: Request, months: int | None = None, group: int | None = None
):
    """Resumes the session's last view; falls back to the current month."""
    return _render(request, None, None, months, group)


@app.get("/{month}/{year}", response_class=HTMLResponse)
def month_view(
    request: Request,
    month: int,
    year: int,
    months: int | None = None,
    group: int | None = None,
):
    """e.g. /05/2026 -> May 2026, /05/2026?months=3&group=2 -> May-Jul, group 2."""
    return _render(request, year, month, months, group)
