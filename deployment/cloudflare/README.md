# Shards-MCP Edge — Cloudflare Deployment and Operations

**Live portal:** https://mcp.shardsinc.co.uk

**Live transport:** https://mcp.shardsinc.co.uk/mcp

**Protected operator console:** https://mcp.shardsinc.co.uk/manage

**Worker:** `shards-mcp-edge`

**D1 database:** `shards-mcp-edge-prod` (EU jurisdiction)

**Worker source:** `deployment/cloudflare/worker.js`

**SQL schema:** `deployment/cloudflare/schema.sql`

## Scope: real deployed edge, not a proxy to the Python runtime

The edge service is a stateless Cloudflare Worker hosting a lightweight MCP transport, live public discovery and DNS tools, and D1-backed internal messaging and task coordination. It is **independent** of the existing Python `shards-mcp` runtime. Existing Python tasks, leases, independent review, scheduler, local hash-chain audit, A2A interface and package CLI are **not** automatically available through this public Worker. Do not misrepresent the edge as the full Python service.

The edge currently supports:
- JSON-RPC 2.0 over Streamable HTTP POST with a 2025-11-25 initialize / initialized subset
- 2026-07-28 `server/discover` subset with header routing validation
- `tools/list`, `tools/call`, `resources/list`, `prompts/list`, `ping`
- JSON response bodies, no SSE push/subscriptions
- 3 public read-only and 9 bearer-protected tools
- same-tenant agent discovery, messaging, tasks with atomic queued → claimed transition and own audit retrieval
- verified Cloudflare Access operator identity, scoped credentials, expiry and revocation
- simple daily operation budgets and fixed-target passive DNS

## Cloudflare configuration

The live deployment is in the existing Shards-inc Cloudflare account. Keep control of hostname and zone in your Cloudflare dashboard, not in an agent's prompt.

Worker bindings:
- `EDGE_DB`: D1 database in EU; apply `schema.sql` before deployment
- `ACCESS_TEAM`: the configured Cloudflare Access team slug, not a secret
- `ACCESS_AUD`: exact Access application audience tag, not a secret

A separate **self-hosted Cloudflare Access application** protects `mcp.shardsinc.co.uk/manage` and its subpaths, allowing only the existing administrator identity through the configured account IdP. The Worker also verifies each `cf-access-jwt-assertion` signature via the Access JWKS, issuer, audience, expiration, nbf and subject. Neither the JWT nor agent tokens are committed to the repository.

For source deployment, use the Cloudflare Workers multipart modules API or Wrangler with a verified D1 binding. **Never paste or commit your Cloudflare API token.** Existing deployment-specific IDs/permissions must be re-resolved from the Cloudflare dashboard before staging or replacement.

The D1 schema must be provisioned before application activation. No manual edits to live database credentials or administrator email should be committed.

## Key lifecycle

The management UI uses the authenticated operator to mint one CSPRNG 32-byte key per named agent. Tokens have a `smcp_` prefix and 30-day expiry. The UI renders the key once; D1 retains only SHA-256 of the full key. The operator selects a subset of explicit scopes; `agent:identity` is mandatory. Keys cannot assign a tenant through a client-provided field.

Credentials are automatically rejected after expiry, user revocation, agent disablement or token hash mismatch. Each tool verifies the scope from authenticated identity. Valid read-only tools that require no key are separated from protected operations.

For enterprise multi-tenancy, this first release intentionally provisions **only** the internal Shards tenant. A public self-service customer registration endpoint does not exist.

## External effect isolation

The edge cannot execute arbitrary commands, browse a user-supplied endpoint, transfer money, access GitHub private repositories, install plugins on another device or perform production deployments. Its DNS tool sends only validated public domain queries to Cloudflare DoH.

Tasks are **records of assignments and completions**, not remote code execution. The atomic claim operation currently has no lease expiry, external effect reconciliation, retries, checkpoint recovery or independent approval. Use the separate Python gateway for its supported durable workflow features until audited cross-host federation exists.

## API quick checks

