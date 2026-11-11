# ASFPOCMendix

A project to compare the results out of developing the same POC description from plan to develop to test within an Agent Software Factory and Mendix MAIA.

This repository is the high-code track: the **Material Shortage Cockpit**, built with Python, Django, server-rendered templates and HTMX.

## Run locally

You need [uv](https://docs.astral.sh/uv/), which installs the right Python version and all dependencies, and [Docker](https://docs.docker.com/get-docker/), which runs the local Postgres database. The app uses Postgres in every environment; there is no SQLite fallback.

```sh
cp .env.example .env              # then fill in SAP_API_KEY and the TEST_PASSWORD_* values
docker compose up -d              # start Postgres (data is kept in a Docker volume)
uv sync                           # install Python and dependencies
uv run python manage.py migrate   # create the tables in Postgres
uv run python manage.py create_test_users   # one account per role, see below
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in. Every page needs a login.

**Accounts and roles.** `create_test_users` creates or resets five accounts: `viewer`, `planner`, `manager_a`, `manager_b` (two Managers, to check that nobody approves their own requisition) and `admin`. Each password comes from its own variable (`TEST_PASSWORD_VIEWER`, `TEST_PASSWORD_PLANNER`, `TEST_PASSWORD_MANAGER_A`, `TEST_PASSWORD_MANAGER_B`, `TEST_PASSWORD_ADMIN`) and must pass Django's password rules (at least 8 characters, not too common, not only digits). If one is missing or too weak, the command stops and changes nothing. A user's role is the one role group they are in; what each role may do is fixed in `cockpit/services/roles.py`. `admin` manages users and roles at `/admin/` and cannot open business pages.

## Run tests and checks

Postgres must be running (`docker compose up -d`); the tests create and remove their own `test_cockpit` database.

Browser tests use [Playwright](https://playwright.dev/python/). Download its browser once, and again after Playwright is upgraded:

```sh
uv run playwright install chromium
```

```sh
uv run pytest                     # tests
uv run ruff check                 # lint
uv run ruff format                # format the code
```

CI runs the same checks on every pull request and on `main`. It also starts the write mock (`mock_pr/`) on `http://localhost:8001` before the tests, with a key made up for that run, and sets `MOCK_PR_BASE_URL` and `MOCK_API_KEY` for them.

## Configuration

Settings come from environment variables. Locally they are read from `.env`; see `.env.example` for the full list.

| Variable       | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `SAP_BASE_URL` | Base URL of the SAP OData V2 sandbox                 |
| `SAP_API_KEY`  | API key for the SAP sandbox (never commit it)        |
| `DATABASE_URL` | Postgres URL, required, e.g. `postgresql://cockpit:cockpit@localhost:5432/cockpit` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Used by `docker compose` to create the local database |
| `MOCK_PR_BASE_URL`, `MOCK_API_KEY` | Purchase requisition mock: its base URL (for the Cockpit) and its API key (for both); see `mock_pr/README.md` |
| `DJANGO_SECRET_KEY` | Django signing key; a dev-only key is used if empty, except when `DJANGO_HTTPS=true` |
| `DJANGO_DEBUG` | `true` shows debug pages; off when unset            |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names, default `localhost,127.0.0.1` |
| `TEST_PASSWORD_VIEWER`, `TEST_PASSWORD_PLANNER`, `TEST_PASSWORD_MANAGER_A`, `TEST_PASSWORD_MANAGER_B`, `TEST_PASSWORD_ADMIN` | Passwords of the five PoC accounts, read by `create_test_users` |
| `DJANGO_HTTPS` | `true` when hosted behind an HTTPS proxy (Render): redirects to HTTPS and sends cookies over HTTPS only; off when unset |

## Deploy on Render

The app runs as its own Render web service next to the mock (see `mock_pr/README.md`) and uses the same free Postgres database `poc-db`. The app's tables live in the default `public` schema; the mock keeps its own schema `mock_pr`, so they never touch each other. Creating the service is done by hand, because it needs the Render login.

1. **New → Web Service**, repository `ASFPOCMendix`, branch `main`, region Frankfurt (same as the database), Free plan, runtime Python. Render reads the Python version from `.python-version` and deploys again on every merge to `main`.
2. **Build command:**
   ```sh
   pip install uv && uv sync --locked --no-dev --inexact && uv run --no-sync python manage.py collectstatic --no-input
   ```
   `--inexact` keeps `uv` itself installed (see `mock_pr/README.md`). `collectstatic` copies the static files (for now the Django admin styles) into `staticfiles/`, where WhiteNoise serves them from.
3. **Start command:**
   ```sh
   uv run --no-sync python manage.py migrate --no-input && uv run --no-sync python manage.py create_test_users && uv run --no-sync gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 2 --timeout 120
   ```
   Migrations and `create_test_users` run at start-up because the free plan has no pre-deploy step or shell; with nothing to migrate this takes a second. **Any change made to the five PoC accounts (password, role, active) is undone on every restart, and a free service restarts every time it wakes from sleep.** Other users are never touched. `--timeout 120` gives a slow SAP sync time to finish, since the sync runs inside the request.
4. **Environment variables** (only here, never in the repository):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | The Internal Database URL of `poc-db` (the same as the mock's) |
   | `DJANGO_SECRET_KEY` | A long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(50))"`. The app refuses to start without it |
   | `DJANGO_HTTPS` | `true` |
   | `DJANGO_DEBUG` | `false` |
   | `DJANGO_ALLOWED_HOSTS` | Optional: Render's own host name (`<service>.onrender.com`) is added automatically. Only for extra host names, without `https://` |
   | `SAP_BASE_URL`, `SAP_API_KEY` | As in your local `.env` |
   | `MOCK_PR_BASE_URL` | The mock's public URL on Render, e.g. `https://<mock-service>.onrender.com` |
   | `MOCK_API_KEY` | The same key as on the mock service |
   | `TEST_PASSWORD_VIEWER`, `TEST_PASSWORD_PLANNER`, `TEST_PASSWORD_MANAGER_A`, `TEST_PASSWORD_MANAGER_B`, `TEST_PASSWORD_ADMIN` | One strong password per PoC account. The service does not start if one is missing or too weak |

5. **Deploy**, then check the public URL: `/` and `/admin/` both end on the login page with its styling, `admin` can log in and reaches user administration, and `http://` redirects to `https://`.

   Errors and refused requests appear in the service's **Logs** tab on Render.

Free services sleep after 15 minutes idle, so the first request after a pause takes about a minute; that wake-up time does not count towards the 5-second load target (D-17). The free database expires 30 days after it was created (see #10 for the date).

## Where things live

If you know Mendix, this is how its concepts map to this repository.

| Mendix                      | Here                                         |
| --------------------------- | -------------------------------------------- |
| Domain model                | `cockpit/models.py`                          |
| Microflows                  | `cockpit/services/`                          |
| Pages                       | `templates/` and `cockpit/templates/cockpit/` |
| User roles and module roles | Django groups and permissions                |
| Constants                   | `config/settings.py`, filled from `.env`     |
| Consumed OData service      | `sap/`                                       |

Other folders:

- `config/`: Django project settings, top-level URLs and the WSGI entry point.
- `cockpit/views.py` and `cockpit/urls.py`: which URL shows which page. Views stay thin and call services.
- `cockpit/tests/`: unit tests for the cockpit app.
- `mock_pr/`: the purchase requisition write mock, a separate FastAPI service; see `mock_pr/README.md`.
- `tests/acceptance/`: acceptance tests, one module per user story.
- `static/`: CSS, images and other static files.
- `docs/`: specs.
