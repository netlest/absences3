"""HTTP client for the absences backend API.

The frontend renders HTML only; all data comes from the backend service
(default http://127.0.0.1:8001, override with the BACKEND_URL env var).
Tests monkeypatch the module-level functions instead of running a backend.
"""

import os
from datetime import date

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001")
TIMEOUT = 10.0


class BackendUnavailable(Exception):
    """Raised when the backend cannot be reached or errors out."""


def _get(path: str, **params):
    params = {k: v for k, v in params.items() if v is not None}
    try:
        r = httpx.get(f"{BACKEND_URL}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise BackendUnavailable(f"GET {path}: {exc}") from exc
    return r.json()


def get_groups() -> list[dict]:
    return _get("/groups")


def get_objects(group_id: int) -> list[dict]:
    return _get(f"/groups/{group_id}/objects")


def get_absences(group_id: int, date_from: date, date_to: date) -> list[dict]:
    return _get(
        "/absences",
        group_id=group_id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )


def get_holidays(date_from: date, date_to: date) -> list[dict]:
    return _get(
        "/holidays", date_from=date_from.isoformat(), date_to=date_to.isoformat()
    )
