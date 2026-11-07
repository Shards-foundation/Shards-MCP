# Operations and recovery (development deployment only)

Environment:
- SHARDS_ADMIN_TOKEN: required high-entropy admin credential >=32 characters.
- SHARDS_DB: path to persistent SQLite database (default shards.db).
- SHARDS_BIND: local listener address (default 127.0.0.1).
- SHARDS_PORT: port (default 8787).
- SHARDS_ALLOWED_ORIGINS: comma-separated Origin allowlist (default empty).
- SHARDS_ALLOW_REMOTE=1: explicitly permit non-loopback binding; **does not enable TLS or OAuth**.

GET /health/live checks process liveness. GET /health/ready checks a database transaction. Neither proves external integrations are healthy.

Workers with both `task:read` and `task:claim` scopes may use `task_claim_next` to atomically obtain the next assigned queued task and a 15–3600-second lease in one request. This replaces the reference worker's separate inbox-read and claim calls. The response is `{"claimed": false, "task": null}` if its queue is empty, without an audit mutation; otherwise it returns the claimed task input, task ID, current lease deadline and attempt counter. Concurrent workers are serialized by SQLite's `BEGIN IMMEDIATE` so each queued task is claimed once. Cancellation and claim cannot both succeed. **This does not guarantee exactly-once external effects**: after a crash/expired lease the task is blocked for explicit reconciliation, not automatically replayed. The server is still single-host SQLite, not a distributed job broker.

The gateway implements interval schedules (not cron expressions). Use the new `shards-scheduler` process for continuous single-host dispatch and expired-lease quarantine, or call `schedule_tick` explicitly from a trusted local operator. An overdue interval coalesces missed intervals into one task. Do not run multiple independent schedulers without distributed leader election.

After crash or outage, the scheduler or operator runs `task_scan_expired`. Inspect downstream effects and requeue blocked tasks only with `task_reconcile` plus explicit evidence. `shards-mcp-admin backup --output NEW_FILE` uses the SQLite backup API, verifies SQLite integrity and the local audit chain, and logs a successful snapshot; `verify-snapshot --input FILE` works offline. Keep snapshots encrypted off-host and rehearse restores. See [persistent deployment runbook](../deploy/README.md).

Keep the database on persistent protected storage. Do not bind the container directly to a public address without an independent security gateway.

## Remote OAuth configuration

Set `SHARDS_AUTH_MODE=oauth`, `SHARDS_OAUTH_ISSUER`, `SHARDS_OAUTH_JWKS_URI`, `SHARDS_PUBLIC_URL=https://YOUR_HOST/mcp`, `SHARDS_BIND=0.0.0.0` and `SHARDS_ALLOW_REMOTE=1`. Install `shards-mcp[oauth]`. The OAuth server validates issuer, audience, signature, expiry and scopes, and maps the signed subject to an operator-enrolled agent. Local bearer tokens cannot authenticate in OAuth mode. The HTTP listener still requires an HTTPS reverse proxy, storage protection, backups and network-level rate limiting. This does not provide an OAuth authorisation server or automatic refresh tokens.

## Review operational controls

Use `message_poll` to paginate all pending messages, `message_ack` after processing and `schedule_disable` to stop recurring tasks. Fetch verification evidence using `verification_get` with task-read authority.

The bootstrap admin token requires at least 32 characters and 12 distinct characters; generate it securely. Container remote binding requires explicit `SHARDS_ALLOW_REMOTE=1`; CI builds the container and checks that startup without this opt-in fails for the specifically expected remote-bind security reason; this is not a full runtime deployment test. An HTTPS reverse proxy and OAuth are still necessary for remote integrations.

The image base digest is pinned and must be refreshed for security updates. Current CI does not publish a signed image or independent vulnerability attestation.

## Verification gate

A positive worker completion enters reported state, not succeeded. Register an independent reviewer with task:verify scope; it must inspect real task evidence and call task_verify with approved=true and verification evidence before success is committed. Rejection marks the task failed. The verifier must be neither the worker nor the task creator. The privileged bootstrap operator can verify tasks created by other agents, not its own tasks. The current gateway records attestations and evidence hashes; it does **not** independently prove evidence authenticity or require a cryptographically signed attestation. For consequential workflows, implement actual validators before approval.
