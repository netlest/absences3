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

import sqlalchemy
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from config import settings
from security import verify_password
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
    """Objects the user may manage absences for (all of them for admins)."""
    q = select(Object).order_by(Object.id)
    if not user.get("admin"):
        q = q.where(Object.user_id == user["user_id"])
    return [
        {"id": o.id, "name": o.name, "group_id": o.group_id} for o in db.scalars(q)
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
