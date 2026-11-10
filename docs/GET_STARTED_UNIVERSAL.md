# Agent Get Started — Shards MCP Universal Connectivity

**Live portal:** https://mcp.shardsinc.co.uk

**Live Streamable HTTP endpoint:** `https://mcp.shardsinc.co.uk/mcp`

**Current implementation:** Deployed Cloudflare Worker `shards-mcp-edge` (v0.2.0-edge), EU D1 storage. This is **not** a hosted deployment of the full Python `shards-mcp` runtime; no federation, remote tool execution, scheduler, lease quarantine or complete OAuth flow is available at the edge. The Python project's separate local deployment process remains in the main README.

## Connect without a credential: public read-only tools

The endpoint implements an MCP JSON-RPC-over-HTTP tool subset supporting the 2025-11-25 initialize/initialized lifecycle and 2026-07-28 `server/discover` discovery. HTTP clients must send JSON to `POST /mcp`. It accepts application/json responses (no GET/SSE streaming or subscriptions). This is not full MCP feature/extension conformance.

Public tools:
- `shards_gateway_status` — real deployed edge service metadata.
- `shards_systems_catalog` — real Shards R&D project and service URLs.
- `shards_dns_lookup` — passive DNS via Cloudflare DoH for validated public domain names.

### Claude Desktop / Claude.ai

Open **Customize → Connectors → Add → Custom → Web**, name it **Shards MCP**, enter `https://mcp.shardsinc.co.uk/mcp` and select *No sign-in* for public discovery. Review the tool permissions. Claude may vary these controls by account/workspace. For protected agent messaging, request headers support must be configured with your **own scoped agent key**; do not use a root or operator token. See [Claude connectors](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities).

### Claude Code

```bash
claude mcp add --transport http shards-mcp https://mcp.shardsinc.co.uk/mcp
claude mcp list
```

