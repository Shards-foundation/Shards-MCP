# Shards MCP Console — first operational slice

This is a **separate Next.js application** under `web/`, not a public deployment or a replacement for the Python gateway.

## What works once configured

- Google, GitHub and Discord OAuth sign-in using NextAuth, with server-side secrets, eight-hour JWT sessions, and an explicit provider-subject allowlist (empty means no access).
- Authentication-gated console; unauthenticated users are redirected to `/signin`.
- A server-side, read-only gateway liveness probe at `/api/gateway/health` with a three-second timeout, no redirects, no user-supplied target URL, no credential forwarding and no response-body forwarding.
- Interactive IDE Connection Hub with local stdio and remote HTTP configuration templates for Cursor, Claude Code, Codex, VS Code, Antigravity and generic MCP clients. Templates are not live connectivity tests; installed client versions and transport support must be verified.
- Visible connection guidance and explicit disclosure of functionality not yet implemented.

**Social sign-in does not authorise gateway actions.** No administrator token, agent token or OAuth provider access token is sent to the browser. This version deliberately does not allow registration, agent management or task mutation. Those require tenant membership, roles, audit integration and a scoped backend bridge.

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

## Universal client onboarding (2026-11-10)

- Public landing route `/` and `/get-started` support Cursor app/CLI, Claude Desktop/Code, ChatGPT, Codex app/CLI.
- Cursor's documented deep-link uses base64-encoded MCP server settings. Other buttons copy **real supported commands or URL**; there is deliberately no fake automatic installer for clients that require their own Add Server / OAuth UI.
- Social login at `/signin` and authenticated `/account` supports **Google, GitHub, Discord, Apple** only when their individual OAuth client credentials are configured. If an approved Sign in with ChatGPT partnership provides OIDC endpoints and credentials, the ChatGPT option becomes available. Never show it as working before approval.
- Existing operator routes move from `/` to `/console`; `/agents`, `/tasks`, `/audit`, `/connections` remain operator-only, protected by the stable `provider:subject` allowlist. All authenticated users may access `/account`. Social login alone grants **no gateway authority**.
- The Python MCP service and the Next.js frontend are **separate workloads**. The endpoint `https://mcp.shardsinc.co.uk/mcp` must forward to a real MCP resource server, not the static frontend. Do not repoint the existing Cloudflare Worker custom domain without reviewing its current configuration and rollback.
- Full customer organisations, persistent identity linking, entitlement management and provisioning are not implemented by JWT-session sign-in. Do not describe this as a production multi-tenant account service.

Provider production callback URLs on the **web origin** are `https://<web-origin>/api/auth/callback/google`, `/github`, `/discord`, `/apple` and (only with approved credentials) `/chatgpt`. Set `NEXTAUTH_URL` to the exact front-end origin, `NEXTAUTH_SECRET` to a strong random secret, and register each callback with the provider.

See [connectivity launch gates](../docs/connectivity-launch-gates.md).


### Authentication compatibility note

The deployed Cloudflare Edge at `mcp.shardsinc.co.uk` currently supports three unauthenticated read-only discovery tools, plus operator-provisioned bearer keys for its private tools. It does **not** yet implement an MCP OAuth authorization server. Codex, Cursor, ChatGPT and Claude client setup instructions therefore intentionally do **not** issue `codex mcp login` or other OAuth login instructions as a mandatory step. An imported connector URL alone does not prove that private tools are usable.