```sh
curl -fsS https://mcp.shardsinc.co.uk/api/status

curl -sS https://mcp.shardsinc.co.uk/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

curl -sS https://mcp.shardsinc.co.uk/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

A protected call without an enrolled token returns a structured MCP `isError` response with `AUTH_REQUIRED`; it does not silently succeed. A non-origin browser POST is rejected. The management route is covered by Cloudflare Access; unauthenticated web navigation redirects to its sign-in page.

## CI, acceptance and monitoring

The workflow `.github/workflows/edge-smoke.yml` executes real public requests against production and checks the app source/client syntax, MCP initialise, modern discovery, tool listings, public tool execution, hostile Origin denial, invalid bearer denial and operator route protection.

**Do not treat public smoke success as proof of complete operational readiness.** Additional acceptance required:
- Actual signed administrator login, issue two nonidentical keys, verify different scopes, revoke one and prove immediate denial.
- Two authenticated separate agents exchange a message, claim a queued task, and verify no duplicate claim or cross-tenant disclosure.
- Test resource exhaustion, retry/error injection, concurrent messages with conflicting idempotency keys and process restarts.
- Add privacy and retention policies for message contents and audit history.
- Add WAF/Turnstile and per-principal abuse controls, enforce CORS/referrer restrictions, public telemetry and alerting.
- Integrate audited external OAuth 2.1 flows and refresh tokens for managed client authentication.
- Deploy and verify the actual Python gateway on a persistent protected Linux host, with Postgres authority if multi-host operation is intended.
- Prevent operator impersonation via stricter device/MFA posture requirements where available.

## Recovery and rollback

- Hosted code is in a dedicated Worker, leaving the original Python gateway and existing Shards sites untouched.
- In an incident, disable the `mcp.shardsinc.co.uk` custom hostname in Cloudflare and revoke affected agent credentials via the admin console after confirming access.
- Preserve the SQL state and audit entries for incident analysis. Do not erase data to hide symptoms.
- Revert through pinned Git commit/Cloudflare Worker deployment, with database schema compatibility checks.

## Contact and contributions

Source: https://github.com/Shards-foundation/Shards-MCP

Commercial deployment status: **experimental**, no public OAuth sign-in, no retail customers and no marketplace listing claimed.

## Edge rate limits and verification

Public tools are constrained by a global daily D1 budget and a lower daily budget per caller. Caller keys are SHA-256 digests of the UTC day and Cloudflare-provided client IP, never raw IPs. DNS input is validated **before** budget charging; invalid input cannot exhaust the shared DNS quota. The caller budget is a best-effort availability control, not a substitute for account quotas, edge WAF enforcement, abuse monitoring or periodic D1 budget cleanup. `node --test deployment/cloudflare/worker.test.mjs` checks protocol negotiation, early DNS validation, per-caller budget partitioning and token-display formatting using isolated local mocks. These tests do not prove private agent/token E2E or a new Worker deployment.

## Public browser Live Lab

The optional read-only portal at `https://mcp.shardsinc.co.uk/lab` is served directly by the **same edge Worker** and uses same-origin `POST /mcp` requests. It offers three executable browser workflows:

1. MCP protocol check: `initialize`, `tools/list` and `shards_gateway_status`.
2. Systems discovery: `shards_systems_catalog`.
3. Passive DNS resolution: `shards_dns_lookup` for A, AAAA, MX, TXT and CAA records.

The browser client has **no credential field**, no arbitrary MCP method selection and no privileged tool calls. It reports actual latency, results and errors, including budget exhaustion. No outcome is fabricated when the API, D1 storage or the upstream resolver is unavailable. A strict same-origin Content Security Policy applies.

The lab does not enrol agents, run private tasks, prove host-separated agent messaging or make the separate Python runtime available. It is a limited diagnostic utility, not a production certification dashboard.

Validate source before a deployment with `node --check deployment/cloudflare/worker.js` and `node --test deployment/cloudflare/worker.test.mjs`, then test the hosted page and MCP endpoint after a separately approved Worker rollout. Merging a pull request does **not** deploy the Cloudflare Worker.
