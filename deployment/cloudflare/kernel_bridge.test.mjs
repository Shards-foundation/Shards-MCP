import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

const src = fs.readFileSync(new URL("./worker.js", import.meta.url), "utf8");
const endpoint = "https://mcp.shardsinc.co.uk/mcp";
const TENANT = "shards-internal";
const AGENT_ID = "agent-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const KERNEL_ORIGIN = "https://kernel.example.test";
const ACTOR = "edge-agent-alice";
const ACTOR_SECRET = "a".repeat(48);
const ACTOR_TOKEN = `${ACTOR}.${ACTOR_SECRET}`;
const GATEWAY_IDENTITY = "cloudflare-edge-prod";
const GATEWAY_TOKEN = "g".repeat(48);
const ACCESS_ID = "access-client-id-1234567890";
const ACCESS_SECRET = "access-client-secret-abcdefghijklmnop";
const SMCP_TOKEN = "smcp_" + "b".repeat(43);
const BRIDGE_TOOL = "shards_kernel_issue_label";

function loadWorker(fetchImpl) {
  const sandbox = {
    Request, Response, Headers, URL, TextEncoder, TextDecoder, crypto: webcrypto,
    AbortSignal, atob, btoa: globalThis.btoa,
    fetch: fetchImpl || (async () => { throw new Error("unexpected network"); }),
  };
  vm.runInNewContext(src.replace("export default {", "globalThis.__edge = {"), sandbox, { filename: "worker.js" });
  return { worker: sandbox.__edge, sandbox };
}

function makeActor(overrides = {}) {
  return {
    id: AGENT_ID,
    tenant_id: TENANT,
    name: "alice",
    client: "test",
    scopes: JSON.stringify(["agent:identity", "kernel:github_label"]),
    ...overrides,
  };
}

function makeDB(actor, { auth = true, writes = [] } = {}) {
  return {
    writes,
    prepare(sql) {
      return {
        bind(...values) {
          return {
            async first() {
              if (/FROM access_tokens/.test(sql)) return auth ? actor : null;
              if (/SELECT 1 AS ok/.test(sql)) return { ok: 1 };
              return null;
            },
            async run() {
              writes.push({ sql, values });
              return { meta: { changes: 1 } };
            },
            async all() { return { results: [] }; },
          };
        },
      };
    },
  };
}

function bridgeEnv(overrides = {}, actor = makeActor(), dbOptions = {}) {
  const env = {
    KERNEL_BRIDGE_ENABLED: "1",
    KERNEL_OPERATOR_ORIGIN: KERNEL_ORIGIN,
    KERNEL_ACCESS_CLIENT_ID: ACCESS_ID,
    KERNEL_ACCESS_CLIENT_SECRET: ACCESS_SECRET,
    KERNEL_GATEWAY_IDENTITY: GATEWAY_IDENTITY,
    KERNEL_GATEWAY_TOKEN: GATEWAY_TOKEN,
    KERNEL_ACTOR_MAP: JSON.stringify({ [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: ACTOR_TOKEN } }),
    KERNEL_LABEL_ALLOWLIST: JSON.stringify(["shards-agent"]),
    KERNEL_MAX_ISSUE_NUMBER: "100000",
    EDGE_DB: makeDB(actor, dbOptions),
  };
  return { ...env, ...overrides };
}

