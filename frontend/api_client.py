"""HTTP client for the absences backend API.

The frontend renders HTML only; all data comes from the backend service
(default http://127.0.0.1:8001, override with the BACKEND_URL env var).
Every data call carries the user's session token as a Bearer header; the
token comes from the frontend's HttpOnly session cookie.

Tests monkeypatch the module-level functions instead of running a backend.
"""

import os
from datetime import date

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001")
TIMEOUT = 10.0


class BackendUnavailable(Exception):
    """Raised when the backend cannot be reached or errors out."""


class Unauthorized(Exception):
    """Raised on 401 — no session or expired session; the user must log in."""


class ApiError(Exception):
    """Raised on 4xx responses (validation, permissions, unknown ids).

    str(exc) is the backend's human-readable `detail`.
    """


class ValidationApiError(ApiError):
    """Raised on 422 — Pydantic field errors, as a {field: message} dict."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("Invalid input")
        self.errors = errors


def _field_errors(detail) -> dict[str, str]:
    """Flatten FastAPI's 422 detail list into {field_name: message}."""
    errors: dict[str, str] = {}
    if isinstance(detail, list):
        for e in detail:
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query")]
            errors[loc[0] if loc else "__all__"] = e.get("msg", "Invalid value")
    return errors


def _request(method: str, path: str, token: str | None = None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            headers=headers,
            timeout=TIMEOUT,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise BackendUnavailable(f"{method} {path}: {exc}") from exc
    if r.status_code == 401:
        raise Unauthorized(r.json().get("detail", "unauthorized"))
    if r.status_code == 422:
        raise ValidationApiError(_field_errors(r.json().get("detail")))
    if 400 <= r.status_code < 500:
        detail = r.json().get("detail", f"request failed ({r.status_code})")
        if not isinstance(detail, str):
            detail = "Invalid input"
        raise ApiError(detail)
    try:
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise BackendUnavailable(f"{method} {path}: {exc}") from exc
    return r.json()


def _get(path: str, token: str | None = None, **params):
    params = {k: v for k, v in params.items() if v is not None}
    return _request("GET", path, token, params=params)


# --- auth --------------------------------------------------------------------


def login(username: str, password: str) -> dict:
    """Returns {"token": ..., "user": {...}}; raises Unauthorized on bad creds."""
    return _request(
        "POST", "/auth/login", json={"username": username, "password": password}
    )


def logout(token: str) -> None:
    _request("POST", "/auth/logout", token)


def get_me(token: str) -> dict:
    return _get("/auth/me", token)


def change_password(token: str, current_password: str, new_password: str) -> None:
    _request(
        "POST",
        "/auth/password",
        token,
        json={"current_password": current_password, "new_password": new_password},
    )


# --- data --------------------------------------------------------------------


def get_groups(token: str) -> list[dict]:
    return _get("/groups", token)


def get_absence_types(token: str) -> list[dict]:
    return _get("/absence_types", token)


def get_objects(token: str, group_id: int) -> list[dict]:
    return _get(f"/groups/{group_id}/objects", token)


def get_absences(
    token: str, group_id: int, date_from: date, date_to: date
) -> list[dict]:
    return _get(
        "/absences",
        token,
        group_id=group_id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )


def get_holidays(token: str, date_from: date, date_to: date) -> list[dict]:
    return _get(
        "/holidays",
        token,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )


# --- absence management --------------------------------------------------------


def get_editable_objects(token: str) -> list[dict]:
    """Objects the user may add absences to (all objects for admins)."""
    return _get("/objects", token)


def get_absence(token: str, absence_id: int) -> dict:
    return _get(f"/absences/{absence_id}", token)


def create_absence(token: str, payload: dict) -> dict:
    return _request("POST", "/absences", token, json=payload)


def update_absence(token: str, absence_id: int, payload: dict) -> dict:
    return _request("PUT", f"/absences/{absence_id}", token, json=payload)


def delete_absence(token: str, absence_id: int) -> None:
    _request("DELETE", f"/absences/{absence_id}", token)


# --- generic management resources (see manage.py) -----------------------------


class Resource:
    """REST client for one backend collection: list/create/update/delete.

    New managed entities get a Resource here plus an Entity spec in
    manage_entities.py — no bespoke request code.
    """

    def __init__(self, path: str):
        self.path = path

    def list(self, token: str, **params) -> list[dict]:
        return _get(self.path, token, **params)

    def create(self, token: str, payload: dict) -> dict:
        return _request("POST", self.path, token, json=payload)

    def update(self, token: str, item_id: int, payload: dict) -> dict:
        return _request("PUT", f"{self.path}/{item_id}", token, json=payload)

    def delete(self, token: str, item_id: int) -> None:
        _request("DELETE", f"{self.path}/{item_id}", token)


users = Resource("/users")
groups_admin = Resource("/groups")
objects = Resource("/objects")
absence_types = Resource("/absence_types")
holidays = Resource("/holidays")
absences = Resource("/absences")


def get_manage_absences(
    token: str,
    year: int | None = None,
    object_id: int | None = None,
    page: int | None = None,
) -> dict:
    """Raw (un-split) absences the user may manage, for the manage table.

    Paginated: {"rows", "total", "page", "per_page", "pages", "years"}.
    """
    return _get(
        "/manage/absences", token, year=year, object_id=object_id, page=page
    )


def get_holidays_all(token: str) -> list[dict]:
    """Raw holiday rows without recurring expansion (admin only)."""
    return _get("/holidays/all", token)


def get_group_members(token: str, group_id: int) -> list[dict]:
    return _get(f"/groups/{group_id}/members", token)


def add_group_member(token: str, group_id: int, user_id: int) -> None:
    _request(
        "POST", f"/groups/{group_id}/members", token, json={"user_id": user_id}
    )


def remove_group_member(token: str, group_id: int, user_id: int) -> None:
    _request("DELETE", f"/groups/{group_id}/members/{user_id}", token)
