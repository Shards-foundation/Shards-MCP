# Reusable Agent and Operator Skills

A **skill** is a documented repeatable workflow with a trigger, input contract, safe actions, verification, failure handling and output evidence. It is not a hidden agent permission, an automation scheduler or a substitute for a security policy.

| Skill | Trigger | Output |
| --- | --- | --- |
| [agent-onboarding](agent-onboarding/SKILL.md) | New or rotating agent identity | Enrolment + denial-test receipt |
| [connection-doctor](connection-doctor/SKILL.md) | Client/IDE connectivity failure | Scoped read-only diagnostics |
| [task-lifecycle](task-lifecycle/SKILL.md) | Delegate/verify non-consequential work | Task state and review evidence |
| [security-review](security-review/SKILL.md) | PR/auth boundary/incident audit | Finding severity, proof, acceptance |
| [incident-recovery](incident-recovery/SKILL.md) | Expired lease, compromised credential or outage | Containment and recovery decision |
| [release-readiness](release-readiness/SKILL.md) | Package release or hosted deployment request | Binary GO/NO-GO with references |

## Skill execution contract

Read [AGENTS.md](../AGENTS.md) and [rulebook](../docs/rulebook.md). Check that input data has no secrets, confirm the operator's approval and current git SHA, execute only commands in scope, record negative as well as positive tests, fail closed on missing evidence. Skills cannot create credentials, publish a package or perform state changes without the actor's existing authority.

These Markdown skills are compatible with agents that read `SKILL.md` workflows; no claim is made that the repository automatically installs them as ChatGPT plugins or grants external tool permissions.
