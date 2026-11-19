# Python gateway: operator-assigned verifier and control-domain gate

**Scope:** experimental self-hosted Python/SQLite gateway only. This change does not alter
Cloudflare Edge/D1, production endpoints, OAuth identity assurance, external agent
runtimes, or Shards-Kernel permits. **Identity separation is not proof of independent
humans or independent evidence.**

## New policy

A separate `task:verify` scope is necessary but **no longer sufficient** to
approve a reported task. A verification may commit only if:

1. The task is in `reported` state and the caller is an active agent holding
   `task:verify` (the bootstrap operator cannot act as the reviewer).
2. The out-of-band operator explicitly assigned the **exact** verifier agent ID
   to the **exact** task ID. No wildcard or inferred reviewer is supported.
3. The verifier is neither the task creator nor the task worker.
4. The operator has classified creator, worker and reviewer into named
   control domains. The verifier domain must differ from both creator and
   worker domains. The creator and worker may share a domain. An operator or
   scheduler-created task is placed in the reserved operator domain.
5. These conditions are rechecked **inside the same SQLite write transaction**
   that commits the verified state and audit record. Changed controller
   classifications or revoked verifiers invalidate earlier assignments.

Policy administration is a **local operator CLI**, not an MCP, REST or A2A tool.
New assignments, domain changes and unassignments are recorded in the audit
hash chain. Repeat assignments and repeated unassignments are idempotent.
Existing accepted tasks and verification evidence are not rewritten.

## Breaking upgrade boundary

Existing databases automatically acquire empty `agent_control_domains` and
`verifier_assignments` tables on startup. Existing `reported` tasks will
**remain reported** until the operator classifies the relevant identities and
pins a verifier. No verifier is automatically grandfathered into approval.
Run a verified database backup before upgrade, inventory currently reported
tasks, record the identity/controller evidence **outside** the gateway, and
provision one task at a time. Do not import synthetic test group labels into
production. If a review cannot be performed independently, retain the task
in `reported` and report BLOCKED.

With your existing `SHARDS_DB` and **either** `SHARDS_ADMIN_TOKEN` or
`SHARDS_ADMIN_TOKEN_FILE` configured in a protected operator shell:

```bash
shards-mcp-admin list
shards-mcp-admin controller-list
shards-mcp-admin verifier-list

CREATOR_ID="agt_REPLACE_WITH_CREATOR_ID"
WORKER_ID="agt_REPLACE_WITH_WORKER_ID"
VERIFIER_ID="agt_REPLACE_WITH_VERIFIER_ID"
TASK_ID="tsk_REPLACE_WITH_REPORTED_TASK_ID"

shards-mcp-admin controller-set --agent-id "$CREATOR_ID" --domain creator-control-a
shards-mcp-admin controller-set --agent-id "$WORKER_ID" --domain worker-control-b
shards-mcp-admin controller-set --agent-id "$VERIFIER_ID" --domain reviewer-control-c
shards-mcp-admin verifier-assign --task-id "$TASK_ID" --verifier "$VERIFIER_ID"
shards-mcp-admin verifier-list
```

Replace **every** example value with an actual ID, and choose domains from a
verified external ownership/controller inventory. A domain is an **operator
assertion**, not an ownership attestation. Do not share the bootstrap secret
with agents or paste it into prompts.

To revoke the assignment of a task that has not yet reached a terminal state:

```bash
shards-mcp-admin verifier-unassign --task-id "$TASK_ID"
```

Reassignment requires explicit unassign followed by a new grant. It does
**not** undo a prior success, failure, real-world effect or external payment.
To contain a compromised reviewer, revoke its credential, remove pending
assignments, investigate any signed-off results and reconcile downstream
effects separately. Control-domain changes are audited and immediately
invalidate incompatible pending assignments.

## What is and is not established

**Established by implementation and source tests:** operator-bound assignment,
controller-label separation, fail-closed missing/revoked/mismatched reviewer,
serialised task transition, restart persistence and snapshot table presence.

**Not established:** actual humans are independent, cloud accounts belong to
different organisations, operator classifications are truthful, evidence is
authentic, agents cannot obey malicious instructions, data is tamperproof, or
external effects have been checked. This is a policy assertion layer, **not**
a hardware-backed identity provider, external approval oracle or execution
permit. Compromise of the bootstrap operator or database owner remains a
fundamental trust-boundary risk.

## Acceptance evidence

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_verifier_policy.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_core.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_a2a.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_snapshots.py' -v
```

The negative suite covers absent assignment, same control domain, inactive
reviewer, missing control group, unscoped reviewer, wrong assigned ID, explicit
reassignment, concurrent attempts, legacy migration, audit and backup. CI
checks require the exact PR head. A test pass does not establish deployment.
