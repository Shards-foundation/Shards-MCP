# Shards MCP Gateway

[![CI](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A persistent, authenticated agent-to-agent messaging and task control plane, exposed as an MCP tool server.**

> **Status: v0.1.0 experimental foundation, not production-certified.** Not yet a complete A2A implementation, general ChatGPT plugin, or commercial hosted service. No live infrastructure or wallet execution.

## Implemented

- Durable operational events with topic filters and monotonic cursor polling, separate from security audit entries.
- Agent-private event topics `agent.<agent_id>.<topic>`, untrusted shared broadcasts `shared.<topic>`, and operator-only `system.*` topics; audit queries scoped to the authenticated actor.

- MCP stdio bridge for compatible local AI runtimes, forwarding to the authenticated HTTP server.
- Authenticated `agent_identity` tool for effective principal and scope discovery without exposing credentials.
- MCP JSON-RPC over authenticated `POST /mcp`, with both the legacy `2025-11-25` initialize/ping/tool-server contract and the **2026-07-28 stateless tool subset** (`server/discover`, `tools/list`, `tools/call`, per-request metadata and checked routing headers). The newer contract is not yet a full MCP extensions/subscriptions implementation. Generic HTTP automation may alternatively use `POST /v1/tools/{name}` or discover `GET /v1/tools`.
- Scoped bearer-credential agent registration, agent enumeration, revocation and heartbeat.
- Durable agent-to-agent messaging, idempotency and recipient isolation.
- Assigned tasks with leases, checkpoint persistence, conservative failure recovery and independent task verification gate.
- Atomic cancellation of **unclaimed** queued tasks by their creator or the operator, exposed through MCP/REST and A2A `CancelTask`. Claimed/running work cannot be cancelled safely.
- SQLite-backed transactionally appended audit hash chain and verification tool.
- Durable interval schedules dispatched by explicit ticks or the independent `shards-scheduler` supervisor; expired leases are quarantined.
- Operator-only Prometheus metrics and redacted structured HTTP access logs.
- Local-only consistent SQLite snapshots with integrity/audit verification and recovery rehearsal.
- Optional external OAuth JWT mode and constrained A2A v1.0 agent delegation interface, now including pre-claim `CancelTask` with protocol-specific not-cancelable errors.
- Docker Compose reference stack for persistent single-host deployment with Caddy HTTPS and protected secret files.
- Local readiness and liveness endpoints; Python standard library runtime; automated tests.
- Explicit cross-runtime E2E suite for MCP, stdio, independent worker/reviewer, revocation and gateway restart, gated in CI.

**Not yet implemented:** complete OAuth provider/client-flow interoperability, full A2A conformance, remote tool federation, server-pushed events, production rate limiting/alerting, multi-host Postgres, independent audit anchoring, distributed leader election, interruption/cancellation of running tasks, automatic external-effect rollback, hosted service and ChatGPT Apps SDK UI. The snapshot feature backs up local SQLite state only.

See [interoperability and ChatGPT plugin gates](docs/interoperability.md) for the E2E contract and what still needs external deployment validation.

## Run locally

Python 3.11+ required. Linux GitHub Actions CI tests Python **3.11, 3.12,
3.13, 3.14 and 3.15**, including the complete unit/HTTP suite, official MCP SDK
client, cross-runtime E2E, wheel/sdist build, and a fresh-environment
installation. This does not claim that Windows/macOS, Python 3.16 or every
third-party SDK is tested. Docker and Caddy deployment checks run on Python
3.12 as a representative container baseline.

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

## Verify a connected AI client (read-only)

The `shards-mcp-doctor` command performs a real Streamable HTTP MCP
`initialize` / `notifications/initialized` / `tools/list` / `agent_identity` lifecycle and prints
the authenticated agent ID, effective permission scopes, discovered tool count
and latency. It makes **no writes**, never prints credentials, rejects
administrator identities and refuses non-loopback plaintext or redirects.

With a separately provisioned agent credential:

~~~bash
export SHARDS_GATEWAY_URL=http://127.0.0.1:8787
export SHARDS_AGENT_TOKEN="$(cat "$HOME/.config/shards/hermes.token")"
shards-mcp-doctor --json
~~~

For file-based secret handling (recommended on a shared host), unset
`SHARDS_AGENT_TOKEN` and instead run:

~~~bash
shards-mcp-doctor --token-file "$HOME/.config/shards/hermes.token" --json
~~~

The token file must be a regular, non-symlink file readable only by its
owner on POSIX. An explicitly configured HTTPS gateway may also be checked;
the diagnostic does not perform OAuth login or issue access tokens. A
successful result proves MCP client negotiation and permissions from this
client's current network location, **not** full ChatGPT App Directory
compatibility or a production deployment. Use separate scoped agent tokens
for each AI client and never provide the bootstrap administrator secret.

## MCP smoke test

~~~bash
curl -sS http://127.0.0.1:8787/mcp \
  -H "Authorization: Bearer $SHARDS_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
~~~

Complete the MCP lifecycle before tool discovery:

~~~bash
curl -sS -i http://127.0.0.1:8787/mcp \
  -H "Authorization: Bearer $SHARDS_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-11-25" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
~~~

Then issue method `tools/list` with an empty `params` object. Tool discovery is filtered by the authenticated agent scopes. Agent creation and revocation are deliberately not exposed through MCP or REST; use `shards-mcp-admin` on the host.

**Do not connect ChatGPT using the administrator token.** Standard remote OAuth support, HTTPS deployment and platform testing are separate release gates.

### Reference worker (safe deterministic operations)

The package also installs the shards-worker command. Register a worker agent with scopes agent:heartbeat, task:read, task:claim, task:update and checkpoint:write. Export its issued token as SHARDS_AGENT_TOKEN and set SHARDS_GATEWAY_URL to the gateway base URL. Then run shards-worker --once for one poll cycle or shards-worker for continuous polling.

Supported example tasks have an input JSON object with action set to echo, sha256 or health. The worker will never execute arbitrary shell commands or external service actions. If a worker is interrupted, an operator must reconcile the expired task lease before retry.

## Remote OAuth resource-server mode

The gateway now supports an **optional signed-JWT resource-server mode**, separate from its local bearer-token mode. It is not an OAuth authorisation server. Install `pip install -e '.[oauth]'` and use `shards-mcp-admin register --oauth-subject SUBJECT` to bind the **exact signed OAuth `sub` claim** to a registered Shards identity. Register that identity with only the scopes it needs.

Example operator configuration (placeholder issuer/host, not a deployed endpoint):

~~~bash
export SHARDS_AUTH_MODE=oauth
export SHARDS_OAUTH_ISSUER=https://identity.example.com
export SHARDS_OAUTH_JWKS_URI=https://identity.example.com/jwks.json
export SHARDS_PUBLIC_URL=https://gateway.example.com/mcp
export SHARDS_BIND=0.0.0.0
export SHARDS_ALLOW_REMOTE=1
# SHARDS_ADMIN_TOKEN and SHARDS_DB must also be set securely.
shards-mcp
~~~

The configured identity provider must issue **signed JWT access tokens** with a verified issuer, `sub`, `aud` equal to `SHARDS_PUBLIC_URL`, `iat`, `exp`, and `scope` string containing the authorised gateway scopes. The server accepts RS256 and ES256; the JWKS address is pinned by the operator, never supplied by a token. Access-token scopes are intersected with the enrolled agent's scopes. The bootstrap credential and local worker tokens cannot authenticate to the OAuth network endpoints.

The resource server exposes RFC 9728 metadata under `/.well-known/oauth-protected-resource` and adds a `resource_metadata` URL to HTTP 401 challenges.

**Remote access requires a TLS reverse proxy and a compatible external OAuth provider.** Token issuance, consent/PKCE, refresh tokens and provider-specific integrations are not implemented by this gateway. Local signed-JWT integration tests passing does **not** mean a live ChatGPT plugin, a fully compatible identity-provider flow, or App Directory approval.

## Agent-to-Agent v1.0 adapter (limited preview)

The gateway now provides an opt-in **A2A v1.0 JSON-RPC subset** alongside MCP and REST. A2A is for *agent-to-agent task collaboration*, whereas MCP connects an agent to tools.

Configure `SHARDS_A2A_BASE_URL=http://127.0.0.1:8787` for local testing. Remote OAuth mode automatically derives the A2A HTTPS base address from `SHARDS_PUBLIC_URL` unless overridden.

- `GET /a2a/agents/<agent_id>/card` — authenticated Agent Card describing the target worker. Requires `agent:read`.
- `POST /a2a/agents/<agent_id>` — A2A JSON-RPC 2.0 with `A2A-Version: 1.0`. `SendMessage` queues a durable task, requiring `task:create`. `GetTask` polls a task requiring `task:read` and creator/assignee ownership.
- Only the **v1.0** `ROLE_USER` format and non-empty `{"text":"..."}` parts are accepted. The received A2A message is preserved under the task input's `protocol: "a2a/1.0"` field; an independently connected agent worker must process it.
- Task outputs appear as A2A artifacts only once a separately authorised reviewer has verified them. A pending reported result is not represented as completed work.
- The included reference worker understands text-only A2A task input and performs **deterministic echo only**. It never treats received text as a shell command, network request, model instruction or trading instruction. A different agent runtime can implement real processing behind its own permission boundary.

`SendStreamingMessage`, `ListTasks`, `CancelTask`, multi-turn messages, push notification support and public well-known card discovery are **not implemented**. The adapter is a constrained subset, **not a full A2A conformance claim**. The per-agent card URL is available via direct configuration (a supported A2A discovery mechanism).

Reference: https://a2a-protocol.org/v1.0.0/specification/

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
- [Persistent Docker Compose deployment and recovery runbook](deploy/README.md)

## Test

~~~bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
~~~

MIT licensed, see [LICENSE](LICENSE).