function post(method, params = {}, headers = {}) {
  return new Request(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
}

function authHeaders(token = SMCP_TOKEN) {
  return { authorization: `Bearer ${token}` };
}

function validPermit(overrides = {}) {
  return {
    permit_id: "c".repeat(64),
    issuer: "offline-operator-issuer",
    subject: ACTOR,
    jurisdiction: "default",
    action: "github.issue.add_label",
    params: { issue_number: 123, label: "shards-agent" },
    constraints: {},
    max_executions: 1,
    valid_from_ms: 1000,
    valid_until_ms: 2000,
    evidence_hash: "",
    proposal_hash: "approved-" + ACTOR,
    nonce: "n".repeat(64),
    signature: "a".repeat(128),
    key_id: "operator-policy-key-1",
    version: 2,
    algorithm: "Ed25519",
    audience: "github-issue-label-operator",
    ...overrides,
  };
}

function validArgs(overrides = {}) {
  return {
    issue_number: 123,
    label: "shards-agent",
    permit: validPermit(),
    request_id: "req-0001",
    ...overrides,
  };
}

function receipt(overrides = {}) {
  return {
    request_id: "req-0001",
    status: "ACCEPTED",
    decision: "ALLOW",
    state_from: "EXECUTING",
    state_to: "COMPLETED",
    ts_ms: 1234567890,
    result: {
      provider: "github",
      action: "add_label",
      operation_id: "op-1",
      state: "SUCCEEDED",
      issue_number: 123,
      label: "shards-agent",
      already_present: false,
      provider_ref: "https://api.github.com/repos/o/r/issues/123",
      detail: "VERIFIED_READBACK",
      reconciled: false,
    },
    error: null,
    evidence_hash: "e".repeat(64),
    ...overrides,
  };
}

function jsonResponse(status, body, headers = {}) {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function stubFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url: String(url), init });
    return handler(String(url), init, calls);
  };
  fn.calls = calls;
  return fn;
}

async function callTool(worker, env, args, headers = authHeaders()) {
  const res = await worker.fetch(post("tools/call", { name: BRIDGE_TOOL, arguments: args }, headers), env);
  const body = await res.json();
  return { res, body, result: body.result };
}

async function listTools(worker, env, headers) {
  const res = await worker.fetch(post("tools/list", {}, headers || {}), env);
  assert.equal(res.status, 200);
  return (await res.json()).result.tools.map((tool) => tool.name);
}

function assertNoSecrets(value) {
  const text = JSON.stringify(value);
  for (const secret of [GATEWAY_TOKEN, ACCESS_SECRET, ACTOR_TOKEN, SMCP_TOKEN, KERNEL_ORIGIN]) {
    assert.equal(text.includes(secret), false, "tool result must not contain a bridge credential or private origin");
  }
}

function assertDeniedWithoutDispatch(result, expectedReason) {
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent.applied, false);
  assert.equal(result.structuredContent.kernel_reached, false);
  assert.equal(result.structuredContent.retryable, false);
  if (expectedReason) assert.equal(result.structuredContent.reason_code, expectedReason);
  assertNoSecrets(result);
}

test("kernel bridge is disabled by default and hidden from discovery", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = { EDGE_DB: makeDB(makeActor()) };

  assert.equal((await listTools(worker, env)).length, 7);
  assert.equal((await listTools(worker, env, authHeaders())).includes(BRIDGE_TOOL), false);

  const status = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/api/status"), env);
  const body = await status.json();
  assert.equal(body.tools.filter((tool) => !tool.public).length, 9);

  const call = await callTool(worker, env, validArgs());
  assertDeniedWithoutDispatch(call.result, "BRIDGE_DISABLED");
  assert.equal(fetchStub.calls.length, 0);
});

test("kernel bridge is discoverable only for a verified actor with the new scope", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);

  const scoped = bridgeEnv();
  assert.equal((await listTools(worker, scoped, authHeaders())).includes(BRIDGE_TOOL), true);
  const status = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/api/status"), scoped);
  const body = await status.json();
  assert.equal(body.tools.filter((tool) => !tool.public).length, 10);
  assert.ok(body.tools.some((tool) => tool.name === BRIDGE_TOOL && tool.public === false));

  const unscoped = bridgeEnv({}, makeActor({ scopes: JSON.stringify(["agent:identity"]) }));
  assert.equal((await listTools(worker, unscoped, authHeaders())).includes(BRIDGE_TOOL), false);

  const anonymous = await listTools(worker, scoped);
  assert.equal(anonymous.length, 7);
  assert.equal(anonymous.includes(BRIDGE_TOOL), false);
  assert.equal(fetchStub.calls.length, 0);
});

