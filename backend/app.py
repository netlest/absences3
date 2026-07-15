"""Absences backend API.

Read-only data endpoints over the PostgreSQL schema (see sql_ddl/), plus a
session-based authentication layer:

- POST /auth/login verifies the password against users.password (scrypt
  hashes in Werkzeug's format, checked with the stdlib — see security.py)
  and stores an opaque bearer token in the pre-existing `sessions` table
  (session_id, JSON payload in `data`, `expiry`).
- Every data endpoint requires `Authorization: Bearer <token>` and is scoped
  to the groups the session's user belongs to (admins see all groups).

Absences are served from the v_absences view, which pre-splits every absence
into one row per calendar month — exactly what the calendar grid needs.
"""

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import sqlalchemy
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from config import settings
from security import hash_password, verify_password
from db import get_db
from models import (
    Absence,
    AbsenceType,
    Group,
    Holiday,
    Object,
    User,
    UserSession,
    VAbsence,
    user_groups,
)

app = FastAPI(title="Absences backend")


# --- authentication ---------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


def _utcnow() -> datetime:
    """Naive UTC now, matching the TIMESTAMP (without tz) expiry column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_or_401(
    authorization: str | None = Header(None), db: Session = Depends(get_db)
) -> UserSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    sess = db.scalar(select(UserSession).where(UserSession.session_id == token))
    if sess is None or sess.expiry is None or sess.expiry < _utcnow():
        if sess is not None:
            db.delete(sess)
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return sess


def current_user(sess: UserSession = Depends(_session_or_401)) -> dict:
    return json.loads(sess.data)


def _allowed_group_ids(db: Session, user: dict) -> set[int]:
    """Groups the user may see: their memberships, or all groups for admins."""
    if user.get("admin"):
        return set(db.scalars(select(Group.id)))
    return set(
        db.scalars(
            select(user_groups.c.group_id).where(
                user_groups.c.user_id == user["user_id"]
            )
        )
    )


@app.post("/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(user.password, body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Opportunistic cleanup of expired sessions.
    db.execute(delete(UserSession).where(UserSession.expiry < _utcnow()))

    token = secrets.token_urlsafe(32)
    payload = {"user_id": user.id, "username": user.username, "admin": user.admin}
    db.add(
        UserSession(
            session_id=token,
            data=json.dumps(payload).encode(),
            expiry=_utcnow() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    db.commit()
    return {"token": token, "user": payload}


@app.post("/auth/logout")
def logout(
    sess: UserSession = Depends(_session_or_401), db: Session = Depends(get_db)
) -> dict:
    db.delete(sess)
    db.commit()
    return {"status": "logged out"}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/password")
def change_password(
    body: PasswordChange,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(User, user["user_id"])
    if row is None or not verify_password(row.password, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=400, detail="New password must be at least 6 characters"
        )
    row.password = hash_password(body.new_password)
    row.updated_at = _utcnow()
    db.commit()
    return {"status": "password changed"}


# --- service health ----------------------------------------------------------


@app.get("/")
def root() -> dict:
    return {
        "service": "absences-backend",
        "status": "ok",
        "sqlalchemy": sqlalchemy.__version__,
    }


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    return {
        "database": "ok",
        "users": db.scalar(select(func.count()).select_from(User)),
        "objects": db.scalar(select(func.count()).select_from(Object)),
    }


# --- data endpoints (session required, group-scoped) -------------------------


@app.get("/groups")
def list_groups(
    user: dict = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """Groups visible to the authenticated user."""
    allowed = _allowed_group_ids(db, user)
    q = select(Group).where(Group.id.in_(allowed)).order_by(Group.id)
    return [
        {"id": g.id, "name": g.name, "description": g.description}
        for g in db.scalars(q)
    ]


@app.get("/groups/{group_id}/objects")
def group_objects(
    group_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Calendar row labels for a group, in stable id order."""
    if group_id not in _allowed_group_ids(db, user):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    if db.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    q = select(Object).where(Object.group_id == group_id).order_by(Object.id)
    return [{"id": o.id, "name": o.name} for o in db.scalars(q)]


