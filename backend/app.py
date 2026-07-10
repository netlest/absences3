"""Minimal absences backend API."""

import sqlalchemy
from fastapi import Depends, FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from models import Object, User

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
