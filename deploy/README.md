# Persistent single-host deployment — operator runbook

This is an **operator-provisioned deployment template**, not a running hosted service or a high-availability architecture. It runs a gateway (MCP/REST/A2A), independent interval scheduler, and Caddy automatic HTTPS ingress. SQLite survives ordinary restarts in the named Docker volume `gateway_data`, but **not** loss of the host or volume.

## Prerequisites

1. Persistent Linux VM with Docker Engine and Docker Compose v2.
2. A real DNS hostname pointed at the VM, with inbound TCP 80/443 for Caddy TLS.
3. A trusted OAuth issuer issuing signed JWT access tokens (correct issuer, subject, audience, scopes and expiry).
4. A protected volume and a separate encrypted **off-host** backup location.
5. Operator-managed IAM, credential rotation, recovery drills and monitoring.

Do not grant trading, wallet, GitHub write or deployment authority until client login, TLS, backup restores and denial tests work.

## Initialise

From the repository root on the target VM:

~~~bash
mkdir -p secrets
chmod 700 secrets
python3 -c 'import pathlib,secrets; p=pathlib.Path("secrets/admin_token"); p.write_text(secrets.token_urlsafe(48)+"\n"); p.chmod(0o600)'
cp deploy/.env.example deploy/.env
~~~

Edit `deploy/.env` with the **real** hostname and OAuth issuer/JWKS URL. Never commit the populated .env or the admin secret. Keep the operator credential in a separate secure recovery store.

~~~bash
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
~~~

Only Caddy publishes 80/443; gateway/scheduler stay on the container network. The gateway runs in OAuth-only remote mode and does not accept local bearer credentials for network access. Check:

~~~bash
curl -fsS https://YOUR_REAL_DOMAIN/health/ready
curl -fsS https://YOUR_REAL_DOMAIN/.well-known/oauth-protected-resource
~~~

Readiness 200 does **not** prove OAuth login, JWKS rotation, token refresh or client compatibility. Test real allowed and forbidden MCP tools from the intended client.

## Scheduler and recovery

One `shards-scheduler` process polls every 30 seconds, dispatches interval schedules and marks expired leases `blocked`. It **never blindly retries** uncertain external actions; an operator must reconcile side effects. It is not a cron expression engine or a multi-host leader.

The admin CLI uses the SQLite online backup API, creates an exclusive 0600 file, and verifies integrity and audit before success.

~~~bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T gateway mkdir -m 700 /data/backups
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T gateway shards-mcp-admin backup --output /data/backups/state-2026-11-04.sqlite
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T gateway shards-mcp-admin verify-snapshot --input /data/backups/state-2026-11-04.sqlite
~~~

**The backup is initially on the same volume**. Copy it immediately to off-host encrypted storage and rehearse restoring a copy to a disposable volume. Never replace a running DB; stop gateway and scheduler, validate backup hash/schema and restore offline. Database recovery cannot reverse deployments, transfers, trades or other agent side effects. There is no automated disaster-recovery service yet.

## Observability

- `/health/live`: process liveness.
- `/health/ready`: SQLite read health, not end-to-end identity-provider health.
- `/metrics`: Prometheus metrics, operator credential and loopback only; Caddy denies the route publicly.
- Structured access logs contain only request ID, fixed route class, status and duration.
- Scheduler logs contain dispatched/blocked counts, never agent payloads.

Local operator-only scrape:

~~~bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T gateway python -c 'import urllib.request; from shards_mcp.config import admin_token_from_environment; req=urllib.request.Request("http://127.0.0.1:8787/metrics",headers={"Authorization":"Bearer "+admin_token_from_environment()}); print(urllib.request.urlopen(req,timeout=3).read().decode())'
~~~

Metrics reset on restart. Export to independent monitored storage for historical tracking and alerting; the stack does not include a production alert manager, trace collector or defined SLO.

## Upgrades and rollback

Back up and verify state before upgrading. Revert code only if database schemas are compatible. Treat database restore as a separate offline operation with a rehearsal, not a simple Docker rollback. This single-host stack has no multi-node lease fencing or failover.

## Why not Render Free?

Render Free web services have ephemeral storage and can spin down after 15 minutes of idle time. Free services cannot attach persistent disks, so SQLite task state and audits would be lost on redeploy, restart or spin-down. See https://render.com/docs/free.
