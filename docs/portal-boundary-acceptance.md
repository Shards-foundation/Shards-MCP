# Cloudflare MCP Portal — read-only acceptance boundary

**Target:** `https://portal.shardsinc.co.uk/mcp` (the Access-protected *portal*, **not** the public upstream `https://mcp.shardsinc.co.uk/mcp`).

This check runs from an independent GitHub Actions runner using **no credentials**. It sends three requests that must be rejected before a tool can execute, and checks OAuth protected-resource metadata. It writes no records, enrols no agents, does not modify Access policies, and does not attempt a real token refresh or log into another person's identity.

## Automated matrix

| Case | Expected | What it proves |
| --- | --- | --- |
| Anonymous `tools/list` | HTTP 401 + Bearer challenge | Portal does not anonymously enumerate tools |
| Anonymous `tools/call` (`shards_gateway_status`) | HTTP 401 | Tool invocation requires portal authentication |
| Deliberately invalid Bearer token + `tools/call` | HTTP 401 | Invalid token does not reach tool execution |
| `GET /.well-known/oauth-protected-resource/mcp` | HTTP 200 with valid JSON resource and HTTPS authorization server | OAuth protected-resource discovery remains accessible |

### Run

- Offline fixture tests: `node --test scripts/portal_boundary_check.test.mjs`.
- Live tests: `node scripts/portal_boundary_check.mjs` (requires public network access to the real portal; intentionally uses no secrets).
- GitHub: **Actions → Cloudflare MCP portal boundary (read-only) → Run workflow**, or open a PR changing the check.
- Once merged into `main`, the same four read-only HTTP checks are scheduled daily at **09:23 UTC**. GitHub Actions may delay scheduled workflows; a schedule is not an SLA or paging service.
- Results include probe names, verdict, portal origin, validation time, HTTP statuses and Bearer challenge presence only; they never log bearer credentials, session cookies, email addresses or response bodies.

## What this does *not* prove

- **A different authenticated identity denied**: requires a separate, genuinely authenticated principal. Cloudflare Account Member login may reject unknown members **before** the portal policy is evaluated. Do not weaken your identity-provider settings merely to manufacture a denial.
- **OAuth positive flow**: a live authorised session, correct audience and tool-call response must be verified through an independently connected MCP client, with corresponding Cloudflare portal analytics. The public CI check intentionally has no OAuth credentials.
- **Private tool scopes and cross-agent isolation**: test with separate synthetic enrolled agent tokens in a disposable database; never expose agent tokens to CI logs.
- **Uptime, load tolerance, retries, restart and external effects**: a 4-probe negative boundary suite is not a load test or a production certification.
- **Public upstream**: the three upstream read-only tools are intentionally anonymously callable; their exposure is a **separate** risk and must not be confused with protection by the portal.

**Promotion gate:** Any unexpected 2xx or redirect for a protected tool is a fail. A green workflow means only that these specific anonymous/invalid-token boundaries passed at that time; it is not proof of full production readiness.
