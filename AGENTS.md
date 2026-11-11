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

## UI

- The UI follows [docs/ui/](docs/ui/): [ui-spec.md](docs/ui/ui-spec.md) for layout, states, roles and exact copy, [tokens.css](docs/ui/tokens.css) for every colour, size and spacing value, and [wireframes.pdf](docs/ui/wireframes.pdf) for the look.
- When they disagree, [spec.md](docs/material-shortage-cockpit/spec.md) wins over `ui-spec.md`, which wins over the wireframes and screenshots. Report the conflict instead of guessing.
- `docs/ui/source/*.html` is reference markup only. Read it; don't copy it in as app code.
- Every PR that changes the UI includes a screenshot of each changed screen in its description.

## Pull requests

- One PR per issue.
- Never merge without green CI.
- Leave PRs open unless asked to merge.
- If implementation shows the spec is wrong, stop and follow the wrong-spec rule in [Workflow](#workflow).
- Review against [REVIEW.md](REVIEW.md).
- End every PR description with the Metrics block below.

## Workflow

Every issue goes through these steps in order. Each step runs a Blueprint skill from [.claude/skills/](.claude/skills/). Load the skill itself and follow its steps. Don't work from memory of what it says. If a skill cannot be loaded, stop and tell the human.

| # | Step | Skill | Who starts it | Board status | Done when |
|---|---|---|---|---|---|
| 1 | Spec | `spec` | The agent, when it picks up an issue in Ready For Spec, or the human with `/spec <issue>` | Creating Spec | The human has answered every behaviour, data, interface and security choice |
| 2 | Architecture | `architecture` | The agent, right after the spec | Creating Spec | `ARCHITECTURE.md` matches the spec, or the comment says why no change is needed |
| 3 | Design review | `architecture-review` | The agent, after step 2 | Creating Spec | Verdict is `Approve`, and the human has decided each Blocker or Important finding |
| 4 | Spec gate | none | The human approves in the chat, then the agent sets the status | Ready To Implement | The spec is Accepted and `[spec-gate]` is posted |
| 5 | Build and test | `task-to-pr`, which runs `test` | The agent, after step 4 | Implementing | All checks are green, every criterion is `Pass`, and the PR is open |
| 6 | Review | `review` (inside `task-to-pr`) | The agent | Reviewing | Verdict is `Approve` and CI is green |
| 7 | Merge | none | The human asks | Done | The PR is merged |

- In step 1, ask the human about each choice the spec needs, with your recommended answer, and wait for the reply. Never answer your own spec questions. A recommendation counts as a decision only after the human accepts it. Each answer is an escalation (see [Escalation](#escalation)), so it gets its own `[decision]` comment.
- Step 2 always runs. If the spec changes no boundary, data ownership, interface, trust boundary or deployment, the step ends with a comment saying so and why.
- If step 2 changes `ARCHITECTURE.md`, update the spec's technical design to match before step 3, and post that as a `[spec]` comment. The design review must see a spec and an architecture that agree.
- Spec gate: only the human approves a spec, in the chat. After that approval the agent sets the issue to Ready To Implement, sets the spec's `Status:` to Accepted, and marks the `ARCHITECTURE.md` decisions the human approved as Accepted. It then posts `[spec-gate]` and starts step 5. Never start step 5 without that approval.
- When `task-to-pr` reaches its test and review steps, load the `test` and `review` skills as well.
- Fix rounds: when a review returns `Request changes`, set the issue back to Implementing, fix the findings, and run `test` again. Set it to Reviewing again when the next review starts. Repeat until the verdict is `Approve`.
- `requirements` and `plan` can only be started by the human. If `task-to-pr` says to split the work with `plan`, escalate instead.
- If the spec, `ARCHITECTURE.md` or `REQUIREMENTS.md` turns out wrong during steps 5 and 6, escalate. This rule overrides `task-to-pr` step 3: never fix them in the feature PR. After the human decides, fix a spec file in a separate small PR first. If the spec lives in the issue body, post the `[decision]` comment and then edit the body.
- `review` and `architecture-review` run in a fresh reviewer that changes nothing and posts nothing. The agent that started the reviewer posts its result.
- `review` uses [REVIEW.md](REVIEW.md) as this repo's review standard.

## Issue status and comments

Every issue sits on the GitHub Project "Factory" (number 2, owner `VincentGroothaar`). Keep its Status field and its comments up to date while you work, so the board and the issue always show where the work is. Change the status at the moment the step changes, not at the end of the session.

Each step and each skill run gets its own comment on the issue. Never combine two steps in one comment. Start every comment with its tag in bold, for example `**[architecture-review]**`, so the history can be read step by step.

| Tag | When | Comment content |
|---|---|---|
| `[spec]` | Spec work starts | What will be clarified or written |
| `[spec]` | Spec is written | Link to the spec or the issue body, and each decision with who made it |
| `[architecture]` | Step 2 ends | Link to the `ARCHITECTURE.md` change and its main decisions, or why no change is needed |
| `[architecture-review]` | Each design review round | Verdict, findings by severity, and what was changed |
| `[spec-gate]` | The human approves | A quote of the approval, when it was given, the link to the agreed spec, and what was marked Accepted |
| `[task-to-pr]` | Coding starts | Branch name and a short plan |
| `[test]` | Each test run | Each criterion with Pass, Fail or Unverified, and the commands run |
| `[task-to-pr]` | The PR is open | PR link and CI state |
| `[review]` | Each review round | Verdict, findings by severity, what was fixed, and the reviewed commit |
| `[decision]` | After every escalation, including each spec or architecture answer | The step that raised it, the question, the options, the choice, and who decided |
| `[spec]` | The spec turns out wrong | What was wrong, the evidence, and the agreed correction, before you change the issue body or the spec |
| `[merge]` | The PR is merged | PR link, and close the issue if the merge did not close it |

- Keep comments short and factual: what happened, links, and what comes next. Never put secrets in a comment; issues are public.
- Look up the field and option IDs with `gh project field-list 2 --owner VincentGroothaar --format json`, the item ID with `gh project item-list 2 --owner VincentGroothaar --format json`, and set the status with `gh project item-edit`.

## Escalation

Some problems are for the human to decide. When a step runs into one, stop that step and raise it in the chat. Don't solve it yourself and carry on. These problems need the human:

- A skill step says to ask the user, for example each spec question in `spec` or a design choice in `architecture`.
- `architecture-review` reports a Blocker or Important finding.
- `review` reports a Must fix whose fix would change the spec.
- The spec, `ARCHITECTURE.md` or `REQUIREMENTS.md` turns out wrong during the build.
- `task-to-pr` wants to split the work with `plan`.
- `test` leaves a criterion `Unverified`, for example because the live sandbox is down.
- The spec, `ui-spec.md` and the wireframes disagree.
- The same check fails three rounds in a row.
- A reviewer returns `Blocked`.

Ask one question at a time. Say which step raised it, give the options and your recommended answer, and wait for the human's reply. Once the human has decided, post a `**[decision]**` comment, then update the spec or the issue body. If the human tells you to use your own judgement, the comment says so. Never record a decision the human did not make.

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
- The skills are copies of `skills/` at that commit, with these changes: `spec`, `architecture`, `architecture-review`, `task-to-pr`, `test` and `review` don't have the `disable-model-invocation: true` frontmatter line (for Claude Code), and their `agents/openai.yaml` sets `allow_implicit_invocation: true` (for Codex). This lets agents load them in the [Workflow](#workflow). Two further edits cut token use: `spec` asks for a diagram only when the flow changes, and `architecture` checks the Mermaid text instead of rendering it. All other skills are unmodified. Blueprint's MIT licence is in [.claude/skills/BLUEPRINT-LICENSE](.claude/skills/BLUEPRINT-LICENSE).
- To upgrade, replace the skills with those from a newer commit, make both changes to the same six skills again, and update the SHA here in the same PR.
