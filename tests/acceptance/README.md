# Acceptance tests

One test file per acceptance criterion and invariant in
[spec.md](../../docs/material-shortage-cockpit/spec.md): `test_ac_<n>_<name>.py` and
`test_inv_<n>_<name>.py`. Every test function is named after its ID (`test_ac_14_…`), and each
file's docstring repeats the criterion it proves. Decisions behind this layout: issue #15.

## Red until built

The tests were written before the app (D-24). Each one is marked

```python
pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #20")
```

naming the issue that should make it pass. CI stays green while a test fails as expected.
When the code makes a test pass, `strict=True` turns that into a CI failure: the PR that
builds the feature removes the marker, and from then on the test guards the feature.

If a test starts passing in an earlier PR than the one it names, remove the marker in that PR.

## What the tests may use

- The URLs, the functions named in spec.md's module table, and the exact copy in
  [ui-spec.md](../../docs/ui/ui-spec.md) section 5.
- [support.py](support.py): a fake SAP and a fake requisition mock that answer at the HTTP
  level (the transport under `requests`) with the entity sets and fields from spec.md, plus
  helpers to read pages. The app code is never patched. The fake SAP applies the app's
  `$filter` the way the sandbox does.
- [builders.py](builders.py): the **only** file that touches models, form field names and the
  types of `shortage.calculate`. Implementing PRs fill it in as a thin translation. They never
  change a test's assertions; if a test is wrong, fix the spec first (AGENTS.md).
- `time-machine` freezes today at 3 Nov 2026, 10:00 Amsterdam.

[tests/test_acceptance_support.py](../test_acceptance_support.py) checks the fakes and helpers
themselves, so they can be trusted while the acceptance tests are still red.

## Outside systems

| Tests | Need | Without it |
|---|---|---|
| AC-10, AC-12 (one test each) | `SAP_API_KEY` (live SAP sandbox; CI passes the Actions secret) | skipped |
| AC-24, AC-35 (one test each) | `MOCK_PR_BASE_URL` and `MOCK_API_KEY` (the local mock; CI starts it) | skipped |
| Browser tests (`test_ac_*_browser_*`) | Playwright's Chromium (`uv run playwright install chromium`) | error |

All other tests use the fakes, so they run anywhere.

## Checked by hand, not by a test

| ID | Why | How |
|---|---|---|
| AC-5 | A cold load of the hosted app within 5 s depends on Render and the live sandbox | Timed manual run on the hosted app, result logged |
| INV-2 | "No secrets in the repository" is a property of the repository, not of the app | Secret scanning with push protection on GitHub, and review |
