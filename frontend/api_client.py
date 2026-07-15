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
    if 400 <= r.status_code < 500:
        detail = r.json().get("detail", f"request failed ({r.status_code})")
        if not isinstance(detail, str):  # pydantic validation errors are lists
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