test("anonymous, invalid, revoked, disabled, expired and wrong-tenant tokens never dispatch", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);

  const anonymous = await worker.fetch(post("tools/call", { name: BRIDGE_TOOL, arguments: validArgs() }), bridgeEnv());
  const anonymousBody = await anonymous.json();
  assert.equal(anonymousBody.result.isError, true);
  assert.match(anonymousBody.result.content[0].text, /AUTH_REQUIRED/);

  for (const label of ["invalid", "revoked", "disabled", "expired"]) {
    const env = bridgeEnv({}, makeActor(), { auth: false });
    const res = await worker.fetch(post("tools/call", { name: BRIDGE_TOOL, arguments: validArgs() }, authHeaders()), env);
    assert.equal(res.status, 401, label);
    assert.match(res.headers.get("www-authenticate"), /invalid_token/);
    assert.equal((await res.text()).includes(SMCP_TOKEN), false);
  }

  const wrongTenant = bridgeEnv({}, makeActor({ tenant_id: "other-tenant" }));
  const wrongTenantCall = await callTool(worker, wrongTenant, validArgs());
  assertDeniedWithoutDispatch(wrongTenantCall.result, "AGENT_NOT_MAPPED");

  const unmapped = bridgeEnv({}, makeActor({ id: "agent-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" }));
  const unmappedCall = await callTool(worker, unmapped, validArgs());
  assertDeniedWithoutDispatch(unmappedCall.result, "AGENT_NOT_MAPPED");

  assert.equal(fetchStub.calls.length, 0);
});

test("a missing scope is denied before any dispatch", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv({}, makeActor({ scopes: JSON.stringify(["agent:identity"]) }));
  const call = await callTool(worker, env, validArgs());
  assert.equal(call.result.isError, true);
  assert.match(call.result.content[0].text, /AUTH_REQUIRED/);
  assert.equal(fetchStub.calls.length, 0);
});

test("unsafe or incomplete bridge configuration fails closed before dispatch", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const cases = [
    { KERNEL_BRIDGE_ENABLED: "0" },
    { KERNEL_OPERATOR_ORIGIN: "http://kernel.example.test" },
    { KERNEL_OPERATOR_ORIGIN: "https://127.0.0.1" },
    { KERNEL_OPERATOR_ORIGIN: "https://localhost" },
    { KERNEL_OPERATOR_ORIGIN: "https://mcp.shardsinc.co.uk" },
    { KERNEL_OPERATOR_ORIGIN: "https://kernel.example.test/" },
    { KERNEL_OPERATOR_ORIGIN: "https://kernel.example.test/path" },
    { KERNEL_OPERATOR_ORIGIN: "https://kernel.example.test?x=1" },
    { KERNEL_OPERATOR_ORIGIN: "https://user:pass@kernel.example.test" },
    { KERNEL_OPERATOR_ORIGIN: "" },
    { KERNEL_ACCESS_CLIENT_ID: "" },
    { KERNEL_ACCESS_CLIENT_SECRET: "" },
    { KERNEL_GATEWAY_IDENTITY: "bad identity" },
    { KERNEL_GATEWAY_IDENTITY: "*" },
    { KERNEL_GATEWAY_TOKEN: "short" },
    { KERNEL_LABEL_ALLOWLIST: "[]" },
    { KERNEL_LABEL_ALLOWLIST: JSON.stringify(["a", "a"]) },
    { KERNEL_LABEL_ALLOWLIST: JSON.stringify(["bad\nlabel"]) },
    { KERNEL_MAX_ISSUE_NUMBER: "0" },
    { KERNEL_MAX_ISSUE_NUMBER: "100001" },
    { KERNEL_ACTOR_MAP: "{}" },
    { KERNEL_ACTOR_MAP: "[]" },
  ];
  for (const override of cases) {
    const call = await callTool(worker, bridgeEnv(override), validArgs());
    assert.equal(call.result.isError, true, JSON.stringify(Object.keys(override)));
    assert.ok(["BRIDGE_DISABLED", "BRIDGE_NOT_CONFIGURED"].includes(call.result.structuredContent.reason_code));
    assertNoSecrets(call.result);
  }
  assert.equal(fetchStub.calls.length, 0);
});

