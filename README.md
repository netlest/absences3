# Absences calendar

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with
three packages:

- **`frontend/`** — FastAPI + Jinja2 app that renders the monthly absence
  calendar as an HTML/CSS grid, replacing the static PNG the legacy app's
  `image.py` produced. The grid layout, colours and proportions match the
  original image. The page around it (navbar, forms, the `/manage` admin page)
  uses Tailwind CSS (Play CDN) and htmx. It holds no data itself: every page
  calls the backend API.
- **`backend/`** — JSON API (FastAPI + SQLAlchemy) on PostgreSQL: session
  login, group-scoped absence data, absence create/edit/delete, and admin CRUD
  for users, groups, objects, absence types and holidays.
- **`models/`** — shared SQLAlchemy 2.0 models (users, groups, objects,
  absence types, absences, the `v_absences` view, sessions, user_groups,
  holidays). The backend depends on it as a workspace package.

## Local development database

The backend talks to a local PostgreSQL database called `kalendarz`, reached
over the Unix socket (peer auth — no password in the connection string). One-time
setup:

```bash
createdb -T template0 kalendarz
psql -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE kalendarz TO adam;"
psql -d kalendarz -v ON_ERROR_STOP=1 -f sql_ddl/schema.sql
psql -d kalendarz -v ON_ERROR_STOP=1 -f sql_ddl/v_absences.sql
cp backend/.env.example backend/.env
uv run --directory backend python seed_dev.py
```

`-T template0` sidesteps the collation-version mismatch a `template1` created
under an older glibc reports; drop it if your `template1` is current.

`seed_dev.py` fills an empty database with an admin login (`admin` / `admin`),
one group, three objects, four absence types, a few September 2026 absences and
the Polish holidays — development only, and a no-op once `users` has rows.

Connection settings live in `backend/.env` (gitignored, see
`backend/.env.example`):

```
DATABASE_URL=postgresql+psycopg:///kalendarz
```

Start over with `dropdb kalendarz` and re-run the block above.

## Run with uv (recommended)

