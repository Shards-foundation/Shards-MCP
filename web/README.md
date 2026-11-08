# Shards MCP Console — private-preview operational slices

This is a **separate Next.js application** under `web/`, not a public deployment or a replacement for the Python gateway.

## What works once configured

- Google, GitHub and Discord OAuth sign-in using NextAuth, with server-side secrets, eight-hour JWT sessions, and an explicit provider-subject allowlist (empty means no access).
- Authentication-gated console; unauthenticated users are redirected to `/signin`.
- A server-side, read-only gateway liveness probe at `/api/gateway/health` with a three-second timeout, no redirects, no user-supplied target URL, no credential forwarding and no response-body forwarding.
- Interactive IDE Connection Hub with local stdio and remote HTTP configuration templates for Cursor, Claude Code, Codex, VS Code, Antigravity and generic MCP clients. Templates are not live connectivity tests; installed client versions and transport support must be verified.
- A read-only agent-registry view backed by `POST /v1/tools/agent_identity` and `agent_list`, requiring a separate server-side `agent:read` credential. Raw gateway responses and credentials are never returned to the browser.
- Visible connection guidance and explicit disclosure of functionality not yet implemented.

**Social sign-in does not authorise gateway actions.** No administrator token, agent token or OAuth provider access token is sent to the browser. This version shows a read-only agent directory only when configured; it does not allow agent registration, revocation, task mutation or privilege changes. Those require tenant membership, roles, audit integration and a scoped backend bridge.

## Local setup

```sh
cd web
npm install
cp .env.example .env.local
# Configure NEXTAUTH_SECRET (random >=32 bytes), NEXTAUTH_URL and provider credentials.
npm run typecheck
npm run build
npm run dev
```

Set `SHARDS_CONSOLE_ALLOWED_IDENTITIES` to comma-separated `provider:providerAccountId` entries (for example `github:12345678`). An empty list denies all sign-ins. Determine the stable provider subject through the provider's trusted developer/account tooling; do not infer it from an email address. This is a private-preview admission gate, **not** persistent tenancy/RBAC. Account linking, invitation and session revocation require a future identity layer. Do not enable general public sign-up.

Register the exact redirect URLs in each OAuth provider's developer console:

| Provider | Local callback |
| --- | --- |
| Google | `http://localhost:3000/api/auth/callback/google` |
| GitHub | `http://localhost:3000/api/auth/callback/github` |
| Discord | `http://localhost:3000/api/auth/callback/discord` |

Set `SHARDS_GATEWAY_INTERNAL_URL` to the gateway address reachable from the **web server**, not from the user's browser. Remote URLs must use HTTPS. The probe does not establish readiness, OAuth interoperability, identity or permission scope.

For production, use a verified HTTPS domain and register corresponding provider callbacks. Configure `NEXTAUTH_URL` to the exact external origin and a strong `NEXTAUTH_SECRET`. Never commit `.env.local`. Do not expose the Python gateway bootstrap secret to the web application.

## Read-only agent registry setup (local gateway tokens only)

Provision a **separate local gateway identity** on the trusted gateway host with exactly the `agent:read` permission. `SHARDS_ADMIN_TOKEN` is only for the out-of-band local provisioning CLI and **must never be configured in Next.js**.

```sh
# On the gateway host, after configuring SHARDS_ADMIN_TOKEN and SHARDS_DB:
shards-mcp-admin register --name console-inventory --provider local \
  --scope agent:read --token-file /private/console-inventory.token
```

The CLI creates a new mode-0600 token file. Supply the secret to the web server through server-side secret management as `SHARDS_CONSOLE_READ_TOKEN` (never `NEXT_PUBLIC_`, committed settings, browser storage or responses). Keep `SHARDS_GATEWAY_INTERNAL_URL` as an operator-configured HTTPS origin or loopback HTTP origin. The web server must reach the gateway privately. Token value must have the local issuer's `shards_` format. A remote `SHARDS_AUTH_MODE=oauth` gateway is **not yet supported by this bridge**.

The server makes two fixed REST calls: first `agent_identity` verifies the credential is a non-operator with **exactly** `agent:read`; only then does `agent_list` return selected directory fields. Invalid credentials, redirects, malformed responses, excessive payloads and failed scope checks return only generic failure states. The browser never sees the bearer token. The API requires a valid allowlisted console session.

This is a **single-organisation private-preview** read interface. Anyone on the explicit social-subject sign-in allowlist who has a valid console session can see the directory. It is not tenant-isolated RBAC, immediate session revocation, a credential-rotation UI, or evidence that agent processes are alive. Gateway heartbeats are recent/stale observations with a 90-second threshold. If such exposure is too broad, do not enable the bridge; implement persistent operator roles first. For access removal, revoke the backend token out of band and expire console sessions as appropriate.

## IDE connection workflow

1. Install the Python gateway/stdio bridge package on the machine where the IDE runs.
2. Register a separate least-privilege agent credential on the trusted gateway host with `shards-mcp-admin`; never reuse the administrator token.
3. Sign in to the console, select the IDE and transport, then copy the generated configuration into that client's MCP settings.
4. Replace the credential placeholder using the client's protected secret mechanism. Do not commit secrets to workspace files.
5. Run `shards-mcp-doctor --protocol both --json` with the scoped credential from a trusted machine to verify server-side identity and permissions. Client-side verification must also be performed.

For remote HTTP, use HTTPS and confirm that the chosen IDE supports the required MCP transport and authentication header handling. Some clients may use different configuration keys or require their own OAuth flow; examples are not claims of certified compatibility.

## ChatGPT and AI connections

ChatGPT is an **MCP client integration**, not a configured OAuth sign-in provider. An externally reachable, secured MCP endpoint and tested client authorisation are separate release gates. The existing `shards-mcp-doctor` and `shards-a2a-doctor` can test scoped connectivity from a trusted host.

## Product architecture and delivery order

1. **Identity and tenancy**: persistent users, organisations, invitations, membership roles, account linking safeguards, session revocation and audit.
2. **Gateway bridge**: backend-to-gateway scoped credentials, per-tenant isolation, permission checks, rate limits and explicit CSRF controls for mutations.
3. **Operational console**: agent directory and status, task board, messages, checkpoints, audit verification, scheduler and observability.
4. **Connection wizard**: per-client MCP/A2A configuration, provider-specific setup, credential rotation and read-only diagnostics.
5. **Live integrations**: real external OAuth IdP, ChatGPT MCP client validation, and deployment acceptance with backups and alerting.

This first slice is intentionally **not** a production multi-tenant control plane. OAuth credentials, live deployment and integration testing are required before claiming it works on the internet.
