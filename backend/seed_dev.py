"""Seed the local development database with a minimal, usable dataset.

Idempotent: skips seeding when a `users` row already exists. Never run
against production — it creates a well-known admin password.

    uv run --directory backend python seed_dev.py
"""

from datetime import date

from sqlalchemy import select

from db import SessionLocal
from models import Absence, AbsenceType, Group, Holiday, Object, User
from security import hash_password

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

ABSENCE_TYPES = [
    ("Urlop", "#7ec8e3"),
    ("Zwolnienie", "#e3a17e"),
    ("Delegacja", "#9ee37e"),
    ("Praca zdalna", "#c8a2e3"),
]

HOLIDAYS_PL = [
    (date(2026, 1, 1), "Nowy Rok"),
    (date(2026, 1, 6), "Trzech Kroli"),
    (date(2026, 5, 1), "Swieto Pracy"),
    (date(2026, 5, 3), "Swieto Konstytucji 3 Maja"),
    (date(2026, 8, 15), "Wniebowziecie NMP"),
    (date(2026, 11, 1), "Wszystkich Swietych"),
    (date(2026, 11, 11), "Narodowe Swieto Niepodleglosci"),
    (date(2026, 12, 25), "Boze Narodzenie"),
    (date(2026, 12, 26), "Boze Narodzenie (2. dzien)"),
]


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            print("Database already seeded — nothing to do.")
            return

        admin = User(
            username=ADMIN_USERNAME,
            password=hash_password(ADMIN_PASSWORD),
            admin=True,
        )
        db.add(admin)
        db.flush()

        group = Group(user_id=admin.id, name="Zespol", description="Zespol testowy")
        db.add(group)
        db.flush()
        group.users.append(admin)

        types = [AbsenceType(name=name, color=color) for name, color in ABSENCE_TYPES]
        db.add_all(types)

        objects = [
            Object(
                user_id=admin.id,
                group_id=group.id,
                name=name,
                description=description,
            )
            for name, description in [
                ("Adam Zaleski", "Developer"),
                ("Anna Nowak", "Analityk"),
                ("Piotr Kowalski", "Tester"),
            ]
        ]
        db.add_all(objects)
        db.flush()

        db.add_all(
            [
                Absence(
                    object_id=objects[0].id,
                    type_id=types[0].id,
                    abs_date_start=date(2026, 9, 7),
                    abs_date_end=date(2026, 9, 11),
                    description="Urlop wypoczynkowy",
                ),
                Absence(
                    object_id=objects[1].id,
                    type_id=types[1].id,
                    abs_date_start=date(2026, 9, 14),
                    abs_date_end=date(2026, 9, 16),
                    description="L4",
                ),
                Absence(
                    object_id=objects[2].id,
                    type_id=types[2].id,
                    abs_date_start=date(2026, 9, 28),
                    abs_date_end=date(2026, 10, 2),
                    description="Delegacja Berlin",
                ),
            ]
        )

        db.add_all(
            [
                Holiday(country="PL", event_date=day, description=text, recurring=True)
                for day, text in HOLIDAYS_PL
            ]
        )

        db.commit()
        print(f"Seeded: login {ADMIN_USERNAME!r} / {ADMIN_PASSWORD!r}")


if __name__ == "__main__":
    main()