test("actor mapping rejects wildcards, extra pilots, mismatched prefixes and credential reuse", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const good = { actor: ACTOR, token: ACTOR_TOKEN };
  const second = { actor: "edge-agent-bob", token: "edge-agent-bob." + "b".repeat(48) };
  const cases = [
    { "*": good },
    { [`${TENANT}/${AGENT_ID}`]: good, "other/agent-cccccccc-cccc-cccc-cccc-cccccccccccc": second, "third/agent-dddddddd-dddd-dddd-dddd-dddddddddddd": { actor: "edge-agent-carol", token: "edge-agent-carol." + "c".repeat(48) } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: "edge-agent-other", token: ACTOR_TOKEN } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: ACTOR_TOKEN }, "other/agent-cccccccc-cccc-cccc-cccc-cccccccccccc": { actor: ACTOR, token: "edge-agent-alice." + "d".repeat(48) } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: ACTOR_TOKEN }, "other/agent-cccccccc-cccc-cccc-cccc-cccccccccccc": { actor: "edge-agent-bob", token: ACTOR_TOKEN } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: ACTOR_TOKEN }, "other/agent-cccccccc-cccc-cccc-cccc-cccccccccccc": { actor: GATEWAY_IDENTITY, token: "cloudflare-edge-prod." + "e".repeat(48) } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: ACTOR_TOKEN }, "other/agent-cccccccc-cccc-cccc-cccc-cccccccccccc": { actor: "edge-agent-bob", token: GATEWAY_TOKEN } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: ACTOR_TOKEN }, "other/agent-cccccccc-cccc-cccc-cccc-cccccccccccc": { actor: "edge-agent-bob", token: "edge-agent-bob." + "b".repeat(48), extra: true } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: "edge.agent", token: "edge.agent." + "a".repeat(48) } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: `${ACTOR}.short` } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: `${ACTOR}.` + "a".repeat(48) + "\n" } },
    { [`${TENANT}/${AGENT_ID}`]: { actor: ACTOR, token: `${ACTOR}.` + "a".repeat(48) }, "bad key": second },
  ];
  for (const map of cases) {
    const call = await callTool(worker, bridgeEnv({ KERNEL_ACTOR_MAP: JSON.stringify(map) }), validArgs());
    assertDeniedWithoutDispatch(call.result, "BRIDGE_NOT_CONFIGURED");
  }
  assert.equal(fetchStub.calls.length, 0);
});

test("client-supplied actor, destination, URL, header and credential fields are rejected", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv();
  for (const extra of ["actor", "destination", "url", "authorization", "headers", "origin", "repository", "token", "credential"]) {
    const call = await callTool(worker, env, { ...validArgs(), [extra]: "attacker" });
    assertDeniedWithoutDispatch(call.result, "UNEXPECTED_ARGUMENT");
  }
  assert.equal(fetchStub.calls.length, 0);
});

test("comma-joined key names cannot bypass the exact argument or permit schema", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv();

  const argsBypass = await callTool(worker, env, {
    issue_number: 123,
    label: "shards-agent",
    "permit,request_id": {},
  });
  assertDeniedWithoutDispatch(argsBypass.result, "UNEXPECTED_ARGUMENT");

  const permitBypass = { ...validPermit() };
  delete permitBypass.action;
  delete permitBypass.algorithm;
  permitBypass["action,algorithm"] = "x";
  const permitCall = await callTool(worker, env, { ...validArgs(), permit: permitBypass });
  assert.equal(permitCall.result.isError, true);
  assert.equal(permitCall.result.structuredContent.kernel_reached, false);
  assert.equal(permitCall.result.structuredContent.reason_code, "PERMIT_INVALID");

  assert.equal(fetchStub.calls.length, 0);
});

