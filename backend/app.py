"""Absences backend API.

Read-only endpoints over the PostgreSQL schema (see sql_ddl/). Absences are
served from the v_absences view, which pre-splits every absence into one row
per calendar month — so a date-range query returns rows that each lie fully
inside a single month, exactly what the calendar grid needs.
"""

from datetime import date

import sqlalchemy
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from models import Group, Holiday, Object, User, VAbsence, user_groups

app = FastAPI(title="Absences backend")


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


@app.get("/groups")
def list_groups(user_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    """All groups, or only the groups a user belongs to (?user_id=)."""
    q = select(Group).order_by(Group.id)
    if user_id is not None:
        q = q.join(user_groups, user_groups.c.group_id == Group.id).where(
            user_groups.c.user_id == user_id
        )
    return [
        {"id": g.id, "name": g.name, "description": g.description}
        for g in db.scalars(q)
    ]


@app.get("/groups/{group_id}/objects")
def group_objects(group_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Calendar row labels for a group, in stable id order."""
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
    db: Session = Depends(get_db),
) -> list[dict]:
    """Month-split absence periods overlapping [date_from, date_to].

    Optional filters: group_id (the object's group), user_id (the object's
    owner). Each returned row lies within a single calendar month.
    """
    q = (
        select(VAbsence, Object.name.label("object_name"))
        .join(Object, VAbsence.object_id == Object.id)
        .where(
            VAbsence.abs_date_start <= date_to,
            VAbsence.abs_date_end >= date_from,
        )
        .order_by(VAbsence.abs_date_start, VAbsence.object_id)
    )
    if group_id is not None:
        q = q.where(VAbsence.group_id == group_id)
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
        }
        for v, object_name in db.execute(q)
    ]


@app.get("/holidays")
def list_holidays(
    date_from: date = Query(...),
    date_to: date = Query(...),
    country: str = "pl",
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
