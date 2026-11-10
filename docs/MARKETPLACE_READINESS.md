# Shards-MCP distribution and marketplace gates

**Source:** https://github.com/Shards-foundation/Shards-MCP

**Public edge MCP endpoint:** https://mcp.shardsinc.co.uk/mcp

**Onboarding portal:** https://mcp.shardsinc.co.uk

**Operator authentication:** https://mcp.shardsinc.co.uk/manage

**Status:** Deployment and public read-only MCP acceptance verified. **No marketplace listing or approval is claimed.** All platform/provider marketplace publications remain an external review process.

## Listing targets are not interchangeable

| Destination | Type | Shards-MCP submission state | Required next action |
| --- | --- | --- | --- |
| [MCP Market](https://mcpmarket.com/) | MCP service directory | Not submitted | Check current listing terms, submit hosted endpoint/docs and security disclosures |
| [MCP Marketplace](https://mcp-marketplace.io/) | MCP directory | Not submitted | Validate registration requirements and provide tested metadata |
| [OpenAI business marketplace](https://openai.com/business/marketplace/) | Enterprise/app distribution | Not submitted | Complete ChatGPT plugin vetting and OAuth/client interoperability before seeking listing |
| [Claude marketplace](https://claude.com/marketplace) | Claude tools/connectors ecosystem | Not submitted | Establish supported remote MCP auth, publish developer docs and apply under correct partner track |
| [Microsoft Marketplace](https://marketplace.microsoft.com/en-us/) | Business SaaS/app marketplace | Not submitted | Commercial legal entity, tenant app model, Microsoft integration/auth requirements and app review |
| [Google Workspace Marketplace](https://workspace.google.com/marketplace/category/popular-apps) | Workspace app marketplace | Not submitted | A functional Workspace add-on/integration, Google OAuth verification and privacy documentation |
| [GitHub Marketplace](https://github.com/marketplace) | GitHub Apps/Actions commerce | Not submitted | Implement a real GitHub App or Action with correct webhook/OAuth/scopes, not simply an MCP URL |
| [Oracle Marketplace](https://marketplace.oracle.com/) | Enterprise cloud marketplace | Not submitted | Applicable Oracle integration or deployable offer and vendor programme conditions |
| [Discadia](https://discadia.com/) | Discord community directory | Not submitted | List a real Shards community/server under directory policy; not a gateway MCP integration |
| [Top.gg](https://top.gg/) | Discord bot/server directory | Not submitted | Have an actual compliant Discord bot or server listing; a bare MCP URL cannot be a bot listing |

Marketplace link buttons in the portal **navigate to provider websites; they do not apply for or install the application**. Never imply otherwise.

## Public plugin foundation

- `deployment/cloudflare/mcp.json` is a portable remote HTTP MCP configuration for the 3 public tools, with no credential embedded.
- The existing repository-root `mcp.json` remains the **local Python stdio gateway**, so the existing installation does not break.
- For Cursor, the portal generates the actual `cursor://anysphere.cursor-deeplink/mcp/install?...` link. The user still must approve it.
- For Claude Desktop, Claude Code, ChatGPT, Codex and Cursor CLI, buttons open official clients/docs or copy genuine configuration; these platforms do not all support arbitrary remote one-click installation.
- `shards-mcp-connect` is an opt-in local installer; `--install` is required to modify Cursor configuration or invoke an installed CLI. It does not install third-party software.

## Prerequisites before public listing

1. **Identity:** production end-user OAuth 2.1 resource server metadata, PKCE flow, token issuer, refresh tokens and/or secure client registration; do not market Cloudflare Access operator console as a turnkey OAuth sign-in for ChatGPT.
2. **Security:** independent audit, per-user quotas, WAF/rate limiting, retention, breach response, token expiry/revocation tests, multi-tenant isolation and least privilege.
3. **Product:** real Python gateway federation if offering full Shards-A2A semantics; validate clients against MCP SDK versions and test write operations under explicit permission controls.
4. **Compliance:** Terms of Service, privacy notice, subprocessors, DPA where required, copyright, licence, incident contact, support and acceptable use.
5. **Listing:** create platform-specific app manifests/icons, test published connect flow, publish docs, satisfy provider terms and submit for review.
6. **Evidence:** build a version-pinned acceptance matrix for each MCP host and security/auth mode; preserve request/response evidence without secrets.

### Independent external marketplaces do not grant authentication

A listing is a discovery surface. It does not automatically register an OAuth client, grant API privileges, provision tenant credentials or connect Claude/ChatGPT/Codex. Those are separate product and security gates.

## Current endpoints to test

```text
https://mcp.shardsinc.co.uk
https://mcp.shardsinc.co.uk/mcp
https://mcp.shardsinc.co.uk/api/status
https://mcp.shardsinc.co.uk/manage
```

The hosted Worker has no direct shell execution or tool federation. Hosted internal tasks are coordination records, not remotely executed jobs.
