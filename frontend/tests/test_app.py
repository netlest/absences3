"""Smoke tests for the CSS-grid calendar app.

The backend API is stubbed by monkeypatching api_client, so no database or
backend process is needed. Run with:  uv run pytest
"""

import pytest
from fastapi.testclient import TestClient

import api_client
from app import app

client = TestClient(app)

GROUPS = [
    {"id": 1, "name": "Default", "description": "Default group"},
    {"id": 2, "name": "HSBC", "description": "HSBC"},
]
OBJECTS = {
    1: [
        {"id": 1, "name": "Adam  Zaleski"},
        {"id": 2, "name": "Kinga Zaleska"},
        {"id": 5, "name": "Wakacje"},
    ],
    2: [
        {"id": 7, "name": "Piotr Hamerski"},
        {"id": 8, "name": "Łukasz Zegar"},
    ],
}
# Month-split rows, like v_absences returns them.
ABSENCES = [
    {
        "id": 1, "object_id": 1, "object_name": "Adam  Zaleski",
        "group_id": 1, "user_id": 1, "type_id": 4,
        "abs_date_start": "2026-05-06", "abs_date_end": "2026-05-15",
        "duration": 10, "description": "Urlop", "color": "#7ec8e3",
        "type_name": "Urlop",
    },
    {
        "id": 2, "object_id": 5, "object_name": "Wakacje",
        "group_id": 1, "user_id": 1, "type_id": 8,
        "abs_date_start": "2026-06-01", "abs_date_end": "2026-06-30",
        "duration": 30, "description": "Wakacje!", "color": "#9f4800",
        "type_name": "Wakacje",
    },
    {
        "id": 3, "object_id": 7, "object_name": "Piotr Hamerski",
        "group_id": 2, "user_id": 1, "type_id": 4,
        "abs_date_start": "2026-05-20", "abs_date_end": "2026-05-22",
        "duration": 3, "description": "OOO", "color": "#f6b26b",
        "type_name": "Urlop",
    },
]
HOLIDAYS = [
    {"date": "2026-05-01", "description": "Święto Pracy"},
    {"date": "2026-05-03", "description": "Święto Konstytucji"},
]


def _in_range(day: str, date_from, date_to) -> bool:
    return date_from.isoformat() <= day <= date_to.isoformat()


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    monkeypatch.setattr(api_client, "get_groups", lambda: GROUPS)
    monkeypatch.setattr(api_client, "get_objects", lambda gid: OBJECTS.get(gid, []))
    monkeypatch.setattr(
        api_client,
        "get_absences",
        lambda gid, date_from, date_to: [
            a for a in ABSENCES
            if a["group_id"] == gid
            and _in_range(a["abs_date_start"], date_from, date_to)
        ],
    )
    monkeypatch.setattr(
        api_client,
        "get_holidays",
        lambda date_from, date_to: [
            h for h in HOLIDAYS if _in_range(h["date"], date_from, date_to)
        ],
    )


def test_root_returns_current_month():
    r = client.get("/")
    assert r.status_code == 200
    assert "cal-grid" in r.text


def test_month_route_renders_may_2026():
    r = client.get("/05/2026")
    assert r.status_code == 200
    assert "May 2026" in r.text
    assert "CW" in r.text  # ISO week bars are drawn
    assert "Urlop" in r.text  # absence from the (stubbed) backend


def test_may_2026_marks_holidays():
    # Two stubbed holidays in May 2026 -> magenta cells.
    r = client.get("/05/2026")
    assert "#e121ff" in r.text


def test_september_is_30_days_with_pad_column():
    r = client.get("/09/2026")
    assert r.status_code == 200
    # 30-day month -> at least one dark padding cell for the missing 31st.
    assert "#605060" in r.text


def test_default_group_shows_its_object_rows():
    r = client.get("/05/2026")
    assert r.status_code == 200
    for name in ["Adam", "Kinga", "Wakacje"]:
        assert name in r.text
    assert "Piotr Hamerski" not in r.text  # belongs to group 2


def test_group_param_switches_rows_and_absences():
    r = client.get("/05/2026?group=2")
    assert r.status_code == 200
    assert "Piotr Hamerski" in r.text
    assert "OOO" in r.text
    assert "Kinga" not in r.text


def test_group_dropdown_lists_groups():
    r = client.get("/")
    assert 'id="nav-group"' in r.text
    assert "Default" in r.text and "HSBC" in r.text


def test_multi_month_span_renders_each_grid():
    r = client.get("/05/2026?months=2")
    assert "May 2026" in r.text
    assert "June 2026" in r.text
    assert "Wakacje!" in r.text  # June absence included in the span


def test_unknown_group_falls_back_to_first():
    r = client.get("/05/2026?group=999")
    assert r.status_code == 200
    assert "Adam" in r.text


def test_invalid_month_returns_404():
    r = client.get("/13/2026")
    assert r.status_code == 404


def test_backend_down_returns_503(monkeypatch):
    def boom():
        raise api_client.BackendUnavailable("GET /groups: connection refused")

    monkeypatch.setattr(api_client, "get_groups", boom)
    r = client.get("/")
    assert r.status_code == 503
