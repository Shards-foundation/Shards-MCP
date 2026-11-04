# Architecture and invariants

MCP/HTTP clients connect to a stateless Python tool endpoint. The application layer validates credentials, schemas and scopes before persisting agent messages, tasks, checkpoints, schedules and audit evidence in SQLite WAL mode.

The gateway coordinates agents; it does not itself run an AI model. Clients are not trusted to provide their own identity or authority. Each running worker acts under its own credential.

## Rules

1. Authenticated actor is derived from the bearer secret.
2. Agents never assign themselves scopes or operator privileges.
3. A sender and idempotency key identify one immutable message.
4. A creator and idempotency key identify one immutable task.
5. Only the assigned worker can claim, renew, checkpoint or complete a task.
6. Completed tasks must have had a valid lease.
7. Expired leases require operator reconciliation instead of automatic replay.
8. Material state changes and corresponding audit entries share transactions.
9. Sensitive credentials are excluded from list and audit results.
10. Unsupported external actions fail closed rather than calling arbitrary upstream tools.

## Deliberate limits

This is a **single-host foundation**. SQLite is not a distributed lock manager. No lease fencing tokens, A2A adapter, OAuth resource server, remote MCP tool federation, true snapshots or checkpointed model-process restoration exist yet.

The server implements basic MCP 2025-11-25 JSON-RPC tool discovery and invocation and a simple authenticated REST tool adapter. It does not claim complete protocol implementation, transport compatibility across every client, or 2026-draft compliance.

A future multi-host release must add Postgres, a transactional outbox, fencing tokens, signed delegation, independently anchored audit, asynchronous worker supervisor and fault-injection testing.