test("invalid, stale-shaped or over-broad permits are rejected structurally before dispatch", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv();
  const mutations = [
    { permit: null },
    { permit: [] },
    { permit: "permit" },
    { permit: { ...validPermit(), permit_id: undefined } },
    { permit: { ...validPermit(), extra: true } },
    { permit: { ...validPermit(), version: 1 } },
    { permit: { ...validPermit(), algorithm: "HS256" } },
    { permit: { ...validPermit(), action: "github.issue.remove_label" } },
    { permit: { ...validPermit(), subject: "another-agent" } },
    { permit: { ...validPermit(), params: { issue_number: 123 } } },
    { permit: { ...validPermit(), params: { issue_number: 123, label: "shards-agent", extra: true } } },
    { permit: { ...validPermit(), params: { issue_number: 124, label: "shards-agent" } } },
    { permit: { ...validPermit(), max_executions: 2 } },
    { permit: { ...validPermit(), nonce: "short" } },
    { permit: { ...validPermit(), signature: "zz" } },
    { permit: { ...validPermit(), permit_id: "zz" } },
    { permit: { ...validPermit(), constraints: [] } },
    { permit: { ...validPermit(), valid_until_ms: 1000 } },
    { permit: { ...validPermit(), audience: "" } },
    { permit: { ...validPermit(), issuer: "" } },
    { permit: { ...validPermit(), proposal_hash: "" } },
    { permit: { ...validPermit(), proposal_hash: "x".repeat(9000) } },
  ];
  for (const mutation of mutations) {
    const call = await callTool(worker, env, { ...validArgs(), ...mutation });
    assert.equal(call.result.isError, true);
    assert.equal(call.result.structuredContent.applied, false);
    assert.equal(call.result.structuredContent.kernel_reached, false);
    assert.match(call.result.structuredContent.reason_code, /^PERMIT_/);
    assertNoSecrets(call.result);
  }
  assert.equal(fetchStub.calls.length, 0);
});

test("issue number and label bounds are enforced before dispatch", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv();
  for (const issue_number of [0, 100001, 1.5, "123", null, Number.NaN]) {
    const call = await callTool(worker, env, { ...validArgs(), issue_number });
    assertDeniedWithoutDispatch(call.result, "ISSUE_NUMBER_OUT_OF_RANGE");
  }
  for (const label of ["other-label", "", " shards-agent", "shards-agent\n", "x".repeat(101)]) {
    const call = await callTool(worker, env, { ...validArgs(), label });
    assertDeniedWithoutDispatch(call.result, "LABEL_NOT_ALLOWLISTED");
  }
  assert.equal(fetchStub.calls.length, 0);
});

test("a valid request dispatches once with the mapped actor and returns a redacted success", async () => {
  const fetchStub = stubFetch(() => jsonResponse(200, receipt()));
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv();
  const args = validArgs();
  const call = await callTool(worker, env, args);

  assert.equal(call.result.isError, false);
  assert.equal(call.result.structuredContent.state, "SUCCEEDED");
  assert.equal(call.result.structuredContent.applied, true);
  assert.equal(call.result.structuredContent.already_present, false);
  assert.equal(call.result.structuredContent.provider_detail, "VERIFIED_READBACK");
  assert.equal(call.result.structuredContent.kernel_status, "ACCEPTED");
  assert.equal(call.result.structuredContent.kernel_decision, "ALLOW");
  assert.equal(call.result.structuredContent.kernel_evidence_hash, "e".repeat(64));
  assert.equal(call.result.structuredContent.request_id, "req-0001");
  assertNoSecrets(call.result);

  assert.equal(fetchStub.calls.length, 1);
  const dispatched = fetchStub.calls[0];
  assert.equal(dispatched.url, `${KERNEL_ORIGIN}/submit`);
  assert.equal(dispatched.init.method, "POST");
  assert.equal(dispatched.init.redirect, "manual");
  assert.ok(dispatched.init.signal, "kernel request must be abortable");
  assert.equal(dispatched.init.signal.aborted, false);

  const headers = new Headers(dispatched.init.headers);
  assert.equal(headers.get("x-shards-gateway-identity"), GATEWAY_IDENTITY);
  assert.equal(headers.get("x-shards-gateway-token"), GATEWAY_TOKEN);
  assert.equal(headers.get("cf-access-client-id"), ACCESS_ID);
  assert.equal(headers.get("cf-access-client-secret"), ACCESS_SECRET);
  assert.equal(headers.get("authorization"), `Bearer ${ACTOR_TOKEN}`);
  assert.equal(headers.get("x-actor"), null);
  assert.equal(headers.get("x-forwarded-user"), null);

  const body = JSON.parse(dispatched.init.body);
  assert.equal(body.request_id, "req-0001");
  assert.equal(body.actor, ACTOR);
  assert.equal(body.intent, "add one allowlisted label");
  assert.deepEqual(body.tool_call, { name: "github.issue.add_label", params: { issue_number: 123, label: "shards-agent" } });
  assert.deepEqual(body.params, { issue_number: 123, label: "shards-agent" });
  assert.deepEqual(body.permit, args.permit);
  assert.equal("url" in body, false);
  assert.equal("destination" in body, false);
});

