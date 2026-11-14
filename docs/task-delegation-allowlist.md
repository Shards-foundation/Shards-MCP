# Python gateway: operator-managed task delegation allowlist

**Scope:** SQLite-backed, single-organisation *Python* gateway. This does not change
Cloudflare Edge/D1, any deployed infrastructure, tenant-v2/Postgres PRs, external
LLM host policy, or Shards-Kernel permits.

## Security invariant

An authenticated principal with `task:create` can create a task for **itself**.
To assign a new task to a *different* active agent, the gateway additionally
requires an exact `(creator_agent_id, assignee_agent_id)` operator-approved
row in `delegation_grants`. No wildcard is accepted. The bootstrap operator
can dispatch administrative work; no agent token can obtain that role.

No approval row means **FORBIDDEN and no task or audit write**. The same check
is applied to MCP/REST `task_create` and A2A `SendMessage` by their common
`Gateway.task_create` path. The allowlist is persistent and is checked inside
the SQLite write transaction, serialised with grant and revoke writes.

Grant/deny/list operations are **local admin CLI only**, require
`SHARDS_ADMIN_TOKEN` in the operator's environment, and are not registered
as MCP, REST or A2A tools. Never share the bootstrap token with a model.

## Upgrade behaviour: deliberate fail-closed change

This changes behaviour from experimental v0.1.x: `task:create` no longer
allows arbitrary cross-agent assignment. Existing persisted tasks, leases and
messages remain intact. Existing installations start with **zero grants** and
new cross-agent task creation will be denied until an operator provisions the
intended pairs. Schedule dispatch by the bootstrap operator is unchanged.

After a source/database backup and an operator inventory, stop agent task
submission temporarily. With the existing environment-based admin secret and
database location configured, find current agent IDs:

```bash
shards-mcp-admin list
shards-mcp-admin delegation-list
CREATOR_AGENT_ID="agt_REPLACE_WITH_CREATOR_ID"
WORKER_AGENT_ID="agt_REPLACE_WITH_WORKER_ID"
shards-mcp-admin delegation-grant --creator "$CREATOR_AGENT_ID" --assignee "$WORKER_AGENT_ID"
shards-mcp-admin delegation-list
```

Replace both example variable values with the **real IDs** printed by `list` before running a grant. Do not paste the example placeholder IDs unchanged.
Then resume task submission and verify one allowed and one denied assignment.
To block future cross-agent assignment:

```bash
shards-mcp-admin delegation-revoke --creator "$CREATOR_AGENT_ID" --assignee "$WORKER_AGENT_ID"
```

Both changes are hash-chain audited in the same transaction as the policy
mutation. A duplicate grant is idempotent and makes no extra audit entry. A
repeated revoke is likewise idempotent. For safety, policy revocation stops
**new** tasks, not previously accepted tasks or already running external
effects. The creator can still repeat an identical idempotency key for an
existing task after a policy change; a changed payload with the same key is
rejected with `CONFLICT`. Emergency stop requires separate worker/tool
revocation, cancellation where safe, and external-effect reconciliation.

## What this does not establish

This is a destination-level authorization control, **not** an independent
human approval, task-class/schema authorization, per-creator rate ceiling,
message-send recipient allowlist, prompt-injection defence, multi-tenant
isolation, verifier independence or a deterministic external-effect permit.
A custom model/tool runtime must independently enforce those downstream
policies. The `task:verify` control still requires a distinct agent ID, not
a proven independent person/controller or authoritative evidence.

## Acceptance / evidence

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_delegation_acl.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_a2a.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_core.py' -v
```

The dedicated regression tests cover default deny, exact grant, wrong target,
idempotent retry, revocation, restart persistence, audit attribution, local
operator-only CLI, absence of remote grant tools, and A2A denial. A passing
source test is not evidence of deployed policy, operator MFA or live effects.
