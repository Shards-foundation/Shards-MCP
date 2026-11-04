# Shards MCP Gateway

[![CI](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A persistent, authenticated agent-to-agent messaging and task control plane, exposed as an MCP tool server.**

> **Status: v0.1.0 experimental foundation, not production-certified.** Not yet a complete A2A implementation, general ChatGPT plugin, or commercial hosted service. No live infrastructure or wallet execution.

## Implemented

- Durable operational events with topic filters and monotonic cursor polling, separate from security audit entries.
- Agent-private event topics `agent.<agent_id>.<topic>`, untrusted shared broadcasts `shared.<topic>`, and operator-only `system.*` topics; audit queries scoped to the authenticated actor.

- MCP stdio bridge for compatible local AI runtimes, forwarding to the authenticated HTTP server.
- MCP JSON-RPC 2.0 stateless HTTP at POST /mcp: initialize, ping, tools/list, tools/call. Authenticated generic HTTP clients may instead invoke POST /v1/tools/{name} with JSON arguments, or discover GET /v1/tools.
- Scoped bearer-credential agent registration, agent enumeration, revocation and heartbeat.
- Durable agent-to-agent messaging, idempotency and recipient isolation.
- Assigned tasks with leases, checkpoint persistence, conservative failure recovery and independent task verification gate.
- SQLite-backed transactionally appended audit hash chain and verification tool.
- Interval task schedules dispatched by explicit schedule_tick calls.
- Local readiness and liveness endpoints; Python standard library runtime; automated tests.

**Not yet implemented:** OAuth 2.1 resource-server flow, A2A protocol, remote tool federation, streaming events, advanced rate limiting, high-availability database, independent audit anchoring, production observability, distributed cron, automatic snapshots/rollback, native dashboard, ChatGPT Apps SDK UI, external service integrations.

## Run locally

Python 3.11+ required.

~~~bash
git clone https://github.com/Shards-foundation/Shards-MCP.git
cd Shards-MCP
python -m pip install -e .
export SHARDS_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export SHARDS_DB="./shards.db"
shards-mcp
~~~

The bootstrap secret must be randomly generated (at least 32 characters and 12 distinct characters; these checks alone do not prove cryptographic entropy). The service binds to 127.0.0.1:8787 by default. PowerShell users should set environment variables using the $env: prefix.

## Provision agent credentials locally (never through MCP tools)

Run on the gateway host as the operator, with `SHARDS_ADMIN_TOKEN` and `SHARDS_DB` configured as above:

~~~bash
mkdir -p "$HOME/.config/shards"
chmod 700 "$HOME/.config/shards"
shards-mcp-admin register --name hermes --provider local \
  --scope agent:heartbeat --scope agent:read \
  --scope task:read --scope task:claim --scope task:update \
  --scope checkpoint:write --token-file "$HOME/.config/shards/hermes.token"
export SHARDS_AGENT_TOKEN="$(cat "$HOME/.config/shards/hermes.token")"
~~~

`shards-mcp-admin` prints only the new agent ID and the token file location. The token file is created with permission `0600`; registration refuses an existing file. To revoke a credential, run `shards-mcp-admin revoke <agent_id>`. These operations are **not** available as network tools. Supply each AI client with only its scoped agent token using the client's secret configuration mechanism; never copy the bootstrap token into a model transcript.

## MCP smoke test

~~~bash
curl -sS http://127.0.0.1:8787/mcp \
  -H "Authorization: Bearer $SHARDS_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
~~~

Then issue method `tools/list` with an empty `params` object. Tool discovery is filtered by the authenticated agent scopes. Agent creation and revocation are deliberately not exposed through MCP or REST; use `shards-mcp-admin` on the host.

**Do not connect ChatGPT using the administrator token.** Standard remote OAuth support, HTTPS deployment and platform testing are separate release gates.

### Reference worker (safe deterministic operations)

The package also installs the shards-worker command. Register a worker agent with scopes agent:heartbeat, task:read, task:claim, task:update and checkpoint:write. Export its issued token as SHARDS_AGENT_TOKEN and set SHARDS_GATEWAY_URL to the gateway base URL. Then run shards-worker --once for one poll cycle or shards-worker for continuous polling.

Supported example tasks have an input JSON object with action set to echo, sha256 or health. The worker will never execute arbitrary shell commands or external service actions. If a worker is interrupted, an operator must reconcile the expired task lease before retry.

## Local stdio MCP bridge

For Claude Desktop and other environments supporting stdio MCP clients, run shards-mcp-stdio as a local process with SHARDS_GATEWAY_URL pointing to the running service and SHARDS_AGENT_TOKEN containing a **least-privileged agent token**. The bridge forwards newline-delimited MCP JSON-RPC messages to the shared authenticated HTTP gateway. It does not use administrator credentials and does not bypass policy checks. Local stdio MCP support is separate from ChatGPT's hosted remote MCP connection requirements.

## Independent review hardening

The review-driven pass added finite two-hour claim lifetimes with audited renewals, persisted verifier attestations, read-only authentication, strict HTTP input handling, bounded connection concurrency, append-only audit triggers, privileged audit verification, permission-filtered tool discovery, cursor-based message polling and stoppable schedules.

Use `message_poll` with `after_seq` for reliable delivery; `message_inbox` is a convenience view, not a cursor. Use `message_ack` after processing each message. Schedules no longer dispatch to revoked agents.

The verification state `succeeded` means an authorised principal other than both task creator and worker has attested a result using `task:verify`. This does not guarantee evidence authenticity. The bootstrap operator may verify tasks created by other principals but cannot verify tasks it created itself. Never expose the bootstrap credential to an AI client.

## Execution and safety model

A sender submits a task with an idempotency key and assignee. Only the assignee may claim that queued task and receive a finite lease. While the lease is valid, the agent can checkpoint, renew and report its result. **A worker's positive completion does not establish verified success**: it enters reported state until a separately authorised reviewer uses task_verify with verification evidence. The worker's own credentials cannot self-verify. When a lease expires, an operator must explicitly mark the task blocked, reconcile any uncertain external effects, and approve requeueing. A saved checkpoint is task metadata, not a running model-process snapshot.

No arbitrary commands, deployments, trades, transfers or external requests are executed by the gateway.

## Documentation

- [Architecture and invariants](docs/architecture.md)
- [Security model](SECURITY.md)
- [Integration requirements](docs/integrations.md)
- [Operations and recovery](docs/operations.md)
- [Release roadmap](docs/roadmap.md)
- [Portable plugin manifests and installation](docs/plugin-packaging.md)

## Test

~~~bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
~~~

MIT licensed, see [LICENSE](LICENSE).
