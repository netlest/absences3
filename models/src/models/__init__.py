"""Shared SQLAlchemy models for the absences apps.

Mirrors the PostgreSQL DDL: users, groups, objects, absence_types,
absences, user_groups (association), holidays and the read-only
v_absences view.
"""

from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Table, false, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "Base",
    "User",
    "Group",
    "Object",
    "AbsenceType",
    "Absence",
    "Holiday",
    "VAbsence",
    "user_groups",
    "create_all",
]


class Base(DeclarativeBase):
    pass


def create_all(bind) -> None:
    """Create all tables, skipping mappings of database views."""
    tables = [t for t in Base.metadata.tables.values() if not t.info.get("is_view")]
    Base.metadata.create_all(bind, tables=tables)


user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    admin: Mapped[bool] = mapped_column(server_default=false())
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    owned_groups: Mapped[list["Group"]] = relationship(back_populates="owner")
    groups: Mapped[list["Group"]] = relationship(
        secondary=user_groups, back_populates="users"
    )
    objects: Mapped[list["Object"]] = relationship(back_populates="user")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(String(255))

    owner: Mapped[User | None] = relationship(back_populates="owned_groups")
    users: Mapped[list[User]] = relationship(
        secondary=user_groups, back_populates="groups"
    )
    objects: Mapped[list["Object"]] = relationship(back_populates="group")


class Object(Base):
    __tablename__ = "objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(30), unique=True)
    description: Mapped[str] = mapped_column(String(255))

    user: Mapped[User | None] = relationship(back_populates="objects")
    group: Mapped[Group | None] = relationship(back_populates="objects")
    absences: Mapped[list["Absence"]] = relationship(back_populates="object")


class AbsenceType(Base):
    __tablename__ = "absence_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(50))
    color: Mapped[str | None] = mapped_column(String(30))

    absences: Mapped[list["Absence"]] = relationship(back_populates="type")


class Absence(Base):
    __tablename__ = "absences"

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int | None] = mapped_column(
        ForeignKey("objects.id", ondelete="CASCADE")
    )
    type_id: Mapped[int | None] = mapped_column(
        ForeignKey("absence_types.id", ondelete="CASCADE")
    )
    abs_date_start: Mapped[date] = mapped_column(Date)
    abs_date_end: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(150))

    object: Mapped[Object | None] = relationship(back_populates="absences")
    type: Mapped[AbsenceType | None] = relationship(back_populates="absences")


class VAbsence(Base):
    """Read-only mapping of the v_absences view.

    Each absence is split into one row per calendar month it spans, so the
    underlying absence id repeats across rows; (id, abs_date_start) is the
    composite identity. Never insert/update/delete through this model.
    """

    __tablename__ = "v_absences"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[int] = mapped_column(primary_key=True)
    abs_date_start: Mapped[date] = mapped_column(Date, primary_key=True)
    abs_date_end: Mapped[date] = mapped_column(Date)
    object_id: Mapped[int | None]
    group_id: Mapped[int | None]
    user_id: Mapped[int | None]
    type_id: Mapped[int | None]
    description: Mapped[str | None] = mapped_column(String(150))
    at_color: Mapped[str | None] = mapped_column(String(30))
    at_name: Mapped[str | None] = mapped_column(String(50))
    duration: Mapped[int]


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(4))
    event_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(150))
    recurring: Mapped[bool | None] = mapped_column(server_default=false())
