---
name: client-integration
description: Configure and verify MCP connectivity for Claude Desktop, Claude Code, ChatGPT, Codex app or CLI, Cursor app or CLI, and other protocol clients. Use when implementing real client onboarding, choosing transport, testing OAuth scopes or troubleshooting client setup.
---
# Client integration — one MCP gateway, per-client credentials

**Trigger:** connect a client, build a native install/configuration flow, or validate a claimed client integration. This skill does not automatically grant OAuth access or certify a marketplace listing.

## Preconditions

- Determine the **actual** deployed endpoint and whether it is the Python gateway or separate Cloudflare edge. Do not assume functional parity.
- Confirm the client/version supports the selected wire protocol and transport. Remote URLs must use HTTPS; do not send secrets to a third-party redirect.
- Separate public tool discovery from protected operations. Existing Cloudflare edge `smcp_*` tokens are not a substitute for OAuth 2.1.

## Inputs

Exact client name/version/platform; desired tools and minimal scopes; confirmed endpoint; identity provider and issuer metadata; client diagnostics; capability and deployment boundaries.

## Procedure

1. Inspect `docs/interoperability.md`, `docs/integrations.md`, `docs/agent-onboarding.md`, `web/app/connection-hub.tsx` and the actual server implementation.
2. Choose local `shards-mcp-stdio` bridge **or** native Streamable HTTP. Do not represent an HTTP JSON-RPC subset as full protocol support.
3. Generate a credential-free **local configuration** from the Shards source checkout using `python skills/client-integration/scripts/generate_config.py --client cursor-app` (or `--client claude-code`, `codex-cli`, `claude-desktop`, `chatgpt`). It prints commands or connector instructions but **does not install**, connect or authenticate. Review the installed client's **current documented syntax** before using any commands. Common paths: Claude Code `claude mcp add`; Codex `codex mcp add`; Cursor MCP server config/deep link; Claude Desktop and ChatGPT via supported remote connector/App flows. Never fabricate a working one-click installer where the client requires interactive consent.
   When this skill is copied to a native client skill directory, its bundled generator can instead be invoked as `python scripts/generate_config.py` **from that installed skill directory**; source-repository paths elsewhere in this workflow still require the full checkout.
4. For Cursor install links the base64 `config` parameter contains the **bare individual server entry** (e.g. `{"url":"https://…/mcp"}`), while a local `mcp.json` uses `{"mcpServers":{"shards":{...}}}`. The `name=shards` query value is separate. Review [Cursor install-link documentation](https://cursor.com/docs/mcp/install-links) before shipping and test the link in the real installed Cursor client. 
5. Provision **distinct scoped identities** through an authorised operator where necessary. Never put `SHARDS_ADMIN_TOKEN` or any bearer token in `mcp.json`, the browser, a PR or screenshots. Prefer credential store/interactive OAuth where supported.
6. Verify transport handshake, `tools/list` and safe identity call with the **real client**. Check explicit 401/403 denials, cross-agent isolation, unknown tools and token revocation; do not accept merely importing JSON as a success.
7. For automation, script only safe local config generation and diagnostic commands; authenticate separately through a supported provider. Record exact client version and tested wire version.

## Verification

Record protocol date/version, TLS certificate, scope result, client-side tool list, challenge/consent behaviour, denial tests, observed side effects and dated command logs. Compare the Python gateway and edge separately.

## Failure handling

If the issuer, consent, callback URL, JWKS or OAuth audience is absent, mark **BLOCKED_AUTH**, never silently switch to a shared admin key. If the client cannot use the required transport, mark **BLOCKED_CLIENT** and provide an explicit supported alternative.

## Output

**Output:** tested platform and version, endpoint, transport, config path (no secret), actual authenticated principal/scopes, handshake PASS/FAIL/BLOCKED, tool call PASS/FAIL/BLOCKED and next remediation.
