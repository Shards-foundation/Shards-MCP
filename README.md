# Shards MCP Gateway

[![CI](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/Shards-foundation/Shards-MCP/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A persistent, authenticated agent-to-agent messaging and task control plane, exposed as an MCP tool server.**

> **Status: Python gateway v0.1.0 experimental, not production-certified.** The separately implemented Cloudflare **edge MCP** is now live at https://mcp.shardsinc.co.uk, but it is **not a hosted deployment of the complete Python gateway**. A2A full conformance, general ChatGPT OAuth private-tool access, complete external tool federation and commercial service approval remain unverified; no wallet execution.

## Live Shards MCP connectivity edge (experimental)

<https://mcp.shardsinc.co.uk> is an operational **Cloudflare Worker + EU D1** edge MCP gateway with a responsive setup portal for Claude Desktop, Claude Code, ChatGPT, Codex app/CLI and Cursor app/CLI.

- **Remote Streamable HTTP endpoint:** `https://mcp.shardsinc.co.uk/mcp`
- **Operator Access-protected registration console:** `https://mcp.shardsinc.co.uk/manage`
- **Provider status:** `https://mcp.shardsinc.co.uk/api/status`
- **Three credential-free read-only tools:** gateway health, Shards systems catalog and passive public DNS lookup
- **Nine protected agent tools:** enrolled identity/list, durable tenant-isolated messaging, assigned coordination tasks with atomic claims, and own audit summaries
- Per-agent CSPRNG bearer credentials, SHA-256-at-rest digests, 30-day expiry, operator-selectable scopes and revocation. No public user signup
- **Real client install/help links** at the portal, including an official Cursor deeplink and client-specific configuration commands
- `shards-mcp-connect` CLI for safe, explicitly requested local setup of Cursor, Claude Code or Codex (`--install` required)

See **[Universal Agent Get Started](docs/GET_STARTED_UNIVERSAL.md)**, **[Edge Operations](deployment/cloudflare/README.md)** and **[Marketplace Readiness](docs/MARKETPLACE_READINESS.md)**. Edge HTTP smoke tests and Python CI are run in GitHub Actions.

**Important release boundary:** This hosted Worker runs its own limited D1 message and task store. It does **not** host this repository's complete Python control plane, forward to the local Python server, execute arbitrary jobs, enforce production Shards Kernel permits, or supply a complete OAuth authorisation server for ChatGPT/Claude. The public plugin can discover read-only tools; private tools require distinct operator-issued tokens and compatible client headers. Cross-tenant and real signed-operator login E2E remain release gates. Do not sell or publicly certify it as a fully managed enterprise gateway.

### Install/configure a local client

```bash
# From a clone of this repo, after python -m pip install -e .
shards-mcp-connect --client cursor-app               # read-only explanation
shards-mcp-connect --client cursor-app --install     # modifies your local config, with backup
shards-mcp-connect --client claude-code --install    # runs locally installed Claude Code CLI
shards-mcp-connect --client codex-cli --install      # runs locally installed Codex CLI
shards-mcp-connect --client codex-app --verify       # read-only real HTTPS MCP handshake
```

`shards-mcp-connect` does not request or store the operator/admin secret. For cloud apps such as ChatGPT and Claude Desktop, use the official connection screens described in the live portal.

## Implemented

- Durable operational events with topic filters and monotonic cursor polling, separate from security audit entries.
- Agent-private event topics `agent.<agent_id>.<topic>`, untrusted shared broadcasts `shared.<topic>`, and operator-only `system.*` topics; audit queries scoped to the authenticated actor.

- MCP stdio bridge for compatible local AI runtimes, forwarding to the authenticated HTTP server.
- Authenticated `agent_identity` tool for effective principal and scope discovery without exposing credentials.
- MCP JSON-RPC over authenticated `POST /mcp`, with both the legacy `2025-11-25` initialize/ping/tool-server contract and the **2026-07-28 stateless tool subset** (`server/discover`, `tools/list`, `tools/call`, per-request metadata and checked routing headers). The newer contract is not yet a full MCP extensions/subscriptions implementation. Generic HTTP automation may alternatively use `POST /v1/tools/{name}` or discover `GET /v1/tools`.
- Scoped bearer-credential agent registration, agent enumeration, revocation and heartbeat.
- Durable agent-to-agent messaging, idempotency and recipient isolation.
- Assigned tasks with leases, checkpoint persistence, conservative failure recovery and independent task verification gate.
- Atomic `task_claim_next` dequeue-and-lease: a scoped worker fetches its next assigned queued task and input in **one transaction** instead of racing between an inbox poll and claim; FIFO order, no duplicate claims, no implicit replay of running tasks.
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

The `shards-mcp-doctor` command verifies scoped Streamable HTTP MCP
connectivity and reports the authenticated agent ID, effective permissions,
visible tools and latency. It supports three explicit modes: `--protocol legacy`
(the default, using the 2025-11-25 initialize/initialized lifecycle),
`--protocol modern` (2026-07-28 stateless discovery, tool listing and identity),
and `--protocol both` (verifies both contracts and checks that they expose
the same agent and tool authority). It performs **no writes**, never prints
credentials, rejects administrator identities and refuses non-loopback
plaintext or redirects. A failed modern check never silently falls back to
legacy.

With a separately provisioned agent credential:

~~~bash
export SHARDS_GATEWAY_URL=http://127.0.0.1:8787
export SHARDS_AGENT_TOKEN="$(cat "$HOME/.config/shards/hermes.token")"
shards-mcp-doctor --json
shards-mcp-doctor --protocol modern --json
shards-mcp-doctor --protocol both --json
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

## Verify A2A without creating tasks

A scoped client can use the new read-only shards-a2a-doctor CLI to check
an enrolled target Agent Card and the A2A 1.0 JSON-RPC GetTask error
contract. It sends **no SendMessage, CancelTask or worker actions**.

~~~bash
shards-a2a-doctor --url http://127.0.0.1:8787 \
  --target-agent agt_REPLACE_WITH_ENROLLED_ID \
  --token-file "$HOME/.config/shards/reader.token" --json
~~~

Requires a separate agent credential with agent:read and task:read. It also verifies scoped agent identity through Shards' read-only MCP agent_identity workflow, rejecting an operator token even when the local SHARDS_ADMIN_TOKEN variable is absent.
It rejects off-loopback plaintext, redirects, malformed responses and
insufficient permissions. Success verifies only this read-only slice of
A2A v1.0 for the configured connection, not general interoperability.

See [A2A diagnostic guide](docs/a2a-doctor.md).

## Agent-to-Agent v1.0 adapter (limited preview)

The gateway now provides an opt-in **A2A v1.0 JSON-RPC subset** alongside MCP and REST. A2A is for *agent-to-agent task collaboration*, whereas MCP connects an agent to tools.

Configure `SHARDS_A2A_BASE_URL=http://127.0.0.1:8787` for local testing. Remote OAuth mode automatically derives the A2A HTTPS base address from `SHARDS_PUBLIC_URL` unless overridden.

- `GET /a2a/agents/<agent_id>/card` — authenticated Agent Card describing the target worker. Requires `agent:read`.
- `POST /a2a/agents/<agent_id>` — A2A JSON-RPC 2.0 with `A2A-Version: 1.0`. `SendMessage` queues a durable task, requiring `task:create`. `GetTask` polls a task requiring `task:read` and creator/assignee ownership.
- Only the **v1.0** `ROLE_USER` format and non-empty `{"text":"..."}` parts are accepted. The received A2A message is preserved under the task input's `protocol: "a2a/1.0"` field; an independently connected agent worker must process it.
- Task outputs appear as A2A artifacts only once a separately authorised reviewer has verified them. A pending reported result is not represented as completed work.
- The included reference worker understands text-only A2A task input and performs **deterministic echo only**. It never treats received text as a shell command, network request, model instruction or trading instruction. A different agent runtime can implement real processing behind its own permission boundary.

`SendStreamingMessage`, `ListTasks`, multi-turn messages, push notification support and public well-known card discovery are **not implemented**. `CancelTask` is supported only for unclaimed queued tasks. It requires both `task:read` and `task:cancel` scopes, and the caller must be the task creator or the operator; claimed or running work returns a not-cancelable error, without interruption or rollback of external effects. The adapter is a constrained subset, **not a full A2A conformance claim**. The per-agent card URL is available via direct configuration (a supported A2A discovery mechanism).

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
- [Release workflow and production deployment acceptance](docs/releasing.md)
- [Persistent Docker Compose deployment and recovery runbook](deploy/README.md)

## Test

~~~bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
~~~

MIT licensed, see [LICENSE](LICENSE).
