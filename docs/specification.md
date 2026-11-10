# Shards-MCP Technical Specification (implemented subset)

**Document version:** 0.1 | **Product:** `shards-mcp==0.1.0` source state | **Authority:** `src/shards_mcp/` and `tests/`.

This is an implementation specification, not a claim of independent MCP/A2A certification. The project is a tool/coordination gateway; model inference and general external tool execution are outside the package.

## Components and boundaries

| Component | Entry | Trust / persistence |
| --- | --- | --- |
| HTTP gateway | `shards-mcp`, `POST /mcp` | Authenticates all tool requests; persists state via SQLite WAL |
| REST adapter | `GET /v1/tools`, `POST /v1/tools/{name}` | Same dispatcher and scoped permissions |
| Local stdio bridge | `shards-mcp-stdio` | Forwards to one authenticated HTTP gateway; credentials via env |
| A2A adapter | `/a2a/agents/{agent_id}` | Opt-in constrained v1.0 text-task delegation |
| Reference worker | `shards-worker` | Restricted `echo` / `sha256` / `health` or A2A text echo |
| Scheduler | `shards-scheduler` | One host process; interval tick and lease quarantine |
| Admin | `shards-mcp-admin` | Host-local token enrolment, revocation, snapshot operations |
| Console | `web/` NextAuth | Private-preview Google/GitHub/Discord allowlist, read-only health; no gateway mutation authority |

## MCP wire support

- **2025-11-25:** authenticated JSON-RPC initialise/initialized, ping, tools/list, tools/call, stateless server-side persistence.
- **2026-07-28:** stateless **tool-only** subset `server/discover`, `tools/list`, `tools/call` with mandatory routing/version metadata. No general subscriptions, resources/prompts, MCP Tasks extension, elicitation or streaming requests.
- Tool input schema validation rejects unknown fields, malformed JSON, duplicate keys, depth overruns and unsupported protocol revisions. See [interop details](interoperability.md).
- Local bearer credentials only for loopback; externally bound listener requires optional JWT resource-server mode with pinned HTTPS JWKS URI, issuer, exact audience and enrolled subject. This does not implement authorisation-code/PKCE issuing flows.

## Scope catalogue

`agent:read`, `agent:heartbeat`, `message:send`, `message:read`, `task:create`, `task:read`, `task:claim`, `task:update`, `task:cancel`, `task:verify`, `checkpoint:write`, `audit:read`, `event:read`, `event:write`. The operator's `*` capability is not enrolable as an agent. Tool visibility is scope-filtered; `task_claim_next` additionally requires `task:read`.

## Tool families

| Family | Tools | Notes |
| --- | --- | --- |
| Identity | `agent_identity`, `agent_list`, `agent_heartbeat` | Agent management is host-only; list returns no tokens |
| Messaging | `message_send`, `message_inbox`, `message_poll`, `message_ack` | Durable receiver isolation and idempotency |
| Task orchestration | `task_create`, `task_get`, `task_inbox`, `task_claim`, `task_claim_next`, `task_renew`, `task_complete`, `task_cancel`, `task_verify`, `task_reconcile`, `task_scan_expired` | Creator/assignee/verifier policy, lease and reconciliation |
| Checkpoints | `checkpoint_write`, `checkpoint_get`, `verification_get` | Stored evidence, not model process snapshots |
| Events/audit | `event_publish`, `event_poll`, `audit_list`, `audit_verify` | Audit verification operator-only; shared events untrusted |
| Scheduler/system | `schedule_create`, `schedule_list`, `schedule_disable`, `schedule_tick`, `system_status`, `system_sanity_check` | Operator-only controls |

Tool names, required args, types and permission mapping are canonically defined by `TOOL_DEFS` and `TOOL_SCOPES` in `src/shards_mcp/server.py`. Do not treat this human-readable summary as an independent OpenAPI schema.

## Task consistency

- Sender provides `assignee`, JSON `payload` and an `idempotency_key`.
- Worker claims via atomic SQLite transaction, obtains bounded lease (15–3600 seconds); active renewals are capped by an overall claim lifetime.
- Worker can write checkpoints and complete with `success=true`, which transitions to `reported`.
- Separate verifier calls `task_verify(approved, evidence)`; valid approval marks `succeeded`. Worker and creator cannot self-certify.
- Expired leases are quarantined; explicit operator reconciliation after checking external effects is required.
- No multi-host leader election, exactly-once external side effects, execution rollback, or running-task kill.

## A2A scope

Opt-in per-agent cards and authenticated JSON-RPC v1.0 subset: `SendMessage` creates assigned text task; `GetTask` returns owner-visible task; `CancelTask` only before claim. No streaming, push, files, general agent registry or multi-turn continuation. Source: `src/shards_mcp/a2a.py`.

## HTTP system and operations

`GET /health/live` proves process liveness; `GET /health/ready` checks database transaction; `GET /metrics` is operator/local only. Caddy example denies metrics externally. Plain HTTP outside loopback and redirects are refused by diagnostic/worker clients.

## Security limits / evidence

SQLite audit hashing is locally verifiable but DB owner can rehash. Snapshots are local and need encrypted off-host copy. No default data retention, multi-tenant isolation, rate limits/alert delivery, enterprise SLA or public URL. Source-facing tests: `test_core.py`, `test_gateway_e2e.py`, `test_official_sdk.py`, `test_a2a.py`, `test_protocol_hardening.py`.

## External standards references

- [MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP current specification](https://modelcontextprotocol.io/specification)
- [A2A v1.0](https://a2a-protocol.org/v1.0.0/specification)
- [OAuth protected-resource metadata RFC 9728](https://www.rfc-editor.org/rfc/rfc9728)
