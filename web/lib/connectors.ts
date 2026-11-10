export const MCP_ENDPOINT = "https://mcp.shardsinc.co.uk/mcp" as const;
export type ClientId = "cursor-app" | "cursor-cli" | "claude-desktop" | "claude-code" | "chatgpt" | "codex-app" | "codex-cli";
export type ConnectMode = "config" | "command" | "url";

export const CLIENTS: ReadonlyArray<{ id: ClientId; name: string; category: string; mode: ConnectMode; docs: string }> = [
  { id: "cursor-app", name: "Cursor", category: "Desktop IDE", mode: "config", docs: "https://prod.cursor.com/docs/mcp/install-links" },
  { id: "cursor-cli", name: "Cursor CLI", category: "Terminal agent", mode: "config", docs: "https://docs.cursor.com/en/cli/reference/parameters" },
  { id: "claude-desktop", name: "Claude Desktop", category: "Desktop AI", mode: "url", docs: "https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp" },
  { id: "claude-code", name: "Claude Code", category: "Terminal agent", mode: "command", docs: "https://code.claude.com/docs/en/mcp" },
  { id: "chatgpt", name: "ChatGPT", category: "AI workspace", mode: "url", docs: "https://developers.openai.com/plugins/build/app-quickstart" },
  { id: "codex-app", name: "Codex app", category: "Developer agent", mode: "command", docs: "https://developers.openai.com/resources/docs-mcp" },
  { id: "codex-cli", name: "Codex CLI", category: "Terminal agent", mode: "command", docs: "https://developers.openai.com/resources/docs-mcp" },
];

export function clientPayload(id: ClientId) {
  switch (id) {
    case "cursor-app":
    case "cursor-cli":
      return JSON.stringify({ mcpServers: { shards: { url: MCP_ENDPOINT } } }, null, 2);
    case "claude-code":
      return `claude mcp add --transport http --scope user shards ${MCP_ENDPOINT}\nclaude mcp list`;
    case "codex-app":
    case "codex-cli":
      return `codex mcp add shards --url ${MCP_ENDPOINT}\ncodex mcp list\ncodex mcp login shards`;
    case "claude-desktop":
    case "chatgpt":
      return MCP_ENDPOINT;
  }
}

export function clientSteps(id: ClientId): string[] {
  switch (id) {
    case "cursor-app": return ["Select Install in Cursor to import the remote server configuration.", "Approve the installation in Cursor, then complete the MCP OAuth flow when prompted.", "Verify that the shards tools appear and check the granted scopes."];
    case "cursor-cli": return ["Save the generated JSON as ~/.cursor/mcp.json (merge with any existing servers).", "Run cursor-agent mcp login shards and complete the browser authentication.", "Run cursor-agent mcp list and cursor-agent mcp list-tools shards."];
    case "claude-desktop": return ["Open Claude → Customize → Connectors → Add custom connector.", "Name it Shards MCP, paste the endpoint, and choose the supported OAuth configuration.", "Authorise and enable the connector, then inspect its available tools."];
    case "claude-code": return ["Run the generated commands in your terminal.", "Use /mcp in Claude Code and complete authentication if offered.", "Verify the server is listed and tool calls execute with your enrolled identity."];
    case "chatgpt": return ["Open ChatGPT → Plugins → Add custom MCP server.", "Paste the endpoint and configure OAuth for the Shards MCP service.", "Install the resulting plugin and test the scoped tools in a chat."];
    case "codex-app": return ["Run the generated commands using the Codex CLI; the IDE/app shares its MCP configuration.", "Complete the OAuth browser flow when requested.", "Open Codex and verify your Shards server and its tool access."];
    case "codex-cli": return ["Run the generated commands using the Codex CLI.", "Complete the OAuth browser flow when requested.", "Ask Codex to list the Shards MCP tools and call agent_identity."];
  }
}

export function cursorInstallUrl() {
  // Cursor documents config as a base64-encoded JSON map of server name to settings.
  const config = JSON.stringify({ shards: { url: MCP_ENDPOINT } });
  // Browser-only: btoa deliberately called by the client UI on click/render.
  return `cursor://anysphere.cursor-deeplink/mcp/install?name=shards&config=${encodeURIComponent(btoa(config))}`;
}
