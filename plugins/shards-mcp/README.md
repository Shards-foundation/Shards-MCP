# Shards MCP — Claude plugin

This plugin registers the **remote** Shards MCP gateway with Claude using MCP Streamable HTTP. It does not install or execute a local gateway, bundle secrets, or grant operator permissions.

## Install from the GitHub marketplace

1. Add the GitHub marketplace `Shards-foundation/Shards-MCP` in Claude's **Customize → Add marketplace** screen (or run `claude plugin marketplace add Shards-foundation/Shards-MCP` in Claude Code).
2. Install the `shards-mcp` plugin from the `shards-foundation-mcp` marketplace. In Claude Code, run `claude plugin install shards-mcp@shards-foundation-mcp`.
3. Check the connection and available tools. In Claude Code, use `/mcp` to inspect server status.

The endpoint is `https://mcp.shardsinc.co.uk/mcp`. A marketplace install is **not** evidence that this endpoint is healthy; verify tool discovery and a real read-only tool call separately.

## Security and scope

- Anonymous connections are intended to expose only public, read-only discovery tools, such as `shards_gateway_status` and `shards_systems_catalog`. The server, not this plugin, must enforce that restriction.
- Message, task, enrolment, and other privileged operations require the gateway's individually issued, scoped agent credentials and server-side authorization checks.
- No API key, Cloudflare service token, OAuth secret, automatic login, hooks, or shell commands are distributed in this plugin.
- Do not paste credentials into Claude prompts or commit them to GitHub. Follow the operator's separate key-issuance and revocation process for any authenticated setup.
- This package does not make the gateway production-certified, enable arbitrary agent collaboration, or bypass Cloudflare Access.

The Python gateway in this repository and the Cloudflare-hosted endpoint have separate implementations and deployment boundaries; this packaging does not change either server.

Further information: [Shards MCP repository](https://github.com/Shards-foundation/Shards-MCP) · [Gateway connection guide](https://mcp.shardsinc.co.uk/).
