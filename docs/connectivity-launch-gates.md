# Shards MCP connectivity launch gates

Status: implementation integration work. **No hosted-service certification implied.**

## Architectural boundary

- `mcp.shardsinc.co.uk/mcp`: OAuth-protected MCP resource endpoint on the existing Cloudflare edge routing path, with a durable Python backend/or equivalent fully tested server.
- The Next.js onboarding portal is a distinct web application and can use a separate hostname; it must never shadow `/mcp` on the existing worker.
- Identity to portal: provider OAuth/OIDC (Google, GitHub, Discord, Apple; OpenAI only upon partner enablement).
- Identity to MCP: OAuth authorization-code + PKCE, protected-resource metadata, authorization-server discovery, token audience and scope checks; gateway's enrolled subject binding is separate from portal login.
- Execution: named least-privilege tools, per-agent credentials, no bootstrap secrets in browser/JSON files, immutable external audit witness for launch.

## Acceptance matrix (required before public connection claims)

| Gate | Required evidence |
| --- | --- |
| DNS/TLS | Hostname resolves, valid certificate, tests from independent external networks |
| Worker route | Verify active script, protect existing route, map `/mcp` to real backend and record rollback |
| MCP compatibility | Real initialize/tools/list/tools/call from each client, with a supported wire version |
| OAuth | PKCE S256, AS/PRM discovery, consent, token audience/scope/revocation, error challenges |
| Provider logins | Actual callback round trips for Google/GitHub/Discord/Apple; ChatGPT only if approved |
| Authorization isolation | Public sign-in cannot read operator resources; distinct users/agents cannot see each other's data |
| Persistence | Durable backend DB, backups, restore and restart/retry tests across hosts |
| Operations | Rate limits, abuse handling, security logging, alerts, secret rotation, runbooks |
| Distribution | Legal terms, privacy policy, docs, marketplace policies, trademark checks and platform review |

## Distribution categories

MCP discovery catalogs: MCPMarket and MCP Marketplace — list server manifest, tool permissions, transport and install guide after verifying the hosted endpoint. ChatGPT business marketplace and Claude marketplace/Connectors Directory: formal platform review; a deployable endpoint is not an automatic listing. Microsoft Marketplace, Google Workspace Marketplace, Vercel Marketplace, Oracle Marketplace: separate commercial apps/integrations and their own technical/compliance reviews. GitHub Marketplace: requires an actual GitHub App or Action product, not merely a repository. Top.gg and Discadia are Discord bot/directories requiring an independently working Discord integration, OAuth and bot permissions. Do not submit misleading listings or promise blanket cross-marketplace acceptance.

## Operational steps

1. Freeze and record current Cloudflare Worker version and database bindings; inspect edge route before writes.
2. Establish a deployed persistent Python gateway plus issuer; don't replace the edge worker with a static web page.
3. Configure web origin, four OAuth provider applications, server secret and restricted operator identities.
4. Run platform-specific auth and tool E2E from external clients. Record PASS/FAIL/BLOCKED and audit outcomes.
5. Only then expose public install claims, enable self-service customer enrolment and prepare submissions.
