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

## Verification gate

A positive worker completion enters reported state, not succeeded. Register an independent reviewer with task:verify scope; it must inspect real task evidence and call task_verify with approved=true and verification evidence before success is committed. Rejection marks the task failed. The verifier must not be the worker. The current gateway records attestations and evidence hashes; it does **not** independently prove evidence authenticity or require a cryptographically signed attestation. For consequential workflows, implement actual validators before approval.
