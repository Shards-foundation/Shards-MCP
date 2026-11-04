# Portable Agent Plugins package

This repository includes Agent Plugins 1.0.0 portable metadata:
- plugin.json: package name/version/author metadata.
- mcp.json: a **local stdio** server entry that runs shards-mcp-stdio.

The stdio command must be installed on PATH using the shards-mcp Python distribution before enabling this plugin. It does not start the persistent gateway automatically.

Run a separately configured gateway first. For each AI client, provide SHARDS_GATEWAY_URL and an independently issued SHARDS_AGENT_TOKEN in that client's protected runtime environment, not in mcp.json or a repository. Do not inherit the gateway bootstrap administrator token. If either environment value is unavailable, the bridge fails closed.

Only MCP-capable clients that support local stdio processes can install this package without an adapter. Mobile or web hosted clients often require remote HTTPS MCP, which is not deployed in this repository.

The 1.0.0 portable package format is separate from the MCP wire protocol version and does not itself certify protocol interoperability or grant directory publication approval.

Reference: https://agent-plugins.org/specification

## ChatGPT remote plugin work still required

Host the /mcp endpoint over public HTTPS or a supported secured tunnel. Implement and validate OAuth user authentication and resource metadata with an established identity provider; use tightly scoped tools for ChatGPT. Configure the connection through ChatGPT Plugins when the user's workspace supports custom MCPs. Execute real connection and tool-use tests. Public listings require the applicable platform review and publication process. This repository has no hosted URL to put into a remote manifest.
