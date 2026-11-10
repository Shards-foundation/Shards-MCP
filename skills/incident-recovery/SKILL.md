---
name: incident-recovery
description: Contain credential, task-lease and data-integrity incidents without replaying uncertain external actions.
---
# Incident and Recovery

**Trigger:** suspected credential theft, expired lease, failed integrity check, outage or unintended action.

1. **Classify:** record UTC time, impacted components/agents and affected asset. Redact secrets/personal data.
2. **Contain:** stop consequential integrations, revoke compromised agent via host-only admin CLI, restrict ingress as needed. Preserve audit/host logs and task state.
3. **Investigate:** inspect latest checkpoint, task status, external system of record, access trail and audit-chain verify result. **Never** infer absence of external side effects from a timeout.
4. **Recover:** for blocked task, document effects_checked proof before `task_reconcile`. For storage issue, verify a protected SQLite snapshot and restore only **offline** to a disposable environment before any production restore.
5. **Validate:** read-only diagnostic, denied old token, audit validity, repaired owner boundaries and known task state. Restart one scheduler only.
6. **Escalate:** controller/operator must assess applicable notification duties and contractual timelines; agent cannot make legal breach determination unilaterally.
7. **Output:** incident ID, evidence timestamps, containment, affected IDs, restore proof/RTO where measured, remaining uncertainty, operator signoff. Unknown external effects -> NO-GO for replay.