@app.get("/absences")
def list_absences(
    date_from: date = Query(...),
    date_to: date = Query(...),
    group_id: int | None = None,
    user_id: int | None = None,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Month-split absence periods overlapping [date_from, date_to].

    Restricted to the authenticated user's groups. Optional filters:
    group_id (must be one of the user's groups), user_id (the object's
    owner). Each returned row lies within a single calendar month.
    """
    allowed = _allowed_group_ids(db, user)
    if group_id is not None:
        if group_id not in allowed:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        group_filter = VAbsence.group_id == group_id
    else:
        group_filter = VAbsence.group_id.in_(allowed)

    q = (
        select(VAbsence, Object.name.label("object_name"))
        .join(Object, VAbsence.object_id == Object.id)
        .where(
            group_filter,
            VAbsence.abs_date_start <= date_to,
            VAbsence.abs_date_end >= date_from,
        )
        .order_by(VAbsence.abs_date_start, VAbsence.object_id)
    )
    if user_id is not None:
        q = q.where(VAbsence.user_id == user_id)
    return [
        {
            "id": v.id,
            "object_id": v.object_id,
            "object_name": object_name,
            "group_id": v.group_id,
            "user_id": v.user_id,
            "type_id": v.type_id,
            "abs_date_start": v.abs_date_start,
            "abs_date_end": v.abs_date_end,
            "duration": v.duration,
            "description": v.description,
            "color": v.at_color,
            "type_name": v.at_name,
            "editable": _may_edit(user, v.user_id),
        }
        for v, object_name in db.execute(q)
    ]


# --- absence management (owner or admin) --------------------------------------


class AbsenceIn(BaseModel):
    object_id: int
    type_id: int
    abs_date_start: date
    abs_date_end: date
    description: str | None = None


def _may_edit(user: dict, owner_user_id: int | None) -> bool:
    """Admins manage everything; others only absences of objects they own."""
    return bool(user.get("admin")) or owner_user_id == user["user_id"]


def _absence_or_404(db: Session, absence_id: int) -> Absence:
    a = db.get(Absence, absence_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Absence not found")
    return a


def _check_absence_input(db: Session, user: dict, body: AbsenceIn) -> None:
    obj = db.get(Object, body.object_id)
    if obj is None:
        raise HTTPException(status_code=400, detail="Unknown object_id")
    if not _may_edit(user, obj.user_id):
        raise HTTPException(
            status_code=403, detail="You may only manage absences of your own objects"
        )
    if db.get(AbsenceType, body.type_id) is None:
        raise HTTPException(status_code=400, detail="Unknown type_id")
    if body.abs_date_end < body.abs_date_start:
        raise HTTPException(status_code=400, detail="End date is before start date")


@app.post("/absences", status_code=201)
def create_absence(
    body: AbsenceIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    _check_absence_input(db, user, body)
    a = Absence(**body.model_dump())
    db.add(a)
    db.commit()
    return {"id": a.id}


@app.get("/absences/{absence_id}")
def get_absence(
    absence_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """One raw (un-split) absence, for the edit form."""
    a = _absence_or_404(db, absence_id)
    obj = db.get(Object, a.object_id)
    if obj is None or obj.group_id not in _allowed_group_ids(db, user):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    return {
        "id": a.id,
        "object_id": a.object_id,
        "object_name": obj.name,
        "type_id": a.type_id,
        "abs_date_start": a.abs_date_start,
        "abs_date_end": a.abs_date_end,
        "description": a.description,
        "editable": _may_edit(user, obj.user_id),
    }


@app.put("/absences/{absence_id}")
def update_absence(
    absence_id: int,
    body: AbsenceIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    a = _absence_or_404(db, absence_id)
    current_obj = db.get(Object, a.object_id)
    if current_obj is not None and not _may_edit(user, current_obj.user_id):
        raise HTTPException(
            status_code=403, detail="You may only manage absences of your own objects"
        )
    _check_absence_input(db, user, body)  # also authorizes the (new) object
    a.object_id = body.object_id
    a.type_id = body.type_id
    a.abs_date_start = body.abs_date_start
    a.abs_date_end = body.abs_date_end
    a.description = body.description
    db.commit()
    return {"id": a.id}


@app.delete("/absences/{absence_id}")
def delete_absence(
    absence_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    a = _absence_or_404(db, absence_id)
    obj = db.get(Object, a.object_id)
    if obj is not None and not _may_edit(user, obj.user_id):
        raise HTTPException(
            status_code=403, detail="You may only manage absences of your own objects"
        )
    db.delete(a)
    db.commit()
    return {"status": "deleted"}


@app.get("/objects")
def editable_objects(
    user: dict = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """Objects the user may manage (all of them for admins), display-ready."""
    q = (
        select(Object, Group.name, User.username)
        .outerjoin(Group, Object.group_id == Group.id)
        .outerjoin(User, Object.user_id == User.id)
        .order_by(Object.id)
    )
    if not user.get("admin"):
        q = q.where(Object.user_id == user["user_id"])
    return [
        {
            "id": o.id,
            "name": o.name,
            "description": o.description,
            "group_id": o.group_id,
            "group_name": group_name,
            "user_id": o.user_id,
            "owner_name": owner_name,
        }
        for o, group_name, owner_name in db.execute(q)
    ]


@app.get("/absence_types")
def list_absence_types(
    user: dict = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """All defined absence types with their display colors."""
    q = select(AbsenceType).order_by(AbsenceType.id)
    return [
        {"id": t.id, "name": t.name, "color": t.color} for t in db.scalars(q)
    ]


@app.get("/holidays")
def list_holidays(
    date_from: date = Query(...),
    date_to: date = Query(...),
    country: str = "pl",
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Holidays within [date_from, date_to].

    Rows flagged `recurring` repeat every year on the same month/day; their
    stored year is ignored and they are expanded into each year of the range.
    """
    rows = db.scalars(
        select(Holiday).where(func.lower(Holiday.country) == country.lower())
    ).all()
    out: list[dict] = []
    for h in rows:
        if h.recurring:
            for y in range(date_from.year, date_to.year + 1):
                try:
                    d = h.event_date.replace(year=y)
                except ValueError:  # Feb 29 in a non-leap year
                    continue
                if date_from <= d <= date_to:
                    out.append({"date": d, "description": h.description})
        elif date_from <= h.event_date <= date_to:
            out.append({"date": h.event_date, "description": h.description})
    out.sort(key=lambda x: x["date"])
    return out


# --- management (see /manage in the frontend) ---------------------------------
#
# Admin-only: users, groups, group membership, absence types, holidays.
# Owner-or-admin: objects. All write bodies are Pydantic-validated so the
# frontend can surface 422 field errors next to the offending input.


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not user.get("admin"):
        raise HTTPException(
            status_code=403, detail="Administrator privileges required"
        )
    return user


Str30 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)
]
Str50 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
Str255 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=30,
        pattern=r"^[A-Za-z0-9_. -]+$",
    ),
]
# Hex color (#abc or #aabbcc) or a plain CSS color name.
Color = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|[A-Za-z]{1,30})$",
    ),
]


