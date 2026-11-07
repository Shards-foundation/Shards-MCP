# Shards MCP Console — first operational slice

This is a **separate Next.js application** under `web/`, not a public deployment or a replacement for the Python gateway.

## What works once configured

- Google, GitHub and Discord OAuth sign-in using NextAuth, with server-side secrets, eight-hour JWT sessions, and an explicit email allowlist (empty means no access).
- Authentication-gated console; unauthenticated users are redirected to `/signin`.
- A server-side, read-only gateway liveness probe at `/api/gateway/health` with a three-second timeout, no redirects, no user-supplied target URL, no credential forwarding and no response-body forwarding.
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

Set `SHARDS_CONSOLE_ALLOWED_EMAILS` to a comma-separated list of approved account emails before testing sign-in. An empty list denies all sign-ins. This is a private-preview admission gate, **not** a substitute for persistent tenancy/RBAC. Provider email changes, account linking and revocation of existing sessions require a future persistent identity layer. Do not enable general public sign-up.

Register the exact redirect URLs in each OAuth provider's developer console:

| Provider | Local callback |
| --- | --- |
| Google | `http://localhost:3000/api/auth/callback/google` |
| GitHub | `http://localhost:3000/api/auth/callback/github` |
| Discord | `http://localhost:3000/api/auth/callback/discord` |

Set `SHARDS_GATEWAY_INTERNAL_URL` to the gateway address reachable from the **web server**, not from the user's browser. Remote URLs must use HTTPS. The probe does not establish readiness, OAuth interoperability, identity or permission scope.

For production, use a verified HTTPS domain and register corresponding provider callbacks. Configure `NEXTAUTH_URL` to the exact external origin and a strong `NEXTAUTH_SECRET`. Never commit `.env.local`. Do not expose the Python gateway bootstrap secret to the web application.

## ChatGPT and AI connections

ChatGPT is an **MCP client integration**, not a configured OAuth sign-in provider. An externally reachable, secured MCP endpoint and tested client authorisation are separate release gates. The existing `shards-mcp-doctor` and `shards-a2a-doctor` can test scoped connectivity from a trusted host.

## Product architecture and delivery order

1. **Identity and tenancy**: persistent users, organisations, invitations, membership roles, account linking safeguards, session revocation and audit.
2. **Gateway bridge**: backend-to-gateway scoped credentials, per-tenant isolation, permission checks, rate limits and explicit CSRF controls for mutations.
3. **Operational console**: agent directory and status, task board, messages, checkpoints, audit verification, scheduler and observability.
4. **Connection wizard**: per-client MCP/A2A configuration, provider-specific setup, credential rotation and read-only diagnostics.
5. **Live integrations**: real external OAuth IdP, ChatGPT MCP client validation, and deployment acceptance with backups and alerting.

This first slice is intentionally **not** a production multi-tenant control plane. OAuth credentials, live deployment and integration testing are required before claiming it works on the internet.
