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
- End every PR description with the Metrics block below.

## Issue status and comments

Every issue sits on the GitHub Project "Factory" (number 2, owner `VincentGroothaar`). Keep its Status field and its comments up to date while you work, so the board and the issue always show where the work is. Change the status at the moment the stage changes, not at the end of the session.

| Stage | Set Status to | Comment on the issue |
|---|---|---|
| Spec work starts | Creating Spec | What you will clarify or write |
| Spec is agreed | Ready To Implement | Link to the spec or the updated issue body, and the decisions made |
| Coding starts | Implementing | Branch name and short plan |
| The spec turns out wrong | (stays) | What was wrong, the evidence, and the agreed correction, before you change the issue body or the spec |
| PR is open | Reviewing | PR link, CI state, and that the independent review has started |
| Review round done | (stays) | Verdict, number of findings, and what was fixed |
| PR is merged | Done | PR link, and close the issue if the merge did not close it |

- Keep comments short and factual: what happened, links, and what comes next. Never put secrets in a comment; issues are public.
- Look up the field and option IDs with `gh project field-list 2 --owner VincentGroothaar --format json`, the item ID with `gh project item-list 2 --owner VincentGroothaar --format json`, and set the status with `gh project item-edit`.

## Metrics

This repo is measured as part of the PoC. The PR history is the evidence, so every PR description ends with this block, filled in from what actually happened in the session:

```markdown
## Metrics
- Issue: #<number>
- Story: <story label, e.g. story-4, or change-request, or none>
- Covers: <REQ-n, AC-n and INV-n IDs this PR implements or tests, or none>
- Repair rounds: <times checks or CI failed and were fixed before the PR was ready>
- Review findings fixed: <count from the independent review, or 0>
- Blocked by: <what slowed or stopped the work, e.g. sandbox down from 10:20 to 10:45, or none>
```

- Report only facts from this session. Write "unknown" rather than estimating.
- Do not report human effort, confidence, or how much code the human reviewed. The person steering logs those separately.
- Do not write to Notion or any other metrics store. The PR description is the only record you keep.

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
