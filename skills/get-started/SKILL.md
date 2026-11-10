---
name: get-started
description: First-run Shards-MCP onboarding for a new human contributor or AI coding agent. Use to inspect the repository, discover skills, verify local prerequisites and complete a safe, read-only first workflow without credentials or hosted-service assumptions.
---
# Get started — first agent session

**Trigger:** new AI coding agent, new contributor, first interaction with Shards-MCP, or a clean environment. This is **developer onboarding**, not privileged gateway agent registration; see [agent-onboarding](../agent-onboarding/SKILL.md) separately.

## Preconditions

- Authorised read access to the repository; working directory is the cloned repository root.
- Python 3.11+ (or report BLOCKED). No provider secrets, live account permissions or GitHub write access required.
- Identify current branch and commit SHA; note unfinished PRs. Never assume `main` includes an open PR's changes.

## Inputs

Repository path, requested role (reviewer/implementer/operator), intended task, Python version, allowed tools and any approved environment constraints. All other credentials are optional and must remain out of generated transcripts.

## Procedure

1. Read `AGENTS.md`, `SECURITY.md`, `README.md`, `docs/README.md`. Summarise the implemented gateway and major non-implemented boundaries; do not repeat marketing as proof.
2. Discover with `python scripts/skillctl.py list`; inspect `skills/MAP.md`. Choose one primary skill using `python scripts/skillctl.py suggest --task "TASK"` as a hint; read it via `python scripts/skillctl.py show SKILL_NAME`.
3. Run the **read-only** preflight:
   ```sh
   python skills/get-started/scripts/preflight.py --json
   python scripts/skillctl.py validate
   python scripts/docs_check.py
   ```
4. If Python distribution is absent, follow `docs/getting-started.md` to create an isolated venv and install from this checkout. Never create or overwrite admin tokens as part of automatic onboarding.
5. For a minimal safe smoke check, run `python scripts/demo_local.py` **after inspecting that script**. It uses a temporary local database and distinct creator, worker and verifier, with no network side effects.
6. To use Shards skills in a local Codex, Cursor or Claude Code project, consult [skill distribution](../../docs/skills-distribution.md). Preview with `python scripts/skill_install.py --client codex --project-dir . --skill get-started` from the Shards source checkout and require explicit approval before `--apply`. Copied skills outside the checkout require access to the Shards repository to run project-level commands.
7. Select the next task-specific skill. For CLI/IDE connection use `client-integration`; for scoped credential issuance obtain a human operator and use `agent-onboarding`.

## Verification

Preflight reports explicit PASS/BLOCKED with no secrets. Skill catalog validates. Optional local demo returns `ok: true`, `audit_valid: true`, three distinct identities and `external_actions_executed: false`. Capture actual process exit codes. Do not claim remote client compatibility based on these tests.

## Failure handling

If a prerequisite or repository document is missing, report BLOCKED and the exact missing path; do not fetch random shell scripts or bootstrap credentials. No remote service needed for the first pass. If demo verification fails, preserve the report and stop before touching production state.

## Output

**Output:** current commit SHA; agent role; selected primary skill; preflight PASS/BLOCKED; catalog validation result; demo result if run; verified capabilities; remaining permissions and next authorised action.
