# Shards-MCP interoperability and ChatGPT plugin gate

Shards-MCP is a governed communication gateway, not an OAuth identity provider
or a general-purpose shell executor. All tools run in the authenticated context
of an enrolled agent.

## Supported entry points

| Interface | Client type | Contract |
| --- | --- | --- |
| POST /mcp | Streamable HTTP MCP clients | MCP 2025-11-25 tool-server subset |
| shards-mcp-stdio | Local desktop and CLI MCP clients | Scoped token, forwarding to the gateway |
| POST /v1/tools/{name} | REST automation, reference worker | Same Shards policy and scopes |
| /a2a/agents/{id} | Delegating agents | Opt-in text-only A2A v1.0 subset |

The **agent_identity** tool returns the current principal's agent_id,
effective scopes and role (operator or agent). It does not return credentials,
enrol other agents or change permissions. Every authenticated agent may call it.

MCP exposes tools to an AI runtime; A2A delegates work between agents. These
interfaces must not be confused with unrestricted tool execution.

## HTTP protocol boundary and version support

The gateway implements the **MCP 2025-11-25 tool-server subset**, not the
newer MCP 2026-07-28 server/discover lifecycle. This is a protocol-version
compatibility statement, not a blanket claim of compliance with the newest
MCP revision.

For /mcp requests, an explicitly supplied MCP-Protocol-Version header must
be exactly 2025-11-25; unsupported values and duplicate version headers return
HTTP 400. An absent header remains accepted for backward compatibility with
older clients and the local stdio bridge. Clients should use the version
returned by initialize.

HTTP POST requests with ambiguous duplicate Content-Length or Authorization
headers are rejected. Duplicate Origin headers are rejected even when the
first one appears allowlisted. Payloads containing duplicate JSON object keys
are rejected rather than allowing last-key-wins ambiguity. JSON-RPC request
IDs must be a scalar string or number; null, booleans, arrays and objects
are invalid. notifications/initialized must not carry a request ID.

The dedicated protocol-hardening regressions run in regular CI discovery,
alongside the official MCP SDK interoperability test. This does not replace
real public HTTPS and OAuth interoperability testing.

## Cancellation semantics across clients

The scoped MCP/REST **task_cancel** tool requires task:cancel and lets the
original task creator or the operator cancel a queued task. The underlying
SQLite transaction serializes cancellation against worker claim; exactly one
operation can succeed. Repeated cancellation through MCP/REST is idempotent
and does not generate extra audit entries.

A2A v1 CancelTask accepts an id for a task routed to that A2A agent. It
requires task:cancel plus task:read, returns a Task with
TASK_STATE_CANCELED, and returns the protocol TaskNotCancelableError (-32002)
if the task was already cancelled or has been claimed. GetTask preserves
that terminal state. An unrelated agent cannot cancel another creator's task
and an id for a different A2A target is not accessible.

**This is queue cancellation, not execution cancellation.** Once a task is
running, reporting a successful cancellation would be unsafe: the worker may
already have called external systems. A failed, reported or completed task
is likewise not cancellable. Expired running leases remain blocked until the
operator reconciles potential external effects. No rollback is implied.

The concurrency and HTTP cancellation regression suite is included in CI
test discovery on all supported Python versions.

## Run the end-to-end checks

~~~bash
python -m pip install -e '.[oauth]' 'mcp==2.0.0'
python -m unittest discover -s tests -p 'test_gateway_e2e.py' -v
python -m unittest discover -s tests -v
~~~

The E2E suite opens real loopback HTTP connections and checks:

1. MCP initialize, ping, scoped discovery and identity.
2. Sender-to-recipient durable messaging, idempotency and recipient isolation.
3. Shared event publication and cursor polling.
4. A worker in a **separate Python process** claiming, checkpointing and
   reporting an assigned task via REST.
5. Denial of creator self-verification, followed by independent reviewer
   attestation and successful task completion.
6. Audit hash verification and state persistence through gateway restart.
7. A **separate stdio bridge process** checking tool visibility, scope denial
   and token revocation.

GitHub Actions runs this contract explicitly on Python 3.11, 3.12 and 3.13.
The existing official MCP SDK, OAuth JWT, concurrency and HTTP regression tests
also run in CI.

These are local functional E2E checks, not proof of a public, deployed,
production-certified integration.

## Desktop and CLI MCP clients

Provision each agent with shards-mcp-admin, keeping its token private. In
the MCP client's secret environment configure:

- SHARDS_GATEWAY_URL: e.g. http://127.0.0.1:8787 on a trusted local host
- SHARDS_AGENT_TOKEN: the token for that agent, **never the admin token**

Launch shards-mcp-stdio from the client as its MCP stdio subprocess. On
connection, call agent_identity and tools/list. The supplied mcp.json is a
generic example; individual AI clients may require different configuration.

## ChatGPT / Codex remote plugin requirements

OpenAI's current guidance requires a stable publicly reachable **HTTPS**
Streamable HTTP endpoint (normally ending in /mcp) for public submission.
Authenticated plugins need a compatible OAuth 2.1 sign-in flow.

Shards-MCP currently verifies externally issued signed OAuth JWTs, maps a
verified subject to an enrolled Shards agent, and publishes OAuth protected
resource metadata. It is **not** an OAuth authorization server.

Before claiming compatibility with a live ChatGPT plugin:

1. Deploy /mcp behind a trusted TLS reverse proxy and retain private-only
   access to bootstrap secrets, metrics and administrative provisioning.
2. Configure a compatible OAuth authorization server; validate discovery,
   PKCE, consent, token exchange, audience, expiry and key rotation against
   the real client. Register the signed subject out-of-band with Shards.
3. Confirm the protected-resource metadata, WWW-Authenticate challenge and
   that supported scopes describe gateway-eligible permissions. OAuth grants
   are always intersected with agent enrolment scopes, never operator *.
4. Connect an actual ChatGPT or Codex client and validate tool discovery,
   read and write actions, denials, latency, reconnect and token refresh.
5. Verify monitoring, incident response and rollback; complete security and
   privacy documentation and publication review.

No publicly deployed endpoint, live identity provider, or successful ChatGPT
client connection is claimed here. A local test or temporary tunnel is not
evidence of public plugin readiness.

## Fail-closed properties to preserve

- Invalid/revoked credentials and wrong-audience tokens must be rejected.
- An OAuth scope claim cannot elevate beyond agent enrolment.
- Creator and worker may not approve their own task result.
- Expired leases are quarantined pending explicit external-effect reconciliation.
- Stdio stdout is JSON-RPC only; secrets must never enter model transcripts.
- Operator-only tools remain hidden and inaccessible to scoped agents.

See SECURITY.md, deploy/README.md and docs/roadmap.md for remaining gates.
