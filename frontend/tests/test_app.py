"""Smoke tests for the CSS-grid calendar app.

The backend API is stubbed by monkeypatching api_client, so no database or
backend process is needed. Run with:  uv run pytest
"""

import pytest
from fastapi.testclient import TestClient

import api_client
from app import app

TOKEN = "test-session-token"
ME = {"user_id": 1, "username": "admin", "admin": True}

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
        "type_name": "Urlop", "editable": True,
    },
    {
        "id": 2, "object_id": 5, "object_name": "Wakacje",
        "group_id": 1, "user_id": 1, "type_id": 8,
        "abs_date_start": "2026-06-01", "abs_date_end": "2026-06-30",
        "duration": 30, "description": "Wakacje!", "color": "#9f4800",
        "type_name": "Wakacje", "editable": True,
    },
    {
        "id": 3, "object_id": 7, "object_name": "Piotr Hamerski",
        "group_id": 2, "user_id": 1, "type_id": 4,
        "abs_date_start": "2026-05-20", "abs_date_end": "2026-05-22",
        "duration": 3, "description": "OOO", "color": "#f6b26b",
        "type_name": "Urlop", "editable": False,
    },
]
HOLIDAYS = [
    {"date": "2026-05-01", "description": "Święto Pracy"},
    {"date": "2026-05-03", "description": "Święto Konstytucji"},
]
ABSENCE_TYPES = [
    {"id": 4, "name": "Urlop", "color": "#1ac938"},
    {"id": 8, "name": "Wakacje", "color": "#9f4800"},
]


def _check(token):
    if token != TOKEN:
        raise api_client.Unauthorized("Invalid or expired session")


def _in_range(day: str, date_from, date_to) -> bool:
    return date_from.isoformat() <= day <= date_to.isoformat()


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    def fake_login(username, password):
        if (username, password) != ("admin", "secret"):
            raise api_client.Unauthorized("Invalid username or password")
        return {"token": TOKEN, "user": ME}

    def fake_me(token):
        _check(token)
        return ME

    def fake_groups(token):
        _check(token)
        return GROUPS

    def fake_types(token):
        _check(token)
        return ABSENCE_TYPES

    def fake_objects(token, gid):
        _check(token)
        return OBJECTS.get(gid, [])

    def fake_absences(token, gid, date_from, date_to):
        _check(token)
        return [
            a for a in ABSENCES
            if a["group_id"] == gid
            and _in_range(a["abs_date_start"], date_from, date_to)
        ]

    def fake_holidays(token, date_from, date_to):
        _check(token)
        return [h for h in HOLIDAYS if _in_range(h["date"], date_from, date_to)]

    def fake_editable_objects(token):
        _check(token)
        return [o for objs in OBJECTS.values() for o in objs]

    def fake_get_absence(token, absence_id):
        _check(token)
        for a in ABSENCES:
            if a["id"] == absence_id:
                return a
        raise api_client.ApiError("Absence not found")

    calls = {"created": [], "updated": [], "deleted": []}

    def fake_create(token, payload):
        _check(token)
        if payload["abs_date_end"] < payload["abs_date_start"]:
            raise api_client.ApiError("End date is before start date")
        calls["created"].append(payload)
        return {"id": 99}

    def fake_update(token, absence_id, payload):
        _check(token)
        calls["updated"].append((absence_id, payload))
        return {"id": absence_id}

    def fake_delete(token, absence_id):
        _check(token)
        calls["deleted"].append(absence_id)

    monkeypatch.setattr(api_client, "login", fake_login)
    monkeypatch.setattr(api_client, "logout", lambda token: _check(token))
    monkeypatch.setattr(api_client, "get_me", fake_me)
    monkeypatch.setattr(api_client, "get_groups", fake_groups)
    monkeypatch.setattr(api_client, "get_absence_types", fake_types)
    monkeypatch.setattr(api_client, "get_objects", fake_objects)
    monkeypatch.setattr(api_client, "get_absences", fake_absences)
    monkeypatch.setattr(api_client, "get_holidays", fake_holidays)
    monkeypatch.setattr(api_client, "get_editable_objects", fake_editable_objects)
    monkeypatch.setattr(api_client, "get_absence", fake_get_absence)
    monkeypatch.setattr(api_client, "create_absence", fake_create)
    monkeypatch.setattr(api_client, "update_absence", fake_update)
    monkeypatch.setattr(api_client, "delete_absence", fake_delete)
    return calls


