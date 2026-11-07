"use client";

import { useState } from "react";

type Client = "cursor" | "claude" | "codex" | "vscode" | "antigravity" | "other";
type Transport = "stdio" | "remote";

const clients: Array<{ id: Client; name: string; note: string }> = [
  { id: "cursor", name: "Cursor", note: "MCP server configuration; validate against installed Cursor release." },
  { id: "claude", name: "Claude Code", note: "CLI or MCP configuration; confirm your installed CLI's syntax." },
  { id: "codex", name: "Codex", note: "MCP server configuration in the Codex CLI/IDE." },
  { id: "vscode", name: "VS Code", note: "MCP configuration supported by your VS Code version." },
  { id: "antigravity", name: "Antigravity", note: "Verify current MCP client and transport support before applying." },
  { id: "other", name: "Other IDE", note: "Any client supporting MCP stdio or Streamable HTTP." },
];

function configuration(client: Client, transport: Transport, endpoint: string) {
  if (transport === "stdio") {
    const server = {
      command: "shards-mcp-stdio",
      env: {
        SHARDS_GATEWAY_URL: endpoint,
        SHARDS_AGENT_TOKEN: "<GATEWAY_ACCESS_TOKEN>",
      },
    };
    if (client === "vscode") return JSON.stringify({ servers: { shards: { type: "stdio", ...server } } }, null, 2);
    if (client === "codex") return [
      "[mcp_servers.shards]",
      'command = "shards-mcp-stdio"',
      "",
      "[mcp_servers.shards.env]",
      `SHARDS_GATEWAY_URL = "${endpoint}"`,
      'SHARDS_AGENT_TOKEN = "<GATEWAY_ACCESS_TOKEN>"',
    ].join("\n");
    return JSON.stringify({ mcpServers: { shards: server } }, null, 2);
  }
  if (client === "codex") return [
    "[mcp_servers.shards]",
    `url = "${endpoint.replace(/\/$/, "")}/mcp"`,
    'bearer_token_env_var = "SHARDS_AGENT_TOKEN"',
  ].join("\n");
  if (client === "vscode") return JSON.stringify({
    servers: { shards: { type: "http", url: endpoint.replace(/\/$/, "") + "/mcp",
      headers: { Authorization: "Bearer ${input:shardsAgentToken}" } } },
    inputs: [{ id: "shardsAgentToken", type: "promptString", description: "Gateway access token (local or OAuth, depending on mode)", password: true }],
  }, null, 2);
  return JSON.stringify({ mcpServers: {
    shards: { type: "http", url: endpoint.replace(/\/$/, "") + "/mcp",
      headers: { Authorization: "Bearer <GATEWAY_ACCESS_TOKEN>" } },
  } }, null, 2);
}

export function ConnectionHub() {
  const [client, setClient] = useState<Client>("cursor");
  const [transport, setTransport] = useState<Transport>("stdio");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8787");
  const [copied, setCopied] = useState(false);
  const valid = (() => {
    try {
      const url = new URL(endpoint);
      const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
      return !url.username && !url.password && !url.search && !url.hash &&
        (url.pathname === "/" || url.pathname === "") &&
        (url.protocol === "https:" || (url.protocol === "http:" && loopback));
    } catch { return false; }
  })();
  const selected = clients.find(item => item.id === client)!;
  const instructions: Record<Client, string> = {
    cursor: "Open Cursor Settings → MCP, add a custom MCP server and adapt the generated configuration to the installed version.",
    claude: "Use Claude Code's MCP configuration or its mcp add command. Check the installed CLI help before importing the example.",
    codex: "Edit the Codex MCP server configuration (typically config.toml) and restart the client.",
    vscode: "Use the VS Code MCP configuration interface or workspace .vscode/mcp.json. Avoid committing credentials.",
    antigravity: "Locate Antigravity's MCP server settings and confirm that the selected transport is supported by your installed release.",
    other: "Open the client's MCP server configuration and map the transport, command or URL and authentication settings.",
  };
  const snippet = valid ? configuration(client, transport, endpoint) : "";
  return <section className="panel" aria-labelledby="connections-title">
    <div className="eyebrow">DEVELOPER CONNECTIVITY</div>
    <h2 id="connections-title">IDE Connection Hub</h2>
    <p>Select a client and generate a starter configuration for the existing Shards MCP gateway.</p>
    <div className="connection-fields">
      <label>Client<select value={client} onChange={event => { setClient(event.target.value as Client); setCopied(false); }}>
        {clients.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label>Transport<select value={transport} onChange={event => { setTransport(event.target.value as Transport); setCopied(false); }}>
        <option value="stdio">Local stdio bridge (recommended initially)</option>
        <option value="remote">Remote Streamable HTTP (client support required)</option>
      </select></label>
      <label>Gateway base URL<input value={endpoint} spellCheck={false} onChange={event => { setEndpoint(event.target.value); setCopied(false); }}/></label>
    </div>
    <p><strong>Setup:</strong> {instructions[client]}</p>
    <p className="muted">{selected.note} These examples are starting points, not verified against every IDE release.</p>
    {transport === "stdio" && <p className="muted">Prerequisite: install the Shards MCP Python package on the same machine as the IDE, so the <code>shards-mcp-stdio</code> executable is on PATH. The gateway itself may run elsewhere.</p>}
    {transport === "remote" && <p className="muted">Prerequisite: the selected client must support Streamable HTTP MCP and bearer-token authentication. The gateway must be reachable from the IDE; localhost refers to the IDE machine. Off-loopback deployments require SHARDS_AUTH_MODE=oauth: enrol the identity with the admin CLI --oauth-subject option and obtain a scoped access JWT from the trusted issuer. Local agent tokens are rejected in OAuth mode.</p>}
    {!valid ? <p role="alert">Use an HTTPS gateway URL or local loopback HTTP, with no path, query or embedded credentials.</p> :
      <><pre className="snippet"><code>{snippet}</code></pre>
      <button className="action" type="button" onClick={() => {
        void navigator.clipboard.writeText(snippet).then(() => setCopied(true)).catch(() => setCopied(false));
      }}>{copied ? "Copied" : "Copy configuration"}</button></>}
    <p className="muted">Never use the bootstrap administrator token. Local-token mode requires a separate least-privilege token per IDE; OAuth mode requires an issuer-signed scoped access JWT for an enrolled subject. Store credentials securely. JSON examples contain placeholders, not live credentials.</p>
    <p className="muted">Validate the connection with <code>shards-mcp-doctor --protocol both --json</code> using that client's scoped credential from a trusted machine.</p>
  </section>;
}