[uv](https://docs.astral.sh/uv/) reads the workspace `pyproject.toml`, creates
one shared virtual environment and installs everything on the first `uv run` —
no manual venv or `pip install` step. From the repo root:

```bash
uv run --directory frontend uvicorn app:app --reload --port 8000
uv run --directory backend  uvicorn app:app --reload --port 8001
```

Open http://127.0.0.1:8000/ and log in (`admin` / `admin` after seeding).
http://127.0.0.1:8001/ reports API status, and http://127.0.0.1:8001/health/db
checks the database connection. The frontend reaches the backend at
`BACKEND_URL` (default `http://127.0.0.1:8001`).

Run the frontend tests. They need no database or backend, because the
backend API is stubbed by monkeypatching `api_client`:

```bash
uv run --directory frontend pytest
```

(Optional: `uv sync --all-packages` pre-installs everything, dev tools included.)

## Linting and formatting (ruff)

[Ruff](https://docs.astral.sh/ruff/) is the linter and formatter for the whole
workspace. It is a dev dependency of the workspace root and is configured in
`[tool.ruff]` in the root `pyproject.toml`. From the repo root:

```bash
uv run ruff check .            # lint (add --fix to apply safe fixes)
uv run ruff format .           # format in place
uv run ruff format --check .   # what CI runs: fail if anything would change
```

The rule set is ruff's defaults plus **UP045**: write optional types as
`X | None`, not `typing.Optional[X]` (PEP 604; the code targets Python 3.10+).
FastAPI's `Depends`/`Form`/`Query` are whitelisted for bugbear's B008, since
calling them in argument defaults is how FastAPI works. CI runs both ruff checks
before the tests, so run them before pushing.

## Frontend URLs

| URL                          | Shows                                   |
|------------------------------|-----------------------------------------|
| `/login`                     | login form (every other page needs it)  |
| `/`                          | last view, else this month              |
| `/05/2026`                   | May 2026 (`/{month}/{year}`)            |
| `/05/2026?months=3&group=2`  | May–July 2026, group 2 only             |
| `/absences/new`              | add an absence                          |
| `/manage`                    | CRUD for all entities (admin tabs)      |
| `/password`                  | change your password                    |
| `/debug/session`             | your own session as JSON                |
| `/version`                   | frontend + backend build (no login)     |

`/` with no query parameters resumes the last view — month, year, month
count and group are written to the user's `users.prefs` column on every
navigation (last view wins) and read back on the next request. They are
kept permanently per user, independent of the session: after a logout or
an expired session (`SESSION_TTL_HOURS`) the next login resumes the same
view. Only a user with no saved prefs starts on the current month.

## Docker

One image (`Dockerfile`) serves both apps. The container argument picks which
app runs:

```bash
docker run -e DATABASE_URL=... ghcr.io/netlest/absences3 backend    # API on :8001
docker run -e BACKEND_URL=...  ghcr.io/netlest/absences3 frontend   # UI  on :8000
```

Configuration is environment-only:

- backend: `DATABASE_URL` (required), `SESSION_TTL_HOURS` (default 48)
- frontend: `BACKEND_URL`
- both: `PORT`

The GitHub Actions workflow runs `ruff check`, `ruff format --check` and the
frontend tests, then publishes the image
to GHCR on pushes to `main` and `v*` tags.

### Which build is running?

CI bakes the commit SHA and build time into the image (`GIT_SHA` /
`BUILD_DATE` build args → `APP_VERSION` / `APP_BUILD_DATE` env vars). The
calendar footer shows `build <short sha> · <build time>`; if the backend
container runs a different build (or can't report one), the footer adds a
red `· backend <sha>`. The same data is available as JSON at the frontend's
`/version` and the backend's `GET /version`. Outside Docker, or for a local
`docker build` without `--build-arg GIT_SHA=$(git rev-parse HEAD)`, the
version is `dev`.

## Files

- `pyproject.toml` — uv workspace root (members: `frontend`, `backend`,
  `models`), the root `dev` group (ruff) and the ruff config. The shared
  `uv.lock` lives next to it.
- `sql_ddl/schema.sql`, `sql_ddl/v_absences.sql` — the PostgreSQL schema and
  the `v_absences` view, which splits multi-month absences into one row per
  month. They are applied by hand: the apps never create or migrate tables.
- `sql_ddl/migrations/` — numbered, idempotent upgrade scripts for databases
  created from an older `schema.sql`; apply them in order with
  `psql -d kalendarz -v ON_ERROR_STOP=1 -f sql_ddl/migrations/<file>.sql`.
- `models/src/models/__init__.py` — declarative models mirroring the DDL,
  importable as `from models import User, Absence, VAbsence, ...`.
- `backend/app.py` — the whole API. Login issues an opaque bearer token stored
  in the `sessions` table. Non-admins only see the groups they belong to.
  Absence and object writes are owner-or-admin; the rest of the CRUD is
  admin-only.
- `backend/security.py` — scrypt password hashing in Werkzeug's format, so the
  hashes stay compatible with the original Flask app.
- `backend/config.py` — settings from the environment or `backend/.env`.
- `backend/seed_dev.py` — one-shot development seed (admin login, sample
  group/objects/absences/holidays). It refuses to run twice.
- `frontend/app.py` — login/logout, password change, absence forms and the
  calendar routes (`/` and `/{month}/{year}`) with prev/next navigation.
- `frontend/api_client.py` — the HTTP client for the backend. It sends the
  session cookie's token as a Bearer header and turns 401/422/4xx responses
  into exceptions.
- `frontend/calendar_grid.py` — pure function `build_context(...)` that
  computes the grid (CW week bars, weekend shading, day numbers, holidays,
  absence blocks, current-day/month highlights). It has no framework
  dependencies and accepts `today=` to freeze "today" in tests.
- `frontend/manage.py`, `frontend/manage_entities.py` — the `/manage` page.
  Each entity is declared once (table columns and form fields), and one
  generic htmx router renders them all.
- `frontend/templates/`, `frontend/static/` — Jinja2 templates and page JS.
- `frontend/tests/` — route and `/manage` tests against a stubbed backend.

## Calendar layout (mirrors `image.py`)

- Fixed width: one 250px label column + 31 day columns of 25px each; rows 35px tall.
- Row 1: ISO week (`CW nn`) bars over week-days only (`#ba90ba`).
- Row 2: day numbers; weekends shaded (`#a090a0`), holidays magenta (`#e121ff`).
- Rows 3+: one per object; absences drawn as coloured, captioned blocks that can span multiple days.
- Months shorter than 31 days get the dark padding column(s) (`#605060`) on the right.
- The current month gets a 2px white frame; the current day a 2px white outline.
- Grid lines are painted by a 1px gap over a `#808080` background.