def _ensure_unique(db, model, column, value, label, exclude_id=None) -> None:
    q = select(model.id).where(func.lower(column) == value.lower())
    if exclude_id is not None:
        q = q.where(model.id != exclude_id)
    if db.scalar(q) is not None:
        raise HTTPException(status_code=400, detail=f"{label} already exists")


def _purge_user_sessions(db: Session, user_id: int) -> None:
    """Kill live sessions of a deleted or demoted user."""
    for s in db.scalars(select(UserSession)):
        try:
            if json.loads(s.data or b"{}").get("user_id") == user_id:
                db.delete(s)
        except (ValueError, UnicodeDecodeError):
            pass


# --- users (admin) ---


class UserCreate(BaseModel):
    username: Username
    password: str = Field(min_length=6, max_length=128)
    admin: bool = False


class UserUpdate(BaseModel):
    username: Username
    password: str | None = Field(default=None, min_length=6, max_length=128)
    admin: bool = False


@app.get("/users")
def list_users(
    _: dict = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        {"id": u.id, "username": u.username, "admin": u.admin}
        for u in db.scalars(select(User).order_by(User.id))
    ]


@app.post("/users", status_code=201)
def create_user(
    body: UserCreate,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_unique(db, User, User.username, body.username, "Username")
    u = User(
        username=body.username,
        password=hash_password(body.password),
        admin=body.admin,
    )
    db.add(u)
    db.commit()
    return {"id": u.id}


def _user_or_404(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return u


@app.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    u = _user_or_404(db, user_id)
    _ensure_unique(db, User, User.username, body.username, "Username", user_id)
    if u.id == admin["user_id"] and not body.admin:
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own administrator rights",
        )
    u.username = body.username
    if body.password:
        u.password = hash_password(body.password)
    demoted = u.admin and not body.admin
    u.admin = body.admin
    u.updated_at = _utcnow()
    if demoted or body.password:
        _purge_user_sessions(db, u.id)
    db.commit()
    return {"id": u.id}


@app.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    u = _user_or_404(db, user_id)
    if u.id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    _purge_user_sessions(db, u.id)
    # Groups have a plain (non-cascading) owner FK: detach before deleting.
    db.execute(update(Group).where(Group.user_id == u.id).values(user_id=None))
    # Core delete so PostgreSQL's ON DELETE CASCADE removes their objects
    # and absences (an ORM delete would null the FKs instead).
    db.execute(delete(User).where(User.id == u.id))
    db.commit()
    return {"status": "deleted"}


# --- groups (admin) ---


class GroupIn(BaseModel):
    name: Str255
    description: Str255


def _group_or_404(db: Session, group_id: int) -> Group:
    g = db.get(Group, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


# The Default group is the app's fallback (new users, first calendar view)
# and must always exist: it cannot be deleted or renamed.
PROTECTED_GROUP = "default"


def _is_protected_group(g: Group) -> bool:
    return g.name.strip().lower() == PROTECTED_GROUP


@app.post("/groups", status_code=201)
def create_group(
    body: GroupIn,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_unique(db, Group, Group.name, body.name, "Group name")
    g = Group(name=body.name, description=body.description, user_id=admin["user_id"])
    db.add(g)
    db.commit()
    return {"id": g.id}


@app.put("/groups/{group_id}")
def update_group(
    group_id: int,
    body: GroupIn,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    g = _group_or_404(db, group_id)
    if _is_protected_group(g) and body.name.strip().lower() != PROTECTED_GROUP:
        raise HTTPException(
            status_code=400, detail="The Default group cannot be renamed"
        )
    _ensure_unique(db, Group, Group.name, body.name, "Group name", group_id)
    g.name = body.name
    g.description = body.description
    db.commit()
    return {"id": g.id}


@app.delete("/groups/{group_id}")
def delete_group(
    group_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    g = _group_or_404(db, group_id)
    if _is_protected_group(g):
        raise HTTPException(
            status_code=400, detail="The Default group cannot be deleted"
        )
    db.execute(delete(Group).where(Group.id == group_id))
    db.commit()
    return {"status": "deleted"}


# --- group membership (admin) ---


class MemberIn(BaseModel):
    user_id: int


@app.get("/groups/{group_id}/members")
def group_members(
    group_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    _group_or_404(db, group_id)
    q = (
        select(User)
        .join(user_groups, user_groups.c.user_id == User.id)
        .where(user_groups.c.group_id == group_id)
        .order_by(User.username)
    )
    return [{"id": u.id, "username": u.username} for u in db.scalars(q)]


@app.post("/groups/{group_id}/members", status_code=201)
def add_group_member(
    group_id: int,
    body: MemberIn,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    _group_or_404(db, group_id)
    _user_or_404(db, body.user_id)
    exists = db.scalar(
        select(user_groups.c.user_id).where(
            user_groups.c.user_id == body.user_id,
            user_groups.c.group_id == group_id,
        )
    )
    if exists is not None:
        raise HTTPException(status_code=400, detail="Already a member")
    db.execute(insert(user_groups).values(user_id=body.user_id, group_id=group_id))
    db.commit()
    return {"status": "added"}


@app.delete("/groups/{group_id}/members/{user_id}")
def remove_group_member(
    group_id: int,
    user_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    r = db.execute(
        delete(user_groups).where(
            user_groups.c.user_id == user_id,
            user_groups.c.group_id == group_id,
        )
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="Not a member")
    db.commit()
    return {"status": "removed"}


# --- objects (owner or admin) ---


class ObjectIn(BaseModel):
    name: Str30
    description: Str255
    group_id: int
    user_id: int | None = None  # owner; admins only, others are forced to self


def _object_payload(db: Session, user: dict, body: ObjectIn) -> tuple[int, int]:
    """Validate and return (group_id, owner_id) for a create/update."""
    _group_or_404(db, body.group_id)
    if user.get("admin"):
        owner_id = body.user_id or user["user_id"]
        _user_or_404(db, owner_id)
    else:
        member = db.scalar(
            select(user_groups.c.group_id).where(
                user_groups.c.user_id == user["user_id"],
                user_groups.c.group_id == body.group_id,
            )
        )
        if member is None:
            raise HTTPException(
                status_code=403, detail="You are not a member of this group"
            )
        owner_id = user["user_id"]
    return body.group_id, owner_id


@app.post("/objects", status_code=201)
def create_object(
    body: ObjectIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    group_id, owner_id = _object_payload(db, user, body)
    _ensure_unique(db, Object, Object.name, body.name, "Object name")
    o = Object(
        name=body.name,
        description=body.description,
        group_id=group_id,
        user_id=owner_id,
    )
    db.add(o)
    db.commit()
    return {"id": o.id}


def _own_object_or_403(db: Session, user: dict, object_id: int) -> Object:
    o = db.get(Object, object_id)
    if o is None:
        raise HTTPException(status_code=404, detail="Object not found")
    if not _may_edit(user, o.user_id):
        raise HTTPException(
            status_code=403, detail="You may only manage your own objects"
        )
    return o


@app.put("/objects/{object_id}")
def update_object(
    object_id: int,
    body: ObjectIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    o = _own_object_or_403(db, user, object_id)
    group_id, owner_id = _object_payload(db, user, body)
    _ensure_unique(db, Object, Object.name, body.name, "Object name", object_id)
    o.name = body.name
    o.description = body.description
    o.group_id = group_id
    o.user_id = owner_id
    db.commit()
    return {"id": o.id}


@app.delete("/objects/{object_id}")
def delete_object(
    object_id: int,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    o = _own_object_or_403(db, user, object_id)
    db.execute(delete(Object).where(Object.id == o.id))
    db.commit()
    return {"status": "deleted"}


# --- absence types (admin) ---


class AbsenceTypeIn(BaseModel):
    name: Str50
    color: Color | None = None


@app.post("/absence_types", status_code=201)
def create_absence_type(
    body: AbsenceTypeIn,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    t = AbsenceType(name=body.name, color=body.color)
    db.add(t)
    db.commit()
    return {"id": t.id}


def _type_or_404(db: Session, type_id: int) -> AbsenceType:
    t = db.get(AbsenceType, type_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Absence type not found")
    return t


@app.put("/absence_types/{type_id}")
def update_absence_type(
    type_id: int,
    body: AbsenceTypeIn,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    t = _type_or_404(db, type_id)
    t.name = body.name
    t.color = body.color
    db.commit()
    return {"id": t.id}


@app.delete("/absence_types/{type_id}")
def delete_absence_type(
    type_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    _type_or_404(db, type_id)
    db.execute(delete(AbsenceType).where(AbsenceType.id == type_id))
    db.commit()
    return {"status": "deleted"}


# --- holidays (admin) ---


class HolidayIn(BaseModel):
    country: Annotated[
        str,
        StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[A-Za-z]{2,4}$"),
    ]
    event_date: date
    description: str | None = Field(default=None, max_length=150)
    recurring: bool = False


@app.get("/holidays/all")
def list_holidays_raw(
    _: dict = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict]:
    """Raw holiday rows (no recurring expansion), for the manage table."""
    q = select(Holiday).order_by(Holiday.event_date.desc(), Holiday.id.desc())
    return [
        {
            "id": h.id,
            "country": h.country,
            "event_date": h.event_date,
            "description": h.description,
            "recurring": bool(h.recurring),
        }
        for h in db.scalars(q)
    ]


@app.post("/holidays", status_code=201)
def create_holiday(
    body: HolidayIn,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    h = Holiday(**body.model_dump())
    db.add(h)
    db.commit()
    return {"id": h.id}


def _holiday_or_404(db: Session, holiday_id: int) -> Holiday:
    h = db.get(Holiday, holiday_id)
    if h is None:
        raise HTTPException(status_code=404, detail="Holiday not found")
    return h


@app.put("/holidays/{holiday_id}")
def update_holiday(
    holiday_id: int,
    body: HolidayIn,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    h = _holiday_or_404(db, holiday_id)
    for k, v in body.model_dump().items():
        setattr(h, k, v)
    db.commit()
    return {"id": h.id}


@app.delete("/holidays/{holiday_id}")
def delete_holiday(
    holiday_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    h = _holiday_or_404(db, holiday_id)
    db.delete(h)
    db.commit()
    return {"status": "deleted"}


# --- raw absences for the manage table (owner or admin) ---


@app.get("/manage/absences")
def manage_absences(
    year: int | None = Query(None, ge=1900, le=2200),
    object_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Un-split absences on objects the user may manage, newest first.

    Paginated; `year` filters on the start date, `object_id` on the object.
    `years` lists every year that has data (unfiltered), for the dropdown.
    """
    scope = []
    if not user.get("admin"):
        scope.append(Object.user_id == user["user_id"])

    year_col = func.extract("year", Absence.abs_date_start)
    years = [
        int(y)
        for y in db.scalars(
            select(year_col.distinct())
            .join(Object, Absence.object_id == Object.id)
            .where(*scope)
            .order_by(year_col.desc())
        )
    ]

    filters = list(scope)
    if year is not None:
        filters.append(year_col == year)
    if object_id is not None:
        filters.append(Absence.object_id == object_id)

    total = (
        db.scalar(
            select(func.count())
            .select_from(Absence)
            .join(Object, Absence.object_id == Object.id)
            .where(*filters)
        )
        or 0
    )
    pages = max(1, -(-total // per_page))
    page = min(page, pages)

    q = (
        select(Absence, Object.name, AbsenceType.name)
        .join(Object, Absence.object_id == Object.id)
        .outerjoin(AbsenceType, Absence.type_id == AbsenceType.id)
        .where(*filters)
        .order_by(Absence.abs_date_start.desc(), Absence.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {
        "rows": [
            {
                "id": a.id,
                "object_id": a.object_id,
                "object_name": object_name,
                "type_id": a.type_id,
                "type_name": type_name,
                "abs_date_start": a.abs_date_start,
                "abs_date_end": a.abs_date_end,
                "description": a.description,
            }
            for a, object_name, type_name in db.execute(q)
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "years": years,
    }
