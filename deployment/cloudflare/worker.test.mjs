import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

const src = fs.readFileSync(new URL("./worker.js", import.meta.url), "utf8");
const sandbox = {
  Request, Response, Headers, URL, TextEncoder, TextDecoder, crypto: webcrypto, AbortSignal,
  fetch: async () => { throw new Error("test must never call the network"); },
};
vm.runInNewContext(src.replace("export default {", "globalThis.__edge = {"), sandbox, { filename: "worker.js" });
const worker = sandbox.__edge;
const endpoint = "https://mcp.shardsinc.co.uk/mcp";
function post(method, params = {}, headers = {}) {
  return new Request(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
}

test("initialize negotiates requested legacy version, not HTTP header default", async () => {
  for (const version of ["2025-06-18", "2025-11-25"]) {
    const response = await worker.fetch(post("initialize", {
      protocolVersion: version, capabilities: {}, clientInfo: { name: "offline-test", version: "1" },
    }), {});
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.result.protocolVersion, version);
    assert.equal(response.headers.get("mcp-protocol-version"), version);
  }
  const response = await worker.fetch(post("initialize", { protocolVersion: "unsupported" }), {});
  assert.equal((await response.json()).result.protocolVersion, "2025-11-25");
});

test("malformed DNS calls are rejected without consuming any budget or contacting DoH", async () => {
  let writes = 0;
  const env = { EDGE_DB: { prepare() { writes++; throw Error("DB should not be touched"); } } };
  for (const value of [{ domain: "bad" }, { domain: "example.com", type: "A;DROP" }, {}]) {
    const response = await worker.fetch(post("tools/call", {
      name: "shards_dns_lookup", arguments: value,
    }), env);
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /Invalid DNS arguments/);
  }
  assert.equal(writes, 0);
});

test("public status quotas use a hashed per-caller key plus global counter", async () => {
  const budgets = [];
  const env = {
    EDGE_DB: {
      prepare(sql) {
        assert.match(sql, /route_budgets/);
        return { bind(...values) {
          budgets.push(values);
          return { async run() { return { meta: { changes: 1 } }; } };
        } };
      },
    },
  };
  const response = await worker.fetch(post("tools/call", {
    name: "shards_gateway_status", arguments: {},
  }, { "cf-connecting-ip": "198.51.100.80" }), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.result.isError, false);
  assert.equal(budgets.length, 2);
  assert.match(budgets[0][1], /^public:shards_gateway_status:caller:[a-f0-9]{24}$/);
  assert.equal(budgets[1][1], "shards_gateway_status");
  assert.equal(JSON.stringify(budgets).includes("198.51.100.80"), false);
});

test("operator issued-token rendering uses newline escapes, not literal backslashes", () => {
  const match = src.match(/^const CLIENT=("(?:\\.|[^"\\])*");/m);
  assert.ok(match, "embedded client source must be present");
  const client = JSON.parse(match[1]);
  const at = client.indexOf("SCOPED TOKEN — COPY NOW.");
  assert.ok(at >= 0);
  const fragment = client.slice(at, at + 145);
  assert.ok(fragment.includes("\\n\\n"), "embedded JS must contain proper newline escape sequences");
  assert.equal(fragment.includes("\\\\n"), false, "embedded JS must not contain literal \\n");
});


test("Live Lab is a real same-origin route with a strict script policy", async () => {
  const response = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/lab"), {});
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/html/);
  const csp = response.headers.get("content-security-policy");
  assert.match(csp, /script-src 'self'/);
  assert.match(csp, /form-action 'none'/);
  assert.match(csp, /connect-src 'self'/);
  assert.doesNotMatch(csp, /unsafe-eval|script-src 'unsafe-inline'/);
  const html = await response.text();
  assert.match(html, /RUN PROTOCOL CHECK/);
  assert.match(html, /QUERY LIVE CATALOGUE/);
  assert.match(html, /id="dnsForm"/);
  assert.match(html, /src="\/lab\.js"/);
  assert.doesNotMatch(html, /<script(?![^>]*src=)/);
});

test("Live Lab client is executable JS restricted to the public MCP operations", async () => {
  const response = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/lab.js"), {});
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/javascript/);
  const js = await response.text();
  assert.doesNotThrow(() => new vm.Script(js));
  assert.match(js, /shards_gateway_status/);
  assert.match(js, /shards_systems_catalog/);
  assert.match(js, /shards_dns_lookup/);
  assert.match(js, /credentials: 'omit'/);
  assert.match(js, /response\.ok/);
  assert.match(js, /\.isError/);
  assert.doesNotMatch(js, /\/manage\/api\//);
  assert.doesNotMatch(js, /localStorage|sessionStorage|Bearer\s/);
});

test("Live Lab appears on the landing page, but never exposes cross-host routes", async () => {
  const main = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/"), {});
  assert.equal(main.status, 200);
  assert.match(await main.text(), /href="\/lab">LIVE LAB/);
  const denied = await worker.fetch(new Request("https://example.com/lab"), {});
  assert.equal(denied.status, 404);
  const missing = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/lab-other"), {});
  assert.equal(missing.status, 404);
});

test("Lab diagnostics do not require credentials; protected MCP tools still fail closed", async () => {
  const discovery = await worker.fetch(post("tools/list"), {});
  const listed = (await discovery.json()).result.tools.map(x => x.name);
  assert.deepEqual(Array.from(listed), [
    "shards_gateway_status", "shards_systems_catalog", "shards_dns_lookup"
  ]);
  const forbidden = await worker.fetch(post("tools/call", {name:"shards_task_create", arguments:{}}), {});
  const body = await forbidden.json();
  assert.equal(body.result.isError, true);
  assert.match(body.result.content[0].text, /AUTH_REQUIRED/);
});
