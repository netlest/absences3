"""The /manage page: CRUD UI for every entity, driven by manage_entities.py.

Interaction model (htmx): the whole tab area (#manage-area) is one server
fragment. Tab clicks, Add/Edit buttons and form submits all re-render that
fragment, so success, field errors and refreshed tables are one code path.
Requests without the HX-Request header get the same content wrapped in the
full page, so everything still works with JavaScript disabled.

Authorization is enforced by the backend (admin-only endpoints return 403);
this layer only hides tabs the user may not use.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import api_client
from manage_entities import ENTITIES, TABS, Entity

router = APIRouter()

SESSION_COOKIE = "session"


class _NeedsLogin(Exception):
    pass


def _templates():
    # Imported lazily to avoid a circular import (app.py includes this router).
    from app import templates

    return templates


def _token(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _NeedsLogin()
    return token


def _login_response(request: Request) -> Response:
    """Full pages redirect to /login; htmx gets an HX-Redirect header."""
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": "/login"})
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# --- data loading per entity ---------------------------------------------------


def _options(rows: list[dict], label_key: str) -> list[dict]:
    return [{"value": r["id"], "label": r[label_key]} for r in rows]


def _list_query(request: Request) -> dict:
    """Panel list state (filters, page) carried in the query string."""
    out = {}
    for k in ("year", "object_id", "page"):
        v = request.query_params.get(k)
        if v and v.isdigit():
            out[k] = int(v)
    return out


def _load(
    key: str, token: str, me: dict, query: dict | None = None
) -> tuple[list[dict], dict, dict | None]:
    """Rows for the table, select options for the form, and — for paginated
    entities — list meta (page/pages/total/years + `qs`, the query string
    every panel URL carries so filter and page survive add/edit/delete)."""
    query = query or {}
    if key == "objects":
        rows = api_client.objects.list(token)
        options = {"groups": _options(api_client.get_groups(token), "name")}
        if me.get("admin"):
            options["users"] = _options(api_client.users.list(token), "username")
        return rows, options, None
    if key == "absences":
        data = api_client.get_manage_absences(
            token,
            year=query.get("year"),
            object_id=query.get("object_id"),
            page=query.get("page"),
        )
        # Active filters (without page): reused by the pager links.
        filters = {
            k: query[k] for k in ("year", "object_id") if query.get(k)
        }
        params = dict(filters)
        if data["page"] > 1:
            params["page"] = data["page"]
        meta = {
            "total": data["total"],
            "page": data["page"],
            "pages": data["pages"],
            "years": data["years"],
            "year": query.get("year"),
            "object_id": query.get("object_id"),
            "fq": urlencode(filters),
            "qs": f"?{urlencode(params)}" if params else "",
        }
        options = {
            "objects": _options(api_client.get_editable_objects(token), "name"),
            "types": _options(api_client.get_absence_types(token), "name"),
        }
        return data["rows"], options, meta
    if key == "types":
        return api_client.absence_types.list(token), {}, None
    if key == "groups":
        rows = api_client.get_groups(token)
        for r in rows:
            # The backend refuses to delete the Default group; hide the button.
            r["_protected"] = r["name"].strip().lower() == "default"
        return rows, {}, None
    if key == "users":
        return api_client.users.list(token), {}, None
    if key == "holidays":
        return api_client.get_holidays_all(token), {}, None
    raise HTTPException(status_code=404, detail="Unknown section")


# Entity key -> api_client attribute holding its Resource. Resolved at call
# time so tests can stub api_client wholesale.
RESOURCE_ATTRS: dict[str, str] = {
    "objects": "objects",
    "absences": "absences",
    "types": "absence_types",
    "groups": "groups_admin",
    "users": "users",
    "holidays": "holidays",
}


def _resource(key: str) -> api_client.Resource:
    return getattr(api_client, RESOURCE_ATTRS[key])


def _entity_or_404(key: str, me: dict) -> Entity:
    entity = ENTITIES.get(key)
    if entity is None:
        raise HTTPException(status_code=404, detail="Unknown section")
    if entity.admin_only and not me.get("admin"):
        raise HTTPException(status_code=403, detail="Administrators only")
    return entity


def _payload(entity: Entity, form, me: dict, editing: bool) -> dict:
    """Form data -> JSON payload; the backend's Pydantic model has the
    final say, so unparseable values are passed through to become 422s."""
    data: dict = {}
    for f in entity.fields:
        if f.admin_only and not me.get("admin"):
            continue
        raw = (form.get(f.name) or "").strip()
        if f.widget == "checkbox":
            data[f.name] = form.get(f.name) is not None
        elif raw == "":
            data[f.name] = None if (not f.required or f.optional_on_edit) else ""
        elif f.coerce == "int":
            try:
                data[f.name] = int(raw)
            except ValueError:
                data[f.name] = raw
        else:
            data[f.name] = raw
    return data


# --- rendering ------------------------------------------------------------------


def _render_area(
    request: Request,
    token: str,
    me: dict,
    key: str,
    *,
    form_mode: str | None = None,  # None | "new" | "edit"
    item_id: int | None = None,
    values: dict | None = None,
    errors: dict | None = None,
    form_error: str | None = None,
    group_id: int | None = None,
    query: dict | None = None,
) -> Response:
    tabs = [
        {"key": k, "label": label}
        for k, label, admin_only in TABS
        if me.get("admin") or not admin_only
    ]
    if key not in {t["key"] for t in tabs}:
        raise HTTPException(status_code=403, detail="Administrators only")

    context: dict = {
        "tabs": tabs,
        "active": key,
        "me": me,
        "username": me["username"],
        "entity": None,
        "form_mode": form_mode,
        "item_id": item_id,
        "values": values or {},
        "errors": errors or {},
        "form_error": form_error,
        "meta": None,
    }

    if key == "members":
        groups = api_client.get_groups(token)
        selected = group_id if group_id in {g["id"] for g in groups} else (
            groups[0]["id"] if groups else None
        )
        members = (
            api_client.get_group_members(token, selected)
            if selected is not None
            else []
        )
        member_ids = {m["id"] for m in members}
        context.update(
            m_groups=groups,
            m_selected=selected,
            m_members=members,
            m_candidates=[
                u for u in api_client.users.list(token) if u["id"] not in member_ids
            ],
        )
    else:
        entity = _entity_or_404(key, me)
        rows, options, meta = _load(key, token, me, query)
        context.update(entity=entity, rows=rows, options=options, meta=meta)
        if form_mode == "edit" and not values:
            row = next((r for r in rows if r["id"] == item_id), None)
            if row is None and key == "absences":
                # Paginated: the row may not be on the current page.
                try:
                    row = api_client.get_absence(token, item_id)
                except api_client.ApiError:
                    row = None
            if row is None:
                raise HTTPException(status_code=404, detail="Not found")
            context["values"] = row

    template = (
        "partials/manage_area.html"
        if request.headers.get("HX-Request")
        else "manage.html"
    )
    return _templates().TemplateResponse(request, template, context)


def _guarded(request: Request, fn) -> Response:
    """Shared error handling for every manage route."""
    try:
        return fn(_token(request))
    except (_NeedsLogin, api_client.Unauthorized):
        return _login_response(request)
    except api_client.BackendUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Backend unavailable: {exc}")


def _me(token: str) -> dict:
    return api_client.get_me(token)


# --- group membership (dedicated panel) ----------------------------------------


@router.get("/manage/members")
def members_panel(request: Request, group_id: int | None = None):
    return _guarded(
        request,
        lambda token: _render_area(
            request, token, _me(token), "members", group_id=group_id
        ),
    )


@router.post("/manage/members/add")
async def members_add(request: Request):
    form = await (request.form())

    def run(token: str) -> Response:
        me = _me(token)
        group_id = int(form.get("group_id") or 0)
        form_error = None
        try:
            api_client.add_group_member(token, group_id, int(form.get("user_id") or 0))
        except api_client.ApiError as exc:
            form_error = str(exc)
        except ValueError:
            form_error = "Pick a user to add"
        if not request.headers.get("HX-Request") and not form_error:
            return RedirectResponse("/manage?tab=members", status_code=303)
        return _render_area(
            request, token, me, "members", group_id=group_id, form_error=form_error
        )

    return _guarded(request, run)


@router.post("/manage/members/{user_id}/remove")
async def members_remove(request: Request, user_id: int):
    form = await (request.form())

    def run(token: str) -> Response:
        me = _me(token)
        group_id = int(form.get("group_id") or 0)
        form_error = None
        try:
            api_client.remove_group_member(token, group_id, user_id)
        except api_client.ApiError as exc:
            form_error = str(exc)
        if not request.headers.get("HX-Request") and not form_error:
            return RedirectResponse("/manage?tab=members", status_code=303)
        return _render_area(
            request, token, me, "members", group_id=group_id, form_error=form_error
        )

    return _guarded(request, run)


# --- generic entity panels -------------------------------------------------------


@router.get("/manage")
def manage_page(request: Request, tab: str = "objects"):
    return _guarded(
        request,
        lambda token: _render_area(
            request, token, _me(token), tab, query=_list_query(request)
        ),
    )


@router.get("/manage/{key}")
def panel(request: Request, key: str):
    return _guarded(
        request,
        lambda token: _render_area(
            request, token, _me(token), key, query=_list_query(request)
        ),
    )


@router.get("/manage/{key}/new")
def form_new(request: Request, key: str):
    return _guarded(
        request,
        lambda token: _render_area(
            request, token, _me(token), key, form_mode="new",
            query=_list_query(request),
        ),
    )


@router.get("/manage/{key}/{item_id}/edit")
def form_edit(request: Request, key: str, item_id: int):
    return _guarded(
        request,
        lambda token: _render_area(
            request, token, _me(token), key, form_mode="edit", item_id=item_id,
            query=_list_query(request),
        ),
    )


def _save(request: Request, key: str, form, token: str, item_id: int | None):
    """Create (item_id None) or update; re-renders the form on errors."""
    me = _me(token)
    entity = _entity_or_404(key, me)
    editing = item_id is not None
    payload = _payload(entity, form, me, editing)
    if editing and key == "users" and payload.get("password") == "":
        payload["password"] = None  # blank on edit = keep current password
    errors: dict = {}
    form_error: str | None = None
    try:
        if editing:
            _resource(key).update(token, item_id, payload)
        else:
            _resource(key).create(token, payload)
    except api_client.ValidationApiError as exc:
        errors = exc.errors
    except api_client.ApiError as exc:
        form_error = str(exc)

    query = _list_query(request)
    if errors or form_error:
        return _render_area(
            request, token, me, key,
            form_mode="edit" if editing else "new",
            item_id=item_id, values=dict(form), errors=errors,
            form_error=form_error, query=query,
        )
    if not request.headers.get("HX-Request"):
        qs = f"&{urlencode(query)}" if query else ""
        return RedirectResponse(f"/manage?tab={key}{qs}", status_code=303)
    return _render_area(request, token, me, key, query=query)


@router.post("/manage/{key}/create")
async def create(request: Request, key: str):
    form = await request.form()
    return _guarded(request, lambda token: _save(request, key, form, token, None))


@router.post("/manage/{key}/{item_id}/update")
async def update(request: Request, key: str, item_id: int):
    form = await request.form()
    return _guarded(request, lambda token: _save(request, key, form, token, item_id))


@router.post("/manage/{key}/{item_id}/delete")
def delete(request: Request, key: str, item_id: int):
    def run(token: str) -> Response:
        me = _me(token)
        _entity_or_404(key, me)
        form_error = None
        try:
            _resource(key).delete(token, item_id)
        except api_client.ApiError as exc:
            form_error = str(exc)
        query = _list_query(request)
        if not request.headers.get("HX-Request") and not form_error:
            qs = f"&{urlencode(query)}" if query else ""
            return RedirectResponse(f"/manage?tab={key}{qs}", status_code=303)
        return _render_area(
            request, token, me, key, form_error=form_error, query=query
        )

    return _guarded(request, run)