test("already-present success is reported without claiming a new write", async () => {
  const fetchStub = stubFetch(() => jsonResponse(200, receipt({
    result: { ...receipt().result, already_present: true, detail: "ALREADY_PRESENT" },
  })));
  const { worker } = loadWorker(fetchStub);
  const call = await callTool(worker, bridgeEnv(), validArgs());
  assert.equal(call.result.isError, false);
  assert.equal(call.result.structuredContent.state, "SUCCEEDED");
  assert.equal(call.result.structuredContent.applied, true);
  assert.equal(call.result.structuredContent.already_present, true);
  assert.equal(call.result.structuredContent.provider_detail, "ALREADY_PRESENT");
  assert.equal(fetchStub.calls.length, 1);
});

test("provider NOT_APPLIED is a definitive non-effect", async () => {
  const fetchStub = stubFetch(() => jsonResponse(200, receipt({
    status: "FAILED", decision: "DENY", result: null,
    error: "Tool execution failed: PROVIDER_NOT_APPLIED: ISSUE_NOT_FOUND",
  })));
  const { worker } = loadWorker(fetchStub);
  const call = await callTool(worker, bridgeEnv(), validArgs());
  assert.equal(call.result.isError, true);
  assert.equal(call.result.structuredContent.state, "NOT_APPLIED");
  assert.equal(call.result.structuredContent.applied, false);
  assert.equal(call.result.structuredContent.reason_code, "PROVIDER_NOT_APPLIED");
  assert.equal(call.result.structuredContent.retryable, false);
  assert.equal(fetchStub.calls.length, 1);
});

test("provider UNKNOWN is quarantined and never reported as success", async () => {
  const fetchStub = stubFetch(() => jsonResponse(200, receipt({
    status: "FAILED", decision: "DENY", result: null,
    error: "Tool execution failed: PROVIDER_EFFECT_UNKNOWN: AMBIGUOUS_NO_READBACK_PROOF",
  })));
  const { worker } = loadWorker(fetchStub);
  const call = await callTool(worker, bridgeEnv(), validArgs());
  assert.equal(call.result.isError, true);
  assert.equal(call.result.structuredContent.state, "UNKNOWN");
  assert.equal(call.result.structuredContent.applied, null);
  assert.equal(call.result.structuredContent.reason_code, "KERNEL_EFFECT_UNKNOWN");
  assert.equal(call.result.structuredContent.retryable, false);
  assert.equal(fetchStub.calls.length, 1);
});

test("kernel permit denials, including replay, are DENIED and never retried", async () => {
  for (const error of ["PERMIT_DENIED: EXPIRED", "PERMIT_DENIED: REPLAY_DETECTED", "PERMIT_DENIED: PARAMS_MISMATCH"]) {
    const fetchStub = stubFetch(() => jsonResponse(200, {
      request_id: "req-0001", status: "REJECTED", decision: "DENY", result: null,
      error, evidence_hash: null, ts_ms: 1234567890,
    }));
    const { worker } = loadWorker(fetchStub);
    const call = await callTool(worker, bridgeEnv(), validArgs());
    assert.equal(call.result.isError, true, error);
    assert.equal(call.result.structuredContent.state, "DENIED", error);
    assert.equal(call.result.structuredContent.applied, false, error);
    assert.equal(call.result.structuredContent.kernel_reached, true, error);
    assert.equal(call.result.structuredContent.reason_code, "KERNEL_DENIED", error);
    assert.equal(call.result.structuredContent.retryable, false, error);
    assert.equal(fetchStub.calls.length, 1, error);
    assertNoSecrets(call.result);
  }
});

test("denied requests produce zero kernel dispatch", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const denials = [
    [bridgeEnv({}, makeActor({ scopes: JSON.stringify(["agent:identity"]) })), validArgs()],
    [bridgeEnv({}, makeActor({ tenant_id: "other-tenant" })), validArgs()],
    [bridgeEnv(), { ...validArgs(), label: "other-label" }],
    [bridgeEnv(), { ...validArgs(), permit: { ...validPermit(), subject: "other-agent" } }],
    [bridgeEnv({ KERNEL_GATEWAY_TOKEN: "short" }), validArgs()],
  ];
  for (const [env, args] of denials) {
    const call = await callTool(worker, env, args);
    assert.equal(call.result.isError, true);
    if (call.result.structuredContent) assert.equal(call.result.structuredContent.kernel_reached, false);
  }
  assert.equal(fetchStub.calls.length, 0, "denied requests must never reach the kernel");
});