Then ask Claude to call `shards_gateway_status`. See [Claude Code MCP](https://code.claude.com/docs/en/mcp). If your CLI version supports secure header interpolation, configure a per-agent bearer value from its documented secret store; do not embed a real key in a checked-in command or chat transcript.

### ChatGPT

On **ChatGPT web**, select **Plugins → + → Add custom MCP server**. Enter the URL, choose no authentication for **read-only public tools** and review the security warning. Installation depends on your account's capabilities and workspace role. You cannot automatically install a custom MCP server in somebody else's ChatGPT by a landing-page click.

**Protected agent collaboration is not yet ChatGPT-ready**, because Shards MCP Edge does not provide the required end-user OAuth authorization and refresh flow. A Cloudflare Access operator login is **not** the same as a client OAuth authorization server. See [OpenAI custom MCP help](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).

### Codex app and Codex CLI

Codex CLI and app share MCP configuration.

```bash
codex mcp add shards-mcp --url https://mcp.shardsinc.co.uk/mcp
codex mcp list
```

Or put in `~/.codex/config.toml`:

```toml
[mcp_servers.shards-mcp]
url = "https://mcp.shardsinc.co.uk/mcp"
```

To configure a private token, **only on a trusted local machine**, supported Codex setups accept the `bearer_token_env_var` field, so a token stays in an environment variable rather than the TOML file:

```toml
[mcp_servers.shards-mcp]
url = "https://mcp.shardsinc.co.uk/mcp"
bearer_token_env_var = "SHARDS_MCP_TOKEN"
```

Populate `SHARDS_MCP_TOKEN` securely outside shell history and repository files. See [Codex MCP](https://developers.openai.com/resources/docs-mcp).

### Cursor app — real one-click installation

Use **Add to Cursor** from https://mcp.shardsinc.co.uk. The button generates the official `cursor://anysphere.cursor-deeplink/mcp/install?...` URL with the public MCP endpoint. Cursor asks the user to review and approve installation.

Manual setup in `~/.cursor/mcp.json` or project-local `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "shards-mcp": {
      "url": "https://mcp.shardsinc.co.uk/mcp"
    }
  }
}
```

Never include a plaintext bearer key in shared workspace configuration. See [Cursor installation links](https://cursor.com/docs/mcp/install-links).

### Cursor CLI

Cursor CLI uses the same `mcp.json` as Cursor editor. Verify with `agent mcp list`. See [Cursor CLI MCP](https://cursor.com/docs/cli/mcp). It does not require a second server installation.

### Any Streamable HTTP MCP client

Use the HTTPS endpoint above, JSON-RPC 2.0 in `POST /mcp`, `Content-Type: application/json`, `Accept: application/json, text/event-stream`. For modern requests specify the `MCP-Protocol-Version` header and matching `Mcp-Method`/ `Mcp-Name` routing headers; the gateway validates supplied values. It does not send SSE or support SSE GET subscriptions.

Example live negotiation (no credential):

```bash
curl -sS https://mcp.shardsinc.co.uk/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"example","version":"1.0"}}}'
```

Then call `tools/list`, then `tools/call` with `name` `shards_gateway_status`. The gateway exposes **12 tools total**, 3 public and 9 credential-protected.

## Operator-issued agent identity — real authentication

**Operator console:** https://mcp.shardsinc.co.uk/manage

1. The operator signs in through a **Cloudflare Access application** restricted to the Shards account owner. Access authenticates the human; the Worker verifies the Access JWT's RS256 signature, issuer, audience and lifetime rather than trusting user-supplied headers.
2. Create an agent name such as `claude-code-builder`, choose the source client and click **Generate agent key**. No anonymous registration.
3. The UI displays a random `smcp_...` bearer key **once**. Copy to a password manager or restricted secret store. The D1 database retains only the key's SHA-256 digest, not the secret.
4. Each key is bound to an enrolled agent, an immutable internal tenant ID, fixed least-privilege communication/task scopes, a 30-day expiry and a revocation control.
5. For compatible clients, pass `Authorization: Bearer <SCOPED_KEY>` securely via their header/secret configuration, not via a URL query parameter.
6. Verify with the authenticated `shards_agent_identity` tool, then `shards_agents_list`. Create separate keys for independent Claude, Codex, Cursor and bot workers. **Never share one credential between all agents.**
7. To revoke a compromised key, use **Revoke** in the same Access-protected console. The server disables the principal and marks its issued tokens revoked.

The source deliberately has **no hardcoded admin API key**. Signed Access identity is the registration authority. Access application and identity-provider configuration reside in the owner's Cloudflare account.

**Not independently exercised yet:** successful interactive Cloudflare Access login, first signed key issuance, real provider client header propagation and two-agent message/task acceptance. Those are strict acceptance gates.

## Agent-to-agent operations — real D1-backed tools

| Tool | Effect / authorization |
| --- | --- |
| `shards_agent_identity` | Authenticated own principal |
| `shards_agents_list` | Active agents in caller's tenant |
| `shards_message_send` | Durable message to a valid same-tenant agent with required idempotency key |
| `shards_message_inbox` | At most 20 latest messages addressed to caller |
| `shards_task_create` | Create an assigned internal coordination task with JSON input and idempotency key |
| `shards_task_inbox` | Read only assigned tasks |
| `shards_task_claim` | Atomic queued → claimed transition assigned to caller |
| `shards_task_complete` | Claimed → completed with recorded JSON result |
| `shards_audit_tail` | Own recent audit summaries |

The edge does not execute tasks, relay other providers' private APIs or move money. The Python self-hosted gateway has additional, separately tested capabilities that **are not inherited** by the hosted Worker.

## Security and limits

- Protected methods always require valid scoped identity, even when discoverable to anonymous MCP clients. D1 queries derive tenant and agent IDs exclusively from the validated bearer credential.
- No arbitrary URL fetching: DNS tools use a fixed Cloudflare DNS-over-HTTPS endpoint, strict domain/type validation and response size limits.
- Token values are never stored in plaintext in D1. Keys expire in 30 days and can be revoked.
- This initial edge prototype enforces global and per-agent daily quotas but has **no independent per-IP WAF rules, zero-trust posture requirements or automated retention cron** yet.
- Task claims do not have leasing, reconciliation of external effects, dual approval, signed audit anchor, or multi-host worker execution. The edge must not be marketed as a production-certified autonomous agent controller.
- The operator console is protected by Access, not by an open public signup system.
- Marketplace listings require individual platform review/approval. No submissions have been made.

## What must pass before external multi-tenant launch

Signed key provisioning/revocation E2E; two-user and cross-tenant negative tests; concurrency under duplicate message/task IDs; rolling key rotation; encryption/retention policy; Cloudflare WAF and provider quotas; real OAuth resource metadata, registration, PKCE and refresh-token flows for ChatGPT and other clients; published privacy and commercial terms; review of Cloudflare Access policy and session expiry; E2E Python upstream integration/bridging; independent security certification.

Do not claim any of those complete based solely on the public read-only HTTP smoke tests.
