# ASFPOCMendix

A project to compare the results out of developing the same POC description from plan to develop to test within an Agent Software Factory and Mendix MAIA.

This repository is the high-code track: the **Material Shortage Cockpit**, built with Python, Django, server-rendered templates and HTMX.

## Run locally

You need [uv](https://docs.astral.sh/uv/). It installs the right Python version and all dependencies for you.

```sh
cp .env.example .env              # then fill in SAP_API_KEY
uv sync                           # install Python and dependencies
uv run python manage.py migrate   # create the local SQLite database
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/.

## Run tests and checks

```sh
uv run pytest                     # tests
uv run ruff check                 # lint
uv run ruff format                # format the code
```

CI runs the same checks on every pull request and on `main`.

## Configuration

Settings come from environment variables. Locally they are read from `.env`; see `.env.example` for the full list.

| Variable       | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `SAP_BASE_URL` | Base URL of the SAP OData V2 sandbox                 |
| `SAP_API_KEY`  | API key for the SAP sandbox (never commit it)        |
| `DATABASE_URL` | Database location, default `sqlite:///db.sqlite3`    |
| `DJANGO_SECRET_KEY` | Django signing key; a dev-only key is used if empty |
| `DJANGO_DEBUG` | `true` shows debug pages; off when unset            |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names, default `localhost,127.0.0.1` |

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
- `mock_pr/`: placeholder for the purchase requisition write mock.
- `tests/acceptance/`: acceptance tests, one module per user story.
- `static/`: CSS, images and other static files.
- `docs/`: specs.