test("kernel authentication, policy, redirect and failure responses fail closed", async () => {
  const scenarios = [
    { name: "gateway-auth", response: () => jsonResponse(401, { error: "Unauthorized" }), state: "UNAVAILABLE", applied: false, reason: "KERNEL_AUTH_UNAVAILABLE" },
    { name: "not-found", response: () => jsonResponse(404, { error: "Not found" }), state: "UNAVAILABLE", applied: false, reason: "KERNEL_AUTH_UNAVAILABLE" },
    { name: "forbidden", response: () => jsonResponse(403, { error: "Forbidden" }), state: "DENIED", applied: false, reason: "KERNEL_DENIED" },
    { name: "conflict", response: () => jsonResponse(409, { error: "Conflict" }), state: "DENIED", applied: false, reason: "KERNEL_DENIED" },
    { name: "payload", response: () => jsonResponse(413, { error: "Too large" }), state: "DENIED", applied: false, reason: "KERNEL_DENIED" },
    { name: "unprocessable", response: () => jsonResponse(422, { error: "Unprocessable" }), state: "DENIED", applied: false, reason: "KERNEL_DENIED" },
    { name: "server-error", response: () => jsonResponse(500, { error: "Internal" }), state: "UNKNOWN", applied: null, reason: "KERNEL_UNAVAILABLE" },
    { name: "rate-limit", response: () => jsonResponse(429, { error: "Slow down" }), state: "UNKNOWN", applied: null, reason: "KERNEL_UNAVAILABLE" },
    { name: "redirect", response: () => jsonResponse(302, "", { location: "https://evil.example/submit" }), state: "UNKNOWN", applied: null, reason: "KERNEL_REDIRECT_REFUSED" },
  ];
  for (const scenario of scenarios) {
    const fetchStub = stubFetch(() => scenario.response());
    const { worker } = loadWorker(fetchStub);
    const call = await callTool(worker, bridgeEnv(), validArgs());
    assert.equal(call.result.isError, true, scenario.name);
    assert.equal(call.result.structuredContent.state, scenario.state, scenario.name);
    assert.equal(call.result.structuredContent.applied, scenario.applied, scenario.name);
    assert.equal(call.result.structuredContent.reason_code, scenario.reason, scenario.name);
    assert.equal(call.result.structuredContent.retryable, false, scenario.name);
    assert.equal(fetchStub.calls.length, 1, scenario.name);
    assertNoSecrets(call.result);
  }
});

test("network errors, aborts, oversized and malformed responses become UNKNOWN", async () => {
  const scenarios = [
    { name: "network", handler: () => { throw new Error("connect ECONNREFUSED"); }, reason: "KERNEL_UNREACHABLE" },
    { name: "abort", handler: () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); }, reason: "KERNEL_UNREACHABLE" },
    { name: "oversize", handler: () => jsonResponse(200, "x".repeat(20000)), reason: "KERNEL_RESPONSE_UNREADABLE" },
    { name: "non-json", handler: () => jsonResponse(200, "not json"), reason: "KERNEL_RESPONSE_INVALID" },
    { name: "array", handler: () => jsonResponse(200, "[]"), reason: "KERNEL_EFFECT_UNKNOWN" },
    { name: "empty-object", handler: () => jsonResponse(200, "{}"), reason: "KERNEL_EFFECT_UNKNOWN" },
    { name: "accepted-without-result", handler: () => jsonResponse(200, { request_id: "req-0001", status: "ACCEPTED", decision: "ALLOW", result: null }), reason: "KERNEL_EFFECT_UNKNOWN" },
  ];
  for (const scenario of scenarios) {
    const fetchStub = stubFetch(scenario.handler);
    const { worker } = loadWorker(fetchStub);
    const call = await callTool(worker, bridgeEnv(), validArgs());
    assert.equal(call.result.isError, true, scenario.name);
    assert.equal(call.result.structuredContent.state, "UNKNOWN", scenario.name);
    assert.equal(call.result.structuredContent.applied, null, scenario.name);
    assert.equal(call.result.structuredContent.reason_code, scenario.reason, scenario.name);
    assert.equal(call.result.structuredContent.retryable, false, scenario.name);
    assert.equal(fetchStub.calls.length, 1, scenario.name);
    assertNoSecrets(call.result);
  }
});

