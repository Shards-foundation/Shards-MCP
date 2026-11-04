# Architecture and invariants

MCP/HTTP clients connect to a stateless Python tool endpoint. The application layer validates credentials, schemas and scopes before persisting agent messages, tasks, checkpoints, schedules and audit evidence in SQLite WAL mode.

The gateway coordinates agents; it does not itself run an AI model. Clients are not trusted to provide their own identity or authority. Each running worker acts under its own credential.

## Rules

1. Authenticated actor is derived from the bearer secret.
2. Agents never assign themselves scopes or operator privileges.
3. A sender and idempotency key identify one immutable message.
4. A creator and idempotency key identify one immutable task.
5. Only the assigned worker can claim, renew, checkpoint or complete a task.
6. Worker-reported success requires a distinct authorised verifier before a task enters succeeded state; task verification is separately audited.
7. Expired leases require operator reconciliation instead of automatic replay.
8. Material state changes and corresponding audit entries share transactions.
9. Sensitive credentials are excluded from list and audit results.
10. Unsupported external actions fail closed rather than calling arbitrary upstream tools.

## Review correction notes

- Renewed task leases are audited and capped at two hours from claim.
- Worker completion enters `reported`; a separately authorised principal must verify before success. The bootstrap operator is still privileged and can act as verifier.
- Verification evidence is persisted and its hash included in the audit ledger.
- Audit verification uses a read-only database cursor and requires operator privileges.
- Audit mutation triggers block ordinary UPDATE/DELETE, not a compromised database administrator.
- `message_poll` is cursor-based, unlike the convenience `message_inbox` view.
- `schedule_list` and `schedule_disable` are available; revoked agents are skipped.

## Deliberate limits

This is a **single-host foundation**. SQLite is not a distributed lock manager. No lease fencing tokens, A2A adapter, OAuth resource server, remote MCP tool federation, true snapshots or checkpointed model-process restoration exist yet.

The server implements basic MCP 2025-11-25 JSON-RPC tool discovery and invocation and a simple authenticated REST tool adapter. It does not claim complete protocol implementation, transport compatibility across every client, or 2026-draft compliance.

A future multi-host release must add Postgres, a transactional outbox, fencing tokens, signed delegation, independently anchored audit, asynchronous worker supervisor and fault-injection testing.
