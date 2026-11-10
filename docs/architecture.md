# Architecture and Safety Invariants

**Document scope:** v0.1.x codebase as of 7 November 2026. Technical contract: [specification](specification.md). Risk register: [threat model](threat-model.md).

## Logical architecture

```text
Local IDE/agent -> stdio bridge ----\
Local HTTP/REST/MCP client ----------> Python gateway -> SQLite WAL
Remote OAuth MCP/A2A via HTTPS -----/      |             |
           external JWT issuer              |           audit ledger
                                             +-- scoped task/message/event dispatch
                                             +-- optional A2A text adapter
One local scheduler --------------------------> schedule tick / lease quarantine
Independent reference worker ---------------> scoped task claim/checkpoint/report
Separate independent verifier --------------> task attest (reported -> succeeded)
Optional NextAuth preview console ----------> login and read-only health only
```

## Invariants

1. All actor identity comes from authenticated bearer or signed JWT; request bodies never grant identity or scopes.
2. Local agent enrolment/revocation is host-only; operator token is never delegated to LLMs.
3. Messages/tasks/events use sender-owned idempotency keys; same key with changed payload is a conflict.
4. Assigned worker is the only principal that claims, renews, checkpoints or completes its task.
5. `task_claim_next` selects and leases a queued task in one SQLite transaction; `task_cancel` cannot beat a successful claim.
6. A worker completion with `success=true` enters `reported`, not `succeeded`. Verifier is neither creator nor worker and provides meaningful evidence.
7. Expired/uncertain work is blocked pending explicit external side-effect reconciliation.
8. State changes and audit entries share a transaction; read-only audit verification cannot prove resistance to a malicious DB administrator.
9. Credentials never appear in tool lists/audit responses. Payloads remain untrusted.
10. The reference worker never executes arbitrary commands, web requests, wallet operations or model inference.
11. Off-host binding requires explicit `SHARDS_ALLOW_REMOTE=1` **and** `SHARDS_AUTH_MODE=oauth`, plus an HTTPS ingress at the deployment layer.
12. No multi-host fencing, automatic disaster recovery, app-level quota enforcement or tenant-wide RBAC is implied.

## Interfaces

The gateway serves MCP 2025-11-25 and MCP 2026-07-28 **tool-only** subsets at `POST /mcp`; scoped REST tools at `GET /v1/tools` and `POST /v1/tools/{name}`; and an opt-in constrained A2A v1.0 adapter for per-agent authenticated cards, text task delegation and unclaimed cancellation. It exposes liveness and readiness checks; operator-only metrics are loopback restricted.

Local worker and scheduler are **distinct processes**, not a built-in 24/7 model. A Next.js allowlisted operations shell is included but does not have persistent organisations, agent/task mutations or ChatGPT login.

## Persistence and recovery

SQLite WAL on a single host serialises writes and keeps durable state across ordinary restarts. Lease expiry does not rewind a third-party effect, and saved checkpoints are **metadata**, not model execution snapshots. Use host-local snapshots, independently protected off-host copies and restore drills; only one scheduler should run.

## Deferred architecture

Postgres transaction/outbox, multi-host leader election and fencing, zero-trust tenant IAM, independent audit anchoring, rate quotas, observability/alerts, full A2A and MCP optional features, hosted operational contracts and external-effect approvals are tracked as **future**, not current features.

For executable tests and gates see [acceptance evidence](acceptance-evidence.md), [releasing](releasing.md), [rulebook](rulebook.md).
