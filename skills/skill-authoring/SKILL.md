---
name: skill-authoring
description: Design, write, test and safely register a new repeatable Shards skill following the Agent Skills specification. Use when adding workflows, scripts, playbooks, reference documents, or extending the skills catalog and agent onboarding instructions.
---
# Skill authoring — make the next run cheaper and safer

**Trigger:** new operating procedure or repeated task needs to become a reusable, verifiable agent skill.

## Preconditions

A demonstrated repeated use case; a bounded, identifiable human or agent user; known entry point and expected output; existing skills checked to avoid duplication. Read `AGENTS.md`, `skills/MAP.md` and the published [Agent Skills specification](https://agentskills.io/specification).

## Inputs

Proposed lowercase-hyphen skill ID, precise trigger, permission requirements, supported versions, scope of external effects, inputs, failure cases, safe example and acceptance tests.

## Procedure

1. Define a narrow job-to-be-done; prefer extending a skill to duplicating one.
2. Create `skills/<name>/SKILL.md` with valid YAML frontmatter `name:` and `description:` that matches the folder name. Trigger text must tell the agent **when** to load it; never make a skill always-on solely to increase usage.
3. Provide **Preconditions, Inputs, Procedure, Verification, Failure handling and Output**. Include a clear trigger, pass/fail conditions, actor authority boundaries and negative tests. Use progressive disclosure: concise core instructions, deeper information in relative `references/` files.
4. For scripts use Python standard library where feasible. No network, privileged writes or credential access by default; require explicit opt-in for mutations. Use clear exit codes and redacted JSON output. Add unit tests and explain dependencies.
5. Update `skills/catalog.json`, `skills/MAP.md` and `skills/README.md`. Avoid machine-specific absolute paths. Keep script and document references relative and real.
6. Validate locally:
   ```sh
   python scripts/skillctl.py validate
   python scripts/docs_check.py
   python -m unittest discover -s tests -p 'test_skills.py' -v
   ```
7. Confirm any truly portable helper scripts live inside the selected skill's own `scripts/` directory; source-checkout scripts remain source-dependent. Test the installer with `python -m unittest discover -s tests -p 'test_skill_install.py' -v` against disposable directories, never a real user's home.
8. Test both expected success and denied/missing-precondition outcomes. Open PR with exact evidence, no auto-publication; resolve independent reviewer feedback.

## Verification

Confirm 1–64 character valid skill name, description no more than 1024 characters, directory match, catalog uniqueness, referenced local scripts exist, no secret literals, heading/link checks and repeatable unit tests. Compatible clients must still discover/import skills according to their own configuration.

## Failure handling

Invalid frontmatter, duplicate/missing catalog entry, permission ambiguity, unreviewed external actions or untested script => **BLOCKED**, not "installed". Avoid shell one-liners that execute remote content without inspection.

## Output

**Output:** skill path, catalog entry, workflow trigger, scripts and test evidence, supported runtime, any approvals or undiscovered client limitations.
