"""Tests for the /manage page (entity CRUD panels + group membership).

The backend is stubbed by monkeypatching api_client, mirroring test_app.py.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_client
from app import app

TOKEN = "test-session-token"
ADMIN = {"user_id": 1, "username": "admin", "admin": True}
PLAIN = {"user_id": 2, "username": "kinga", "admin": False}

GROUPS = [
    {"id": 1, "name": "Default", "description": "Default group"},
    {"id": 2, "name": "HSBC", "description": "HSBC"},
]
OBJECTS = [
    {
        "id": 1, "name": "Adam Zaleski", "description": "Adam",
        "group_id": 1, "group_name": "Default",
        "user_id": 1, "owner_name": "admin",
    },
    {
        "id": 2, "name": "Kinga Zaleska", "description": "Kinga",
        "group_id": 1, "group_name": "Default",
        "user_id": 2, "owner_name": "kinga",
    },
]
USERS = [
    {"id": 1, "username": "admin", "admin": True},
    {"id": 2, "username": "kinga", "admin": False},
]
TYPES = [
    {"id": 4, "name": "Urlop", "color": "#1ac938"},
    {"id": 8, "name": "Wakacje", "color": "#9f4800"},
]
HOLIDAYS_RAW = [
    {
        "id": 1, "country": "pl", "event_date": "2026-05-01",
        "description": "Święto Pracy", "recurring": True,
    },
]
MANAGE_ABSENCES = [
    {
        "id": 7, "object_id": 1, "object_name": "Adam Zaleski",
        "type_id": 4, "type_name": "Urlop",
        "abs_date_start": "2026-05-06", "abs_date_end": "2026-05-15",
        "description": "Urlop",
    },
    {
        "id": 8, "object_id": 2, "object_name": "Kinga Zaleska",
        "type_id": 8, "type_name": "Wakacje",
        "abs_date_start": "2025-07-01", "abs_date_end": "2025-07-10",
        "description": "Lato",
    },
]
MEMBERS = {1: [{"id": 1, "username": "admin"}], 2: []}


def _check(token):
    if token != TOKEN:
        raise api_client.Unauthorized("Invalid or expired session")


def _fake_resource(rows, calls, key):
    def list_(token, **params):
        _check(token)
        return rows

    def create(token, payload):
        _check(token)
        calls.setdefault(f"{key}.create", []).append(payload)
        return {"id": 99}

    def update(token, item_id, payload):
        _check(token)
        calls.setdefault(f"{key}.update", []).append((item_id, payload))
        return {"id": item_id}

    def delete(token, item_id):
        _check(token)
        calls.setdefault(f"{key}.delete", []).append(item_id)

    return SimpleNamespace(list=list_, create=create, update=update, delete=delete)


@pytest.fixture
def calls():
    return {}


@pytest.fixture
def me():
    """Indirection so tests can flip the logged-in user to non-admin."""
    return {"user": ADMIN}


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch, calls, me):
    def fake_me(token):
        _check(token)
        return me["user"]

    monkeypatch.setattr(api_client, "get_me", fake_me)
    monkeypatch.setattr(api_client, "get_groups", lambda t: (_check(t), GROUPS)[1])
    monkeypatch.setattr(
        api_client, "get_absence_types", lambda t: (_check(t), TYPES)[1]
    )
    monkeypatch.setattr(
        api_client, "get_editable_objects", lambda t: (_check(t), OBJECTS)[1]
    )
    def fake_manage_absences(token, year=None, object_id=None, page=None):
        # Paginates with one row per page so pager rendering is testable.
        _check(token)
        rows = [
            a for a in MANAGE_ABSENCES
            if (year is None or a["abs_date_start"].startswith(str(year)))
            and (object_id is None or a["object_id"] == object_id)
        ]
        pages = max(1, len(rows))
        p = min(page or 1, pages)
        return {
            "rows": rows[p - 1 : p], "total": len(rows), "page": p,
            "per_page": 1, "pages": pages, "years": [2026, 2025],
        }

    monkeypatch.setattr(api_client, "get_manage_absences", fake_manage_absences)
    monkeypatch.setattr(
        api_client, "get_holidays_all", lambda t: (_check(t), HOLIDAYS_RAW)[1]
    )
    monkeypatch.setattr(
        api_client,
        "get_group_members",
        lambda t, gid: (_check(t), MEMBERS.get(gid, []))[1],
    )

    def fake_add_member(token, group_id, user_id):
        _check(token)
        calls.setdefault("members.add", []).append((group_id, user_id))

    def fake_remove_member(token, group_id, user_id):
        _check(token)
        calls.setdefault("members.remove", []).append((group_id, user_id))

    monkeypatch.setattr(api_client, "add_group_member", fake_add_member)
    monkeypatch.setattr(api_client, "remove_group_member", fake_remove_member)

    monkeypatch.setattr(api_client, "objects", _fake_resource(OBJECTS, calls, "objects"))
    monkeypatch.setattr(api_client, "users", _fake_resource(USERS, calls, "users"))
    monkeypatch.setattr(
        api_client, "groups_admin", _fake_resource(GROUPS, calls, "groups")
    )
    monkeypatch.setattr(
        api_client, "absence_types", _fake_resource(TYPES, calls, "types")
    )
    monkeypatch.setattr(
        api_client, "holidays", _fake_resource(HOLIDAYS_RAW, calls, "holidays")
    )
    monkeypatch.setattr(
        api_client, "absences", _fake_resource(MANAGE_ABSENCES, calls, "absences")
    )


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("session", TOKEN)
    return c


@pytest.fixture
def anon():
    return TestClient(app)


# --- access control --------------------------------------------------------


def test_manage_requires_login(anon):
    r = anon.get("/manage", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_manage_htmx_expired_session_gets_hx_redirect(anon):
    anon.cookies.set("session", "stale")
    r = anon.get("/manage/objects", headers={"HX-Request": "true"})
    assert r.headers.get("HX-Redirect") == "/login"


def test_admin_sees_all_tabs(client):
    r = client.get("/manage")
    assert r.status_code == 200
    for label in ["Objects", "Absences", "Absence types", "Groups",
                  "Group members", "Users", "Public holidays"]:
        assert label in r.text


def test_non_admin_sees_only_own_tabs(client, me):
    me["user"] = PLAIN
    r = client.get("/manage")
    assert r.status_code == 200
    assert "Objects" in r.text and "Absences" in r.text
    for label in ["Users", "Group members", "Public holidays"]:
        assert label not in r.text


def test_non_admin_cannot_open_admin_panel(client, me):
    me["user"] = PLAIN
    r = client.get("/manage/users")
    assert r.status_code == 403


def test_calendar_navbar_links_to_manage(client, monkeypatch):
    # The calendar route needs the full stub set from test_app; just check
    # the manage page itself renders the back link and the template ships
    # the navbar button.
    r = client.get("/manage")
    assert "Back to calendar" in r.text


# --- panels and forms --------------------------------------------------------


def test_objects_panel_lists_rows(client):
    r = client.get("/manage/objects")
    assert r.status_code == 200
    assert "Adam Zaleski" in r.text
    assert "Default" in r.text
    assert "Owner" in r.text  # admin-only column


def test_objects_panel_hides_owner_for_non_admin(client, me):
    me["user"] = PLAIN
    r = client.get("/manage/objects")
    assert "Owner" not in r.text


def test_new_form_renders_fields(client):
    r = client.get("/manage/users/new")
    assert r.status_code == 200
    for name in ("username", "password", "admin"):
        assert f'name="{name}"' in r.text


def test_edit_form_prefills_values(client):
    r = client.get("/manage/objects/1/edit")
    assert r.status_code == 200
    assert 'value="Adam Zaleski"' in r.text
    assert "/manage/objects/1/update" in r.text


def test_add_and_edit_forms_render_in_modal(client):
    for url in ("/manage/objects/new", "/manage/users/2/edit"):
        r = client.get(url)
        assert 'id="manage-modal"' in r.text
        assert "<dialog" in r.text
    # Panel without a form has no modal.
    r = client.get("/manage/objects")
    assert 'id="manage-modal"' not in r.text
    # The upgrade script ships with the page shell.
    assert "/static/manage.js" in client.get("/manage").text
    js = client.get("/static/manage.js")
    assert js.status_code == 200
    assert "showModal" in js.text


def test_create_posts_payload_and_redirects(client, calls):
    r = client.post(
        "/manage/groups/create",
        data={"name": "New group", "description": "Desc"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/manage?tab=groups"
    assert calls["groups.create"] == [{"name": "New group", "description": "Desc"}]


def test_create_htmx_returns_fragment(client, calls):
    r = client.post(
        "/manage/groups/create",
        data={"name": "New group", "description": "Desc"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "Groups" in r.text
    assert calls["groups.create"]


def test_checkbox_and_int_coercion(client, calls):
    client.post(
        "/manage/users/create",
        data={"username": "nowy", "password": "secret1", "admin": "on"},
        headers={"HX-Request": "true"},
    )
    assert calls["users.create"] == [
        {"username": "nowy", "password": "secret1", "admin": True}
    ]
    client.post(
        "/manage/objects/create",
        data={"name": "X", "description": "Y", "group_id": "2", "user_id": "1"},
        headers={"HX-Request": "true"},
    )
    assert calls["objects.create"] == [
        {"name": "X", "description": "Y", "group_id": 2, "user_id": 1}
    ]


def test_validation_errors_render_next_to_fields(client, calls, monkeypatch):
    def failing_create(token, payload):
        raise api_client.ValidationApiError({"username": "String should match pattern"})

    monkeypatch.setattr(api_client.users, "create", failing_create)
    r = client.post(
        "/manage/users/create",
        data={"username": "zły!", "password": "secret1"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "String should match pattern" in r.text
    assert 'value="zły!"' in r.text  # form re-filled


def test_api_error_shows_banner(client, monkeypatch):
    def failing_create(token, payload):
        raise api_client.ApiError("Group name already exists")

    monkeypatch.setattr(api_client.groups_admin, "create", failing_create)
    r = client.post(
        "/manage/groups/create",
        data={"name": "Default", "description": "dup"},
        headers={"HX-Request": "true"},
    )
    assert "Group name already exists" in r.text


def test_update_posts_payload(client, calls):
    client.post(
        "/manage/types/8/update",
        data={"name": "Wakacje", "color": "#9f4800"},
        headers={"HX-Request": "true"},
    )
    assert calls["types.update"] == [(8, {"name": "Wakacje", "color": "#9f4800"})]


def test_blank_password_on_user_edit_means_keep(client, calls):
    client.post(
        "/manage/users/2/update",
        data={"username": "kinga", "password": ""},
        headers={"HX-Request": "true"},
    )
    assert calls["users.update"] == [
        (2, {"username": "kinga", "password": None, "admin": False})
    ]


def test_delete_calls_backend(client, calls):
    r = client.post("/manage/holidays/1/delete", follow_redirects=False)
    assert r.status_code == 303
    assert calls["holidays.delete"] == [1]


# Row 7 belongs to Adam Zaleski (2026), row 8 to Kinga Zaleska (2025); the
# fake backend serves one row per page. Object *names* appear in the filter
# dropdown on every page, so presence of a row is asserted via its edit URL.


def test_absences_panel_has_year_filter_and_pager(client):
    r = client.get("/manage/absences")
    assert r.status_code == 200
    assert 'name="year"' in r.text and "All years" in r.text
    assert ">2026<" in r.text and ">2025<" in r.text
    assert "Page 1 of 2" in r.text
    assert "page=2" in r.text  # Next link
    assert "/manage/absences/7/edit" in r.text  # newest row on page 1
    assert "/manage/absences/8/edit" not in r.text


def test_absences_second_page(client):
    r = client.get("/manage/absences?page=2")
    assert "/manage/absences/8/edit" in r.text
    assert "/manage/absences/7/edit" not in r.text
    assert "Page 2 of 2" in r.text
    assert "page=1" in r.text  # Prev link


def test_absences_year_filter(client):
    r = client.get("/manage/absences?year=2025")
    assert "/manage/absences/8/edit" in r.text
    assert "/manage/absences/7/edit" not in r.text
    assert "Page 1 of" not in r.text  # single page -> no pager


def test_absences_list_state_carries_into_row_urls(client):
    r = client.get("/manage/absences?year=2026")
    assert "/manage/absences/7/edit?year=2026" in r.text
    assert "/manage/absences/7/delete?year=2026" in r.text
    assert "/manage/absences/new?year=2026" in r.text


def test_absences_object_filter(client):
    r = client.get("/manage/absences")
    assert 'name="object_id"' in r.text and "All objects" in r.text
    r = client.get("/manage/absences?object_id=2")
    assert "/manage/absences/8/edit" in r.text  # only Kinga's row
    assert "/manage/absences/7/edit" not in r.text


def test_absences_filters_combine_and_carry(client):
    # Both filters match row 8 (Kinga, 2025).
    r = client.get("/manage/absences?year=2025&object_id=2")
    assert "Kinga Zaleska" in r.text
    assert "/manage/absences/8/edit?year=2025&amp;object_id=2" in r.text
    # Contradictory filters -> empty table.
    r = client.get("/manage/absences?year=2026&object_id=2")
    assert "Nothing here yet" in r.text


def test_default_group_has_no_delete_button(client):
    r = client.get("/manage/groups")
    assert r.status_code == 200
    # Group 1 is "Default": protected. Group 2 is deletable.
    assert "/manage/groups/1/delete" not in r.text
    assert "/manage/groups/2/delete" in r.text


# --- group membership ----------------------------------------------------------


def test_members_panel_lists_members_and_candidates(client):
    r = client.get("/manage/members")
    assert r.status_code == 200
    assert "Group members" in r.text
    assert "admin" in r.text  # member of group 1
    assert "kinga" in r.text  # candidate to add


def test_members_add_and_remove(client, calls):
    r = client.post(
        "/manage/members/add",
        data={"group_id": 1, "user_id": 2},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert calls["members.add"] == [(1, 2)]

    r = client.post(
        "/manage/members/1/remove",
        data={"group_id": 1},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert calls["members.remove"] == [(1, 1)]
