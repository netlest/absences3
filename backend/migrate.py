"""Apply the SQL upgrade scripts in sql_ddl/migrations/ to DATABASE_URL.

    python migrate.py                     # from backend/, or:
    docker compose run --rm absences-backend migrate

Every *.sql file is run in name order, each in its own transaction (a failing
script rolls back and stops the run). The scripts are written to be
idempotent, so all of them run every time — no bookkeeping table is needed,
and re-running after a partial failure is safe. The image ships no psql
client; this goes through the backend's own psycopg driver.
"""

import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql_ddl" / "migrations"


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def main() -> int:
    files = migration_files()
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    from db import engine  # imported late: needs DATABASE_URL

    raw = engine.raw_connection()
    try:
        for path in files:
            print(f"Applying {path.name} ...", flush=True)
            try:
                with raw.cursor() as cur:
                    # No parameters, so psycopg sends the whole multi-statement
                    # script in one simple-protocol query.
                    cur.execute(path.read_text())
                raw.commit()
            except Exception as exc:
                raw.rollback()
                print(f"FAILED {path.name}: {exc}", file=sys.stderr)
                return 1
    finally:
        raw.close()
    print(f"Done: {len(files)} migration(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
