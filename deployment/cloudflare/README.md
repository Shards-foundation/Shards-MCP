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
- `CONNECT_ACCESS_AUD`: separate pilot MCP Access application audience tag (required for `/connect` and `/connect/profile`; must differ from `ACCESS_AUD`)

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


## Authenticated MCP connection (separate Cloudflare Access application)

`https://mcp.shardsinc.co.uk/signin` is a public sign-in entrypoint. `https://mcp.shardsinc.co.uk/connect` is a **separate Access-protected MCP POST endpoint**. `https://mcp.shardsinc.co.uk/connect/profile` is the verified browser profile path. Neither path is an end-user database account or operator account. It must be bound to its **own** Cloudflare Access application and audience, not the existing operator-only `/manage` application.

### Identity provider requirements

- The account currently contains a Cloudflare identity provider. Its existing configuration restricts sign-in to Cloudflare account members. A distinct email one-time-PIN identity provider was registered for separate explicitly allowed Access applications. Both require an Access policy admitting the user; these mechanisms are **not** equivalent to public Google/GitHub/Discord login.
- Do not show buttons for Google, GitHub, Discord, Apple, Microsoft, Meta, OpenAI, Anthropic/Claude, phone/SMS or email OTP unless an actual configured IdP and a successful callback verify them. Each external provider requires suitable developer registration/credentials; SMS also requires a legitimate delivery/abuse-control provider. OpenAI and Anthropic consumer accounts are not assumed to provide general-purpose social-login OAuth.
- If offering public self-service sign-in later, use a **separate** public login method and explicit enrolment/privacy/abuse policy. Do not relax the existing account-member-only operator IdP or change `/manage` policies.
- Portal sessions, Cloudflare Access application tokens and existing `smcp_*` agent tokens are separate security domains.

### Cloudflare Access Managed OAuth configuration

1. Keep `/mcp`, `/lab`, `/api/status` and `/signin` public. Preserve the owner-only Access app for `/manage` exactly as it is.
2. Create a new self-hosted Cloudflare Access application securing only **`mcp.shardsinc.co.uk/connect` and `mcp.shardsinc.co.uk/connect/profile`** with the same audience. Select the actual configured IdP and an explicitly reviewed Access policy. Enable **Managed OAuth** and avoid enabling it on the operator application.
3. Record the newly issued Access application **audience tag** in the Cloudflare Worker plain-text binding `CONNECT_ACCESS_AUD`. Retain `ACCESS_TEAM`, `ACCESS_AUD` and `EDGE_DB` unchanged. Use strict binding inheritance on Worker versions.
4. Confirm an anonymous browser navigation to `/connect/profile` redirects to real Cloudflare Access login, while an authenticated browser receives the signed-identity page. A signed-in `GET /connect` must return MCP HTTP 405 rather than HTML.
5. Test the MCP client at `https://mcp.shardsinc.co.uk/connect` (the Managed OAuth route). The client must support the RFC 8707 resource indicator and provider-managed PKCE flow. An unauthenticated non-browser MCP request should receive an OAuth `401` challenge from Access, not a fake success or arbitrary local browser token.
6. After completing a real login, use `tools/list` and `shards_user_identity`. The supported authenticated tools are `shards_user_identity` plus the three existing **public** read-only tools. This is *not* a general user account, internal tenant membership, or an agent enrolment feature. Existing private messages/tasks remain restricted to separately provisioned `smcp_*` agents.

**Security boundary:** Worker code verifies the JWT signature against the fixed Cloudflare Access JWKS, expected issuer, separate audience, expiry and nbf. The new route does not accept a user-provided issuer, an unverified JWT, or an arbitrary redirect URL. The operator JWT cannot be reused as a connect JWT and vice versa.

**Rollback:** Revert only the new Access app/policy and Worker deployment to the prior pinned version. Never delete the D1 database, existing Access operator app or its policies. An attempted provider login must be labelled **BLOCKED** until a real user completes the provider consent/callback; the tests cannot impersonate a Cloudflare account or prove a UI login.

**Pricing/admission gate:** Cloudflare Access Free is intended for fewer than 50 users; avoid enabling unrestricted customer self-sign-up via an Access `Everyone` policy. The initial `/connect` app is a limited operator-approved pilot, not a commercial identity platform. For public customer growth, use a dedicated customer-identity platform and a migration design.


## Path-bound OAuth discovery for `/connect`

Cloudflare Access Managed OAuth is enabled on the separate application scoped to `mcp.shardsinc.co.uk/connect`, **not** the whole MCP hostname. On the prior deployment, the root `/.well-known/` endpoints returned HTTP 404 because the root hostname is intentionally public and handled by the Worker. This prevented standards-based clients from locating the issuer through the conventional resource URLs.

The Worker now serves:

| Public discovery route | Behaviour |
| --- | --- |
| `/.well-known/cloudflare-access-protected-resource/connect` | **Actual Access-advertised path** observed in the live HTTP 401 `WWW-Authenticate` header; returns canonical resource, verified issuer, and public Cloudflare protection metadata |
| `/.well-known/oauth-protected-resource/connect` | RFC 9728 metadata: canonical resource `https://mcp.shardsinc.co.uk/connect`, configured Cloudflare Access issuer, and header-based bearer transport |
| `/.well-known/oauth-protected-resource` | Temporary redirect to the path-bound resource metadata |
| `/.well-known/oauth-authorization-server` | Temporary redirect to the **actual** `https://<ACCESS_TEAM>.cloudflareaccess.com/.well-known/oauth-authorization-server` metadata published by Cloudflare |

The issuer is built only from the restricted Worker `ACCESS_TEAM` binding, never from query parameters or user input. The exact Access-advertised metadata path was extracted from the deployed Cloudflare Access `401` challenge by the edge acceptance workflow, not guessed from the standards fallback. GET discovery requests return 503 if the separate audience is missing, equal to the operator audience, or the team hostname configuration is invalid. Other request methods are not discovery operations and return 404. They do **not** issue OAuth tokens, advertise unsupported providers, or bypass the Cloudflare Access policies.

These metadata endpoints permit anonymous cross-origin **GET** reads (`Access-Control-Allow-Origin: *`) because their contents are public. This CORS allowance applies **only to discovery metadata and redirects**; the authenticated `/connect` endpoint still rejects untrusted browser origins. Authenticated clients can retrieve only their **own verified identity** (including their Access email if provided) and the three public read-only tools; no raw bearer credentials, internal agent records or privileged tool authority are exposed.

An origin-bypass fallback `401` on `/connect` includes the RFC 9728 `resource_metadata` challenge URL. The actual browser/agent challenge for a Cloudflare-protected request is managed by Cloudflare Access, which may replace that header.

**Live verification required after deploying this change:** fetch all three discovery routes, follow the authorization-server redirect and confirm the real issuer and S256 support; confirm `/signin` and `/lab` still load, the original public `/mcp` remains available, and unauthenticated `/connect` is blocked by Access. A successful real user OAuth authorization-code exchange and token refresh remain **BLOCKED until observed in a supported client**; discovery and JWT mock tests alone are not proof.