@pytest.fixture
def client():
    """Logged-in client."""
    c = TestClient(app)
    c.cookies.set("session", TOKEN)
    return c


@pytest.fixture
def anon():
    """Client without a session cookie."""
    return TestClient(app)


# --- authentication ------------------------------------------------------


def test_anonymous_is_redirected_to_login(anon):
    r = anon.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_invalid_session_is_redirected_and_cookie_cleared(anon):
    anon.cookies.set("session", "stale-token")
    r = anon.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert 'session=""' in r.headers.get("set-cookie", "")


def test_login_page_renders(anon):
    r = anon.get("/login")
    assert r.status_code == 200
    assert 'name="password"' in r.text


def test_login_success_sets_cookie_and_redirects(anon):
    r = anon.post(
        "/login",
        data={"username": "admin", "password": "secret"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert f"session={TOKEN}" in cookie
    assert "HttpOnly" in cookie


def test_login_bad_credentials_shows_error(anon):
    r = anon.post("/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid username or password" in r.text


def test_logout_clears_cookie_and_redirects(client):
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert 'session=""' in r.headers.get("set-cookie", "")


def test_nav_shows_username_and_logout(client):
    r = client.get("/")
    assert "admin" in r.text
    assert 'action="/logout"' in r.text


# --- calendar ------------------------------------------------------------


def test_root_returns_current_month(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "cal-grid" in r.text


def test_month_route_renders_may_2026(client):
    r = client.get("/05/2026")
    assert r.status_code == 200
    assert "May 2026" in r.text
    assert "CW" in r.text  # ISO week bars are drawn
    assert "Urlop" in r.text  # absence from the (stubbed) backend


def test_may_2026_marks_holidays(client):
    # Two stubbed holidays in May 2026 -> magenta cells.
    r = client.get("/05/2026")
    assert "#e121ff" in r.text


def test_september_is_30_days_with_pad_column(client):
    r = client.get("/09/2026")
    assert r.status_code == 200
    # 30-day month -> at least one dark padding cell for the missing 31st.
    assert "#605060" in r.text


def test_default_group_shows_its_object_rows(client):
    r = client.get("/05/2026")
    assert r.status_code == 200
    for name in ["Adam", "Kinga", "Wakacje"]:
        assert name in r.text
    assert "Piotr Hamerski" not in r.text  # belongs to group 2


def test_group_param_switches_rows_and_absences(client):
    r = client.get("/05/2026?group=2")
    assert r.status_code == 200
    assert "Piotr Hamerski" in r.text
    assert "OOO" in r.text
    assert "Kinga" not in r.text


def test_group_dropdown_lists_groups(client):
    r = client.get("/")
    assert 'id="nav-group"' in r.text
    assert "Default" in r.text and "HSBC" in r.text


def test_multi_month_span_renders_each_grid(client):
    r = client.get("/05/2026?months=2")
    assert "May 2026" in r.text
    assert "June 2026" in r.text
    assert "Wakacje!" in r.text  # June absence included in the span


def test_unknown_group_falls_back_to_first(client):
    r = client.get("/05/2026?group=999")
    assert r.status_code == 200
    assert "Adam" in r.text


def test_legend_shows_absence_types_with_colors(client):
    r = client.get("/")
    assert "Legend" in r.text
    for t in ABSENCE_TYPES:
        assert t["name"] in r.text
        assert t["color"] in r.text


# --- absence add / edit / delete ------------------------------------------


def test_add_form_renders_objects_and_types(client):
    r = client.get("/absences/new")
    assert r.status_code == 200
    assert 'name="object_id"' in r.text
    assert 'name="type_id"' in r.text
    assert "Adam  Zaleski" in r.text
    assert "Urlop" in r.text


def test_create_absence_posts_and_redirects(client, fake_backend):
    r = client.post(
        "/absences/new",
        data={
            "object_id": 1, "type_id": 4,
            "abs_date_start": "2026-08-10", "abs_date_end": "2026-08-14",
            "description": "Test", "months": 2, "group": 1,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/08/2026?months=2&group=1"
    assert fake_backend["created"] == [{
        "object_id": 1, "type_id": 4,
        "abs_date_start": "2026-08-10", "abs_date_end": "2026-08-14",
        "description": "Test",
    }]


def test_create_absence_validation_error_shows_in_form(client, fake_backend):
    r = client.post(
        "/absences/new",
        data={
            "object_id": 1, "type_id": 4,
            "abs_date_start": "2026-08-14", "abs_date_end": "2026-08-10",
            "description": "", "months": 1, "group": 1,
        },
    )
    assert r.status_code == 400
    assert "End date is before start date" in r.text
    assert fake_backend["created"] == []


def test_edit_form_is_prefilled(client):
    r = client.get("/absences/1/edit")
    assert r.status_code == 200
    assert 'value="2026-05-06"' in r.text
    assert 'value="2026-05-15"' in r.text
    assert 'value="Urlop"' in r.text
    assert 'action="/absences/1/delete"' in r.text


def test_edit_non_editable_absence_forbidden(client):
    r = client.get("/absences/3/edit")  # editable: False in stub data
    assert r.status_code == 403


def test_update_absence_posts_and_redirects(client, fake_backend):
    r = client.post(
        "/absences/1/edit",
        data={
            "object_id": 1, "type_id": 8,
            "abs_date_start": "2026-05-07", "abs_date_end": "2026-05-16",
            "description": "Urlop dłużej", "months": 1, "group": 1,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/05/2026?months=1&group=1"
    assert fake_backend["updated"][0][0] == 1


def test_delete_absence_posts_and_redirects(client, fake_backend):
    r = client.post(
        "/absences/1/delete",
        data={"months": 1, "group": 1, "abs_date_start": "2026-05-06"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/05/2026?months=1&group=1"
    assert fake_backend["deleted"] == [1]


def test_editable_absence_is_link_in_grid(client):
    r = client.get("/05/2026")
    assert 'href="/absences/1/edit?months=1&amp;group=1"' in r.text


def test_non_editable_absence_is_not_link(client):
    r = client.get("/05/2026?group=2")
    assert "OOO" in r.text
    assert "/absences/3/edit" not in r.text


def test_empty_cell_in_own_row_links_to_prefilled_add_form(client):
    r = client.get("/05/2026")
    # May 1 is free for Adam (object 1): the empty cell links to the add
    # form with the object and the clicked date preselected.
    assert (
        'href="/absences/new?object_id=1&amp;months=1&amp;group=1&amp;date=2026-05-01"'
        in r.text
    )


def test_add_form_page_prefills_from_query(client):
    r = client.get("/absences/new?object_id=2&date=2026-05-06")
    assert r.status_code == 200
    assert 'value="2026-05-06"' in r.text  # both From and To
    assert '<option value="2" selected>' in r.text


def test_calendar_contains_add_modal(client):
    r = client.get("/")
    assert 'id="add-modal"' in r.text
    assert "showModal" in r.text
    for o in ("Adam  Zaleski", "Kinga Zaleska"):
        assert o in r.text  # modal object select options


def test_absence_data_returns_raw_absence(client):
    r = client.get("/absences/1/data")
    assert r.status_code == 200
    body = r.json()
    assert body["object_id"] == 1
    assert body["abs_date_start"] == "2026-05-06"
    assert body["abs_date_end"] == "2026-05-15"


def test_absence_data_forbidden_for_non_editable(client):
    r = client.get("/absences/3/data")  # editable: False in stub data
    assert r.status_code == 403


def test_absence_data_unknown_id_404(client):
    r = client.get("/absences/12345/data")
    assert r.status_code == 404


def test_modal_supports_edit_mode(client):
    r = client.get("/")
    assert 'id="modal-delete"' in r.text
    assert "openEditModal" in r.text
    assert "/data" in r.text


def test_nav_has_add_absence_button(client):
    r = client.get("/")
    assert "Add absence" in r.text
    assert "/absences/new?" in r.text


def test_invalid_month_returns_404(client):
    r = client.get("/13/2026")
    assert r.status_code == 404


def test_backend_down_returns_503(client, monkeypatch):
    def boom(token):
        raise api_client.BackendUnavailable("GET /auth/me: connection refused")

    monkeypatch.setattr(api_client, "get_me", boom)
    r = client.get("/")
    assert r.status_code == 503
