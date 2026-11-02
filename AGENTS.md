# Agent instructions

This is the repository policy for every coding agent working here.

This repo is the high-code track of a PoC that compares Mendix + Maia Make with an agentic software factory. The app is the "Material Shortage Cockpit": it reads SAP OData V2 sandbox APIs (production orders, material stock, product) and writes purchase requisitions to a shared mock. The person steering the agents is a Mendix developer with limited Python experience, so structure and readability come first.

## Stack

- Python 3.12+, Django, server-rendered templates, HTMX.
- No React or SPA framework.

## SAP and secrets

- The SAP base URL comes only from config (`SAP_BASE_URL`).
- The API key comes only from the environment (`SAP_API_KEY`).
- No secrets in code, ever.
- The purchase requisition mock is the only POST target. Never write to the SAP sandbox.

## Code

- Keep business logic in plain functions in `services` modules, not in views or templates.
- Prefer readable over clever: small functions, clear names, type hints, a short docstring on each service function.

## Pull requests

- One PR per issue.
- Never merge without green CI.
- Leave PRs open unless asked to merge.
- If implementation shows the spec is wrong, stop and update the spec in a separate small PR first.
- Review against [REVIEW.md](REVIEW.md).

## Commands

Dependencies are managed with `uv`. Install them with `uv sync`.

- Lint: `uv run ruff check`
- Format: `uv run ruff format` (CI runs `uv run ruff format --check`)
- Test: `uv run pytest`
- Django checks: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`
- Run: `uv run python manage.py runserver`

## Blueprint

The workflow is [Blueprint](https://github.com/owainlewis/blueprint). Its skills are committed in [.claude/skills/](.claude/skills/), so refinement and development use the same version.

- Pinned commit: `fb5a850965039d434343fa1b74f8c7f47eb2bd96`
- The skills are unmodified copies of `skills/` at that commit. Blueprint's MIT licence is in [.claude/skills/BLUEPRINT-LICENSE](.claude/skills/BLUEPRINT-LICENSE).
- To upgrade, replace the skills with those from a newer commit and update the SHA here in the same PR.
