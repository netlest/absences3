# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

uv workspace (members `frontend`, `backend`, `models`; one shared `.venv` and `uv.lock` at the repo root). Run everything from the repo root:

```bash
uv run --directory frontend uvicorn app:app --reload --port 8000   # UI
uv run --directory backend  uvicorn app:app --reload --port 8001   # API
uv run --directory frontend pytest                                  # all tests (what CI runs)
uv run --directory frontend pytest tests/test_manage.py::test_name  # single test
uv run ruff check .                                                 # lint (--fix to autofix)
uv run ruff format .                                                # format (--check in CI)
uv sync --all-packages                                              # optional pre-install
```

Ruff is the linter and formatter (root `dev` dependency group; config in `[tool.ruff]` of the root `pyproject.toml`): ruff's default rules plus **UP045** — write `X | None`, never `Optional[X]`. `src` lists the member dirs so isort treats `api_client`, `models`, etc. as first-party; FastAPI `Depends`/`Form`/`Query` are exempt from B008. All code must pass `ruff check .` and `ruff format --check .`. There is no backend test suite; the only tests are in `frontend/tests/`.

### Local database

The backend needs PostgreSQL. Local dev uses a database `kalendarz` over the Unix socket (peer auth): `DATABASE_URL=postgresql+psycopg:///kalendarz` in `backend/.env` (copy `backend/.env.example`; `database_url` has no default, so the backend won't start without it). The schema is applied by hand from `sql_ddl/schema.sql` then `sql_ddl/v_absences.sql` — the app never creates or migrates tables (no `create_all`). Schema changes also get an idempotent upgrade script in `sql_ddl/migrations/` for existing databases; `backend/migrate.py` (Docker: `migrate` command) re-runs all of them in name order on every deploy, so they must be safe to re-run. `uv run --directory backend python seed_dev.py` seeds an empty DB (login `admin`/`admin`); it's a no-op once `users` has rows. Full setup steps are in README.md.

### Docker

One image for both apps (`Dockerfile`, `docker-entrypoint.sh`): the container argument picks `backend` (default, :8001) or `frontend` (:8000). Config is env-only: backend `DATABASE_URL`, `SESSION_TTL_HOURS` (default 48); frontend `BACKEND_URL` (default `http://127.0.0.1:8001`); `PORT` for both. CI (`.github/workflows/docker-publish.yml`) runs `ruff check`, `ruff format --check` and the frontend tests, then publishes to `ghcr.io/netlest/absences3` on pushes to `main` and `v*` tags.

## Architecture

Two separate FastAPI processes. The **frontend never touches the database** — it renders HTML and gets all data from the backend over HTTP.

- **`models/`** — shared SQLAlchemy 2.0 declarative models (`from models import User, Absence, VAbsence, UserSession, ...`) mirroring `sql_ddl/schema.sql`. Keep the models and the DDL in sync by hand. `VAbsence` maps the `v_absences` view, which splits multi-month absences into one row per month (a recursive CTE) — the calendar reads from it.
- **`backend/app.py`** — the whole JSON API in one file. Auth is opaque bearer tokens stored in the `sessions` table (`session_id`, JSON `data`, `expiry`); `_session_or_401` → `current_user` → `require_admin` are the dependency chain. Data endpoints are group-scoped: non-admins only see groups they belong to (`_allowed_group_ids`), and absence/object writes are owner-or-admin (`_may_edit`). Admin CRUD lives under `/users`, `/groups`, `/objects`, `/absence_types`, `/holidays`. Write bodies are Pydantic models with constrained types (`Str30`, `Username`, `Color`, ...) so that 422 field errors can be shown next to form inputs in the UI. `security.py` hashes passwords with stdlib scrypt in **Werkzeug's format** (`scrypt:N:r:p$salt$hex`) for compatibility with the legacy Flask app's `users.password` values — don't change the format.
- **`frontend/api_client.py`** — the only path to the backend. `_request()` turns HTTP status codes into exceptions (`Unauthorized` on 401, `ValidationApiError` with a `{field: msg}` dict on 422, `ApiError` on other 4xx, `BackendUnavailable` for connection errors/5xx). Generic admin CRUD uses `Resource(path)` instances. The session token comes from the frontend's HttpOnly `session` cookie and is sent as `Authorization: Bearer`.
- **`frontend/app.py`** — login/logout/password, absence create/edit/delete forms, and the calendar. `/{month}/{year}` (month first) is a catch-all, so new routes must be registered before it. View prefs (month, year, month count, group) are saved permanently to the `users.prefs` JSONB column via `PUT /auth/prefs` on every render and read back (via `GET /auth/me`) when `/` is hit without parameters — they outlive sessions. The cookie lifetime and backend session TTL both come from `SESSION_TTL_HOURS`.
- **`frontend/calendar_grid.py`** — pure, framework-free `build_context(...)` that computes the CSS grid (CW week bars, weekends, holidays, absence blocks, today/current-month highlights; accepts `today=` for tests). The layout intentionally reproduces the legacy `image.py` PNG (250px label column, 31×25px day columns, 35px rows, fixed colours — see README "Calendar layout").
- **`/manage` page** — `manage_entities.py` declares each entity (`Entity` with `Column`s and `FormField`s); `manage.py` is a generic htmx router that re-renders the whole `#manage-area` fragment for tab switches, forms and submits (one code path for success, field errors and refreshed tables), and wraps it in the full page for non-htmx requests. Adding a managed entity = an `Entity` in `manage_entities.py` + a `Resource` in `api_client.py` + a loader entry in `manage.py`, no new templates. Authorization is enforced by the backend (403); the frontend only hides tabs.
- Templates use Jinja2 + Tailwind (Play CDN) + htmx; page JS is in `frontend/static/`.

### Tests

Frontend tests need no backend or database: an autouse `fake_backend` fixture in each test file monkeypatches the module-level functions of `api_client` (`get_groups`, `get_absences`, `login`, ...) with in-memory fakes. When adding a new `api_client` function used by a route, stub it there too.

## Notes

- UI text and seed data are partly Polish (holidays, absence type names like "Urlop").
