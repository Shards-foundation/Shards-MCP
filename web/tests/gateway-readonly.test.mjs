import test from "node:test";
import assert from "node:assert/strict";
import {
  gatewayOrigin, InventoryError, isLocalAgentToken, invokeReadTool,
  readBoundedJson, requireReadOnlyIdentity, sanitiseInventory,
} from "../lib/gateway-readonly.ts";

const agentId = "agt_" + "a".repeat(24);
const scopedToken = "shards_" + "A".repeat(48);
const validAgent = {
  id: agentId,
  name: "reviewer",
  provider: "local",
  scopes: ["agent:read"],
  revoked: false,
  heartbeat_state: "unobserved",
  last_seen: null,
};

function rejectsState(action, expected) {
  assert.throws(action, error =>
    error instanceof InventoryError && error.state === expected);
}
async function rejectsAsyncState(action, expected) {
  await assert.rejects(action, error =>
    error instanceof InventoryError && error.state === expected);
}

test("only explicit origins are accepted, with loopback HTTP only", () => {
  for (const value of [
    "http://localhost:8787", "http://127.0.0.1:8787/",
    "http://[::1]:8787", "https://Gateway.Example.test", "https://gateway.example.test:443/",
  ]) {
    assert.ok(gatewayOrigin(value) instanceof URL, value);
  }
  for (const value of [
    "", " http://localhost:8787", "https://gateway.example.test\n",
    "https://gate\u00a0way.example.test", "https://gateway.example.test\u2028",
    "https://gateway.example.test/path", "https://gateway.example.test/..",
    "https://gateway.example.test?", "https://gateway.example.test#",
    "https://gateway.example.test/#", "https://gateway.example.test\\@evil.test",
    "https://user:password@gateway.example.test",
    "http://gateway.example.test", "http://[::1]evil:8787",
    "https://gateway.example.test:0", "https://[::1",
  ]) {
    rejectsState(() => gatewayOrigin(value), "configuration_error");
  }
});

test("local gateway credential must match the scoped agent issuer format", () => {
  assert.equal(isLocalAgentToken(scopedToken), true);
  for (const token of ["", "secret", "Bearer abc", "shards_short", "shards_" + "x".repeat(49)]) {
    assert.equal(isLocalAgentToken(token), false);
  }
});

test("agent directory read rejects broad and unrelated principals", () => {
  assert.doesNotThrow(() => requireReadOnlyIdentity({
    role: "agent", agent_id: agentId, scopes: ["agent:read"],
  }));
  for (const identity of [
    { role: "operator", agent_id: "operator", scopes: ["*"] },
    { role: "agent", agent_id: agentId, scopes: ["*"] },
    { role: "agent", agent_id: agentId, scopes: ["agent:read", "task:create"] },
    { role: "agent", agent_id: agentId, scopes: ["task:read"] },
    { role: "agent", agent_id: "wrong", scopes: ["agent:read"] },
    null,
  ]) {
    rejectsState(() => requireReadOnlyIdentity(identity), "permission_denied");
  }
});

test("inventory strips unexpected backend fields and preserves real heartbeat state", () => {
  const raw = { ...validAgent, token_hash: "MUST_NOT_LEAK", oauth_subject: "subject" };
  const agents = sanitiseInventory([raw]);
  assert.deepEqual(agents, [validAgent]);
  assert.equal(JSON.stringify(agents).includes("MUST_NOT_LEAK"), false);
});

test("inventory rejects invalid or excessive upstream data", () => {
  for (const value of [
    {},
    new Array(501).fill(validAgent),
    [{ ...validAgent, scopes: ["agent:read", 7] }],
    [{ ...validAgent, heartbeat_state: "always-alive" }],
    [{ ...validAgent, revoked: "false" }],
    [{ ...validAgent, name: "x".repeat(201) }],
    [{ ...validAgent, id: "bad" }],
  ]) {
    rejectsState(() => sanitiseInventory(value), "invalid_gateway_response");
  }
});

test("response reader enforces application/json, UTF-8 and 256 KiB bound", async () => {
  const good = new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
  assert.deepEqual(await readBoundedJson(good), { ok: true });
  await rejectsAsyncState(
    () => readBoundedJson(new Response("x", { headers: { "Content-Type": "text/html" } })),
    "invalid_gateway_response",
  );
  await rejectsAsyncState(
    () => readBoundedJson(new Response("x".repeat(262145), {
      headers: { "Content-Type": "application/json" },
    })),
    "invalid_gateway_response",
  );
});

test("fixed tool call sends bearer only to configured host with redirects disabled", async () => {
  const url = gatewayOrigin("https://gateway.example.test");
  const seen = [];
  const answer = await invokeReadTool(url, scopedToken, "agent_list", async (input, options) => {
    seen.push({ input: String(input), options });
    return new Response(JSON.stringify({ ok: true, result: [validAgent] }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  });
  assert.deepEqual(answer, [validAgent]);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].input, "https://gateway.example.test/v1/tools/agent_list");
  assert.equal(seen[0].options.method, "POST");
  assert.equal(seen[0].options.body, "{}");
  assert.equal(seen[0].options.redirect, "manual");
  assert.equal(seen[0].options.headers.Authorization, "Bearer " + scopedToken);
});

test("upstream access failures and redirects fail closed", async () => {
  const url = gatewayOrigin("https://gateway.example.test");
  for (const [response, expected] of [
    [new Response("{}", { status: 403 }), "permission_denied"],
    [new Response("", { status: 302, headers: { Location: "https://evil.test" } }), "gateway_unavailable"],
    [new Response('{"ok":false}', { status: 200, headers: { "Content-Type": "application/json" } }), "invalid_gateway_response"],
  ]) {
    await rejectsAsyncState(
      () => invokeReadTool(url, scopedToken, "agent_identity", async () => response),
      expected,
    );
  }
});
