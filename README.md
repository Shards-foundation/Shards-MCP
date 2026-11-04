# Shards MCP Gateway

[![CI](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A persistent, authenticated agent-to-agent messaging and task control plane, exposed as an MCP tool server.**

> **Status: v0.1.0 experimental foundation, not production-certified.** Not yet a complete A2A implementation, general ChatGPT plugin, or commercial hosted service. No live infrastructure or wallet execution.

## Implemented

- MCP JSON-RPC 2.0 stateless HTTP at POST /mcp: initialize, ping, tools/list, tools/call.
- Scoped bearer-credential agent registration, agent enumeration, revocation and heartbeat.
- Durable agent-to-agent messaging, idempotency and recipient isolation.
- Assigned tasks with leases, checkpoint persistence and conservative failure recovery.
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

The service binds to 127.0.0.1:8787 by default. PowerShell users should set environment variables using the $env: prefix.

## MCP smoke test

~~~bash
curl -sS http://127.0.0.1:8787/mcp \
  -H "Authorization: Bearer $SHARDS_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
~~~

Then issue method tools/list with an empty params object. To register an agent, call tool agent_register with name, provider, capabilities and limited scopes. Save the issued worker token in a secret manager: never expose it in a model prompt or repository. Workers invoke tools with their own credential.

**Do not connect ChatGPT using the administrator token.** Standard remote OAuth support, HTTPS deployment and platform testing are separate release gates.

## Execution and safety model

A sender submits a task with an idempotency key and assignee. Only the assignee may claim that queued task and receive a finite lease. While the lease is valid, the agent can checkpoint, renew and complete its work. When a lease expires, an operator must explicitly mark the task blocked, reconcile any uncertain external effects, and approve requeueing. A saved checkpoint is task metadata, not a running model-process snapshot.

No arbitrary commands, deployments, trades, transfers or external requests are executed by the gateway.

## Documentation

- [Architecture and invariants](docs/architecture.md)
- [Security model](SECURITY.md)
- [Integration requirements](docs/integrations.md)
- [Operations and recovery](docs/operations.md)
- [Release roadmap](docs/roadmap.md)

## Test

~~~bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
~~~

MIT licensed, see [LICENSE](LICENSE).
