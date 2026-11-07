# Shards-MCP Cookbook — repeatable safe recipes

These recipes operate on a **local test gateway only** unless explicitly identified as read-only for HTTPS. Replace example IDs with actual IDs; use separate least-privilege tokens. Never copy production secrets into shell history, issues or model prompts.

## Recipe A — enrol and verify a read-only agent

Operator on gateway host:

```bash
shards-mcp-admin register --name doctor --provider cli \
  --scope agent:read \
  --token-file "$HOME/.config/shards/doctor.token"
shards-mcp-doctor --url http://127.0.0.1:8787 \
  --token-file "$HOME/.config/shards/doctor.token" --protocol both --json
```

Success: read-only identity displayed; no task modifications. If agent registration refuses a pre-existing file, **do not overwrite**; choose a new protected path.

## Recipe B — create and process one deterministic task

1. Register **creator** (`task:create` + `task:read`), **worker** (`agent:heartbeat` + `task:read` + `task:claim` + `task:update` + `checkpoint:write`) and **verifier** (`task:verify` + `task:read`) using the host CLI.
2. The operator stores each credential in a different permission-restricted file and knows the worker's returned `agent_id`.
3. Creator submits via authenticated REST with its own credential (example variables must be set in a protected interactive shell):

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $SHARDS_CREATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"assignee":"WORKER_AGENT_ID","payload":{"action":"echo","data":"hello"},"idempotency_key":"local-demo-001"}' \
  http://127.0.0.1:8787/v1/tools/task_create
```

4. Worker process uses only `SHARDS_AGENT_TOKEN` (the worker's token) and `SHARDS_GATEWAY_URL`:

```bash
shards-worker --once
```

5. Creator or verifier reads `task_get` by returned task ID. A successful worker result is only `reported`.
6. Verifier **independently inspects** the output and calls `task_verify` with non-empty meaningful evidence, such as a reviewed expected/actual output digest. Until then do not claim `succeeded`.

## Recipe C — diagnose without mutation

```bash
shards-mcp-doctor --protocol legacy --token-file "$HOME/.config/shards/doctor.token" --json
shards-mcp-doctor --protocol modern --token-file "$HOME/.config/shards/doctor.token" --json
```

Do not replace a failing modern check with silent legacy success. Record server identity, scope differences and redacted latency.

## Recipe D — preserve a portable backup

```bash
mkdir -m 700 "$HOME/.config/shards/backups"
shards-mcp-admin backup --output "$HOME/.config/shards/backups/demo.sqlite"
shards-mcp-admin verify-snapshot --input "$HOME/.config/shards/backups/demo.sqlite"
```

The backup command requires the gateway's **real** operator-admin configuration; each output filename must be new. A local snapshot is not disaster recovery. Transfer encrypted off-host via your approved process and rehearse an offline restore.

## Recipe E — handle expired work

Run `shards-scheduler --once` (operator-only) to quarantine expired leases. Inspect downstream effects and review task audit/checkpoints. Only call `task_reconcile` when evidence supports `external_effects_checked=true`. Do **not** auto-retry an uncertain external trade, deployment or payment. If evidence is inconclusive, leave task blocked.

## Recipe F — revoke compromised identity

```bash
shards-mcp-admin revoke ACTUAL_AGENT_ID
```

Test old token denied; replace connector configuration, investigate data exposure and record audit. Never remove database rows to hide a compromise.

See [skills](../skills/README.md) for operator checklists, [demo](demo.md) for a self-contained test and [spec](specification.md) for supported contracts.
