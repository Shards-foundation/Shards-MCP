# Shards skills map — governed workflow router

This map is the human-readable interface to the machine-validated [skills catalog](catalog.json). Agents read [AGENTS.md](../AGENTS.md) for top-level instructions and load only the matching `SKILL.md` body. The map does not grant additional access or install plugins.

## Discover and retrieve

```sh
python scripts/skillctl.py list
python scripts/skillctl.py list --json
python scripts/skillctl.py suggest --task "I need to connect Claude Code"
python scripts/skillctl.py show client-integration
python scripts/skillctl.py validate
```

`show` emits the exact on-disk skill instructions; `suggest` is a **lexical hint**, not a model decision or authorization. When no unambiguous match exists, read this table and choose manually. All commands are read-only. A supported external agent must have repository/file access and permission to run local Python; otherwise it should retrieve the Markdown over the repository's authenticated GitHub reader.

## Routing table

| Need / trigger | Primary skill | Risk | Script or deliverable |
| --- | --- | --- | --- |
| Fresh contributor or AI worker, first local run | [get-started](get-started/SKILL.md) | Low | `skills/get-started/scripts/preflight.py` |
| Enrol or rotate a scoped gateway identity | [agent-onboarding](agent-onboarding/SKILL.md) | Privileged | Host-local admin CLI, denial receipt |
| Connect Claude, ChatGPT, Codex, Cursor, other MCP client | [client-integration](client-integration/SKILL.md) | Bounded | Transport configuration and auth verification |
| Investigate handshake, transport, scope mismatch | [connection-doctor](connection-doctor/SKILL.md) | Low | `shards-mcp-doctor` output |
| Assign, claim, checkpoint, independently verify work | [task-lifecycle](task-lifecycle/SKILL.md) | Bounded | `scripts/demo_local.py` and task audit |
| Diagnose broken GitHub Actions or failing tests | [ci-triage](ci-triage/SKILL.md) | Low | Pinpoint failing step and regression |
| Audit auth, tenant boundaries, secrets and parser changes | [security-review](security-review/SKILL.md) | Bounded | Findings and negative tests |
| Respond to compromised keys, outages and lease uncertainty | [incident-recovery](incident-recovery/SKILL.md) | Privileged | Containment/reconciliation evidence |
| Evaluate package/hosted production release gate | [release-readiness](release-readiness/SKILL.md) | Privileged | `scripts/skill_evidence.py`, NO-GO by default |
| Prepare a marketplace/directory submission | [marketplace-gate](marketplace-gate/SKILL.md) | Privileged | Platform-specific conformance evidence |
| Create a new repeatable Shards workflow | [skill-authoring](skill-authoring/SKILL.md) | Bounded | Catalog update + validation + tests |

**Risk:** Low = inspection and deterministic local checks; Bounded = code changes or scoped test actions with review; Privileged = requires independently authorised credentials and explicit operator approval. A low-risk skill can become privileged if its requested tool operation has external effects.

## Recommended dependency paths

- **First contribution:** `get-started` → `ci-triage` or `skill-authoring` → `security-review` → independent review.
- **New client:** `get-started` → `client-integration` → `connection-doctor`; add `agent-onboarding` only when authorised enrolment is required.
- **Agent execution:** `agent-onboarding` → `task-lifecycle` → `security-review` when task actions cross a trust boundary.
- **Hosted release:** `security-review` → `release-readiness` → `marketplace-gate`, with separate approvals and evidence for each.

## Standard of execution

Each skill must specify **Trigger, Preconditions, Inputs, Procedure, Verification, Failure handling, Output** and an explicit no-go boundary for risky effects. Scripts must be deterministic, non-destructive unless an operator opts in, and must not print secrets. The skill directory follows the [Agent Skills specification](https://agentskills.io/specification), with `name` and `description` frontmatter and optional `scripts/`, `references/`, `assets/`.

The catalog is versioned with the source. Adding, renaming or deleting skills requires updating both this map and `catalog.json`, then running `python scripts/skillctl.py validate` and `python scripts/docs_check.py`.