test("the result and text never contain bridge credentials or the private origin", async () => {
  const fetchStub = stubFetch(() => jsonResponse(200, receipt()));
  const { worker } = loadWorker(fetchStub);
  const call = await callTool(worker, bridgeEnv(), validArgs());
  assertNoSecrets(call.result);
  assertNoSecrets(call.body);
  assert.equal(call.result.content[0].text.includes(ACTOR_SECRET), false);
});

test("existing public and protected tools remain unchanged when the bridge is enabled", async () => {
  const fetchStub = stubFetch(() => { throw new Error("must not fetch"); });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv();

  const anonymous = await listTools(worker, env);
  assert.deepEqual(anonymous, [
    "shards_gateway_status", "shards_systems_catalog", "shards_dns_lookup",
    "shards_skill_search", "shards_skill_read", "shards_repo_document", "shards_open_prs",
  ]);

  const observer = bridgeEnv({}, makeActor({ scopes: JSON.stringify(["agent:identity"]) }));
  const observerTools = await listTools(worker, observer, authHeaders());
  assert.ok(observerTools.includes("shards_agent_identity"));
  assert.equal(observerTools.includes("shards_message_send"), false);

  const status = await worker.fetch(post("tools/call", { name: "shards_gateway_status", arguments: {} }, authHeaders()), env);
  const statusBody = await status.json();
  assert.equal(statusBody.result.isError, false);
  assert.equal(statusBody.result.structuredContent.status, "online");
  assert.equal(fetchStub.calls.length, 0);
});

test("a verified Cloudflare Access human identity cannot call the kernel bridge", async () => {
  const { publicKey, privateKey } = await webcrypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true, ["sign", "verify"],
  );
  const jwk = await webcrypto.subtle.exportKey("jwk", publicKey);
  jwk.kid = "test-key";
  const b64 = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const header = b64({ alg: "RS256", kid: "test-key" });
  const payload = b64({
    iss: "https://test.cloudflareaccess.com",
    aud: ["connect-aud"],
    sub: "verified-access-human",
    email: "human@example.com",
    exp: now + 1200,
    nbf: now - 10,
  });
  const signature = await webcrypto.subtle.sign(
    "RSASSA-PKCS1-v1_5", privateKey, new TextEncoder().encode(`${header}.${payload}`),
  );
  const token = `${header}.${payload}.${Buffer.from(signature).toString("base64url")}`;

  const fetchStub = stubFetch((url) => {
    assert.equal(url, "https://test.cloudflareaccess.com/cdn-cgi/access/certs");
    return { ok: true, json: async () => ({ keys: [jwk] }) };
  });
  const { worker } = loadWorker(fetchStub);
  const env = bridgeEnv({
    ACCESS_TEAM: "test",
    ACCESS_AUD: "operator-aud",
    CONNECT_ACCESS_AUD: "connect-aud",
  });
  const target = "https://mcp.shardsinc.co.uk/connect";
  const signed = (method, params) => new Request(target, {
    method: "POST",
    headers: { "content-type": "application/json", "cf-access-jwt-assertion": token },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });

  const list = await worker.fetch(signed("tools/list", {}), env);
  const names = (await list.json()).result.tools.map((tool) => tool.name);
  assert.equal(names.includes(BRIDGE_TOOL), false);
  assert.ok(names.includes("shards_user_identity"));

  const call = await worker.fetch(signed("tools/call", { name: BRIDGE_TOOL, arguments: validArgs() }), env);
  const body = await call.json();
  assert.equal(body.result.isError, true);
  assert.match(body.result.content[0].text, /PERMISSION_DENIED/);
  assert.equal(fetchStub.calls.length, 1, "only the Access JWKS fetch is allowed");
});
