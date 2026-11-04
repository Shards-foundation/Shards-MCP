# Operations and recovery (development deployment only)

Environment:
- SHARDS_ADMIN_TOKEN: required high-entropy admin credential >=32 characters.
- SHARDS_DB: path to persistent SQLite database (default shards.db).
- SHARDS_BIND: local listener address (default 127.0.0.1).
- SHARDS_PORT: port (default 8787).
- SHARDS_ALLOWED_ORIGINS: comma-separated Origin allowlist (default empty).
- SHARDS_ALLOW_REMOTE=1: explicitly permit non-loopback binding; **does not enable TLS or OAuth**.

GET /health/live checks process liveness. GET /health/ready checks a database transaction. Neither proves external integrations are healthy.

This version exposes an interval scheduler, not a cron-expression parser. A trusted authenticated operator must trigger schedule_tick periodically via an external scheduler. An overdue interval coalesces missed intervals into one dispatched task.

After crash or outage, run task_scan_expired. Inspect downstream effects, then requeue blocked tasks only using task_reconcile with explicit evidence. A SQLite backup should be created through the backup API, encrypted and restored in a test environment regularly.

Keep the database on persistent protected storage. Do not bind the container directly to a public address without an independent security gateway.

## Review operational controls

Use `message_poll` to paginate all pending messages, `message_ack` after processing and `schedule_disable` to stop recurring tasks. Fetch verification evidence using `verification_get` with task-read authority.

The bootstrap admin token requires at least 32 characters and 12 distinct characters; generate it securely. Container remote binding requires explicit `SHARDS_ALLOW_REMOTE=1`; CI builds the container and checks that startup without this opt-in fails for the specifically expected remote-bind security reason; this is not a full runtime deployment test. An HTTPS reverse proxy and OAuth are still necessary for remote integrations.

The image base digest is pinned and must be refreshed for security updates. Current CI does not publish a signed image or independent vulnerability attestation.

## Verification gate

A positive worker completion enters reported state, not succeeded. Register an independent reviewer with task:verify scope; it must inspect real task evidence and call task_verify with approved=true and verification evidence before success is committed. Rejection marks the task failed. The verifier must be neither the worker nor the task creator. The privileged bootstrap operator can verify tasks created by other agents, not its own tasks. The current gateway records attestations and evidence hashes; it does **not** independently prove evidence authenticity or require a cryptographically signed attestation. For consequential workflows, implement actual validators before approval.
