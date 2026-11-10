import test from "node:test";
import assert from "node:assert/strict";
import { CLIENTS, MCP_ENDPOINT, clientPayload, clientSteps, cursorInstallUrl } from "../lib/connectors.ts";

test("all seven client integrations have actionable instructions", () => {
  assert.equal(CLIENTS.length, 7);
  for (const client of CLIENTS) {
    assert.ok(clientPayload(client.id).includes(MCP_ENDPOINT));
    assert.ok(clientSteps(client.id).length >= 3);
    assert.ok(client.docs.startsWith("https://"));
  }
});
test("Cursor config is valid and never embeds a credential", () => {
  const parsed = JSON.parse(clientPayload("cursor-app"));
  assert.equal(parsed.mcpServers.shards.url, MCP_ENDPOINT);
  assert.equal(JSON.stringify(parsed).includes("TOKEN"), false);
});
test("supported CLI syntax and endpoint", () => {
  assert.match(clientPayload("claude-code"), /^claude mcp add --transport http/);
  assert.match(clientPayload("codex-cli"), /^codex mcp add shards --url/);
  assert.equal(clientPayload("chatgpt"), MCP_ENDPOINT);
  assert.equal(clientPayload("claude-desktop"), MCP_ENDPOINT);
});

test("Cursor native install link encodes only a bare server entry", () => {
  const link = new URL(cursorInstallUrl());
  assert.equal(link.protocol, "cursor:");
  assert.equal(link.searchParams.get("name"), "shards");
  const config = JSON.parse(Buffer.from(link.searchParams.get("config") ?? "", "base64").toString("utf8"));
  assert.deepEqual(config, { url: MCP_ENDPOINT });
});

test("Codex onboarding never advertises an unavailable edge OAuth login command", () => {
  assert.equal(clientPayload("codex-cli").includes("codex mcp login"), false);
  assert.match(clientSteps("codex-app").join(" "), /Private tools remain unavailable/);
});
