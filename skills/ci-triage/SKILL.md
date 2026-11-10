---
name: ci-triage
description: Triage a failing Shards-MCP GitHub Actions job or local test, reproduce the smallest fault, repair it with a regression and rerun the relevant matrix. Use for failed CI checks, dependency problems, typecheck failures and review-blocking build errors.
---
# CI triage — evidence before repair

**Trigger:** failed pipeline, failing local test, branch protection red status, dependency or release workflow error.

## Preconditions

Inspect current commit SHA, PR base/head, workflow attempt, runner environment and the failure log. Never trust a status from a different commit. Do not blindly rerun deployments or publish jobs.

## Inputs

Workflow/run URL or exported job log, head SHA, failing step, environment version, file/line references and constraints for making changes.

## Procedure

1. Retrieve the exact failing job and the **first causal error**, not merely the final nonzero exit. Compare to previous working baseline.
2. Select the minimal relevant command: `python -m unittest discover -s tests -v`, `python scripts/docs_check.py`, `python scripts/skillctl.py validate`, `cd web && npm run typecheck`, or a targeted pytest/unittest case.
3. Classify: product defect, test expectation, environment/dependency, flaky timing, missing credential, external service or infrastructure. Capture reproduction instructions and actual output.
4. Patch the smallest source path; add a negative or regression test that fails before the fix when practical. Do not suppress CI jobs, blanket-skip tests or silently lower lint/security thresholds.
5. Re-run targeted tests, then all impacted CI paths including Python 3.11–3.15 matrix as relevant. Audit unresolved failures and independent reviewer comments before approving merge.
6. If the run is blocked by an unavailable external provider, record **BLOCKED_EXTERNAL**, not PASS.

## Verification

Provide before/after run IDs with head SHA, failing line/step, exact command, exit code, regression test and new CI status. Distinguish "locally reproduced" from "CI verified".

## Failure handling

Do not retry an externally consequential workflow without checking idempotency and approvals. On repeated flakiness, collect bounded seeds/timestamps and isolate root cause instead of increasing retries indefinitely.

## Output

**Output:** root cause and category, affected SHA/files, regression evidence, tests run, outstanding failures and merge gate PASS/FAIL/BLOCKED.
