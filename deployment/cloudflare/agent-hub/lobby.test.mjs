import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { generateKeyPairSync, sign } from 'node:crypto';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { runInNewContext } from 'node:vm';
import hub from './worker.mjs';

const HUB = 'https://agents.shardsinc.co.uk';
const TRANSPORT = 'https://lobby-transport.shardsinc.co.uk';
const UUID_A = '11111111-1111-4111-8111-111111111111';
const UUID_B = '22222222-2222-4222-8222-222222222222';
const SECRETS = {
  LOBBY_CF_ACCESS_CLIENT_ID: 'cf-client-id-0123456789abcdef',
  LOBBY_CF_ACCESS_CLIENT_SECRET: 'cf-client-secret-0123456789abcdef',
  LOBBY_ADAPTER_TOKEN: 'adapter-token-0123456789abcdef'
};
const SECRET_VALUES = Object.values(SECRETS);
const b64 = value => Buffer.from(JSON.stringify(value)).toString('base64url');

function assertion(sub = 'owner-a', overrides = {}) {
  const header = b64({alg: 'RS256', kid: 'test-kid'});
  const payload = b64({
    iss: 'https://team.cloudflareaccess.com',
    aud: ['hub-audience'],
    sub,
    exp: Math.floor(Date.now() / 1000) + 300,
    ...overrides
  });
  return header + '.' + payload + '.' + Buffer.from('signature').toString('base64url');
}

function session(accept = () => true) {
  const calls = [];
  return {
    calls,
    binding: {
      fetch: async request => {
        const path = new URL(request.url).pathname;
        const value = request.headers.get('Cf-Access-Jwt-Assertion');
        calls.push({path, assertion: value});
        if (path !== '/session') return new Response(null, {status: 404});
        if (!accept(value)) return new Response(null, {status: 401});
        return Response.json({authenticated: true});
      }
    }
  };
}

function transport(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    calls.push({url: String(url), init, body});
    return handler({url: String(url), init, body});
  };
  return {calls, restore() { globalThis.fetch = original; }};
}

function env(binding, overrides = {}) {
  return {...SECRETS, MCP_GATEWAY: binding, ...overrides};
}

function request(path, options = {}) {
  const {method = 'GET', headers = {}, body} = options;
  const jwt = Object.hasOwn(options, 'jwt') ? options.jwt : assertion();
  const h = new Headers(headers);
  if (jwt) h.set('Cf-Access-Jwt-Assertion', jwt);
  const init = {method, headers: h};
  if (body !== undefined) init.body = typeof body === 'string' ? body : JSON.stringify(body);
  return new Request(HUB + path, init);
}

function chat(body, options = {}) {
  return request('/api/lobby/chat', {
    method: 'POST',
    jwt: Object.hasOwn(options, 'jwt') ? options.jwt : assertion(),
    headers: {
      origin: HUB,
      'sec-fetch-site': 'same-origin',
      'content-type': 'application/json',
      ...(options.headers || {})
    },
    body
  });
}

async function runChat(body, {accept = () => true, handler, envOverrides = {}, headers = {}} = {}) {
  const {binding} = session(accept);
  const mock = transport(handler || (({body}) => Response.json({conversation_id: body.conversation_id, reply: 'ok'})));
  try {
    const response = await hub.fetch(chat(body, {headers}), env(binding, envOverrides));
    const text = await response.text();
    let data = null;
    try { data = JSON.parse(text); } catch {}
    return {response, text, data, calls: mock.calls};
  } finally {
    mock.restore();
  }
}

test('lobby page and script require a verified owner session and keep strict headers', async () => {
  assert.equal((await hub.fetch(new Request(HUB + '/lobby'), env(session().binding))).status, 401);

  const jwt = assertion('owner-a');
  const rejected = session(() => false);
  assert.equal((await hub.fetch(request('/lobby', {jwt}), env(rejected.binding))).status, 401);
  assert.equal(rejected.calls.length, 1);

  const accepted = session(value => value === jwt);
  for (const path of ['/lobby', '/lobby.js']) {
    const response = await hub.fetch(request(path, {jwt}), env(accepted.binding));
    assert.equal(response.status, 200);
    assert.match(response.headers.get('cache-control'), /private, no-store/);
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
    const csp = response.headers.get('content-security-policy');
    assert.match(csp, /default-src 'none'/);
    assert.match(csp, /script-src 'self'/);
    assert.match(csp, /connect-src 'self'/);
    assert.match(csp, /frame-ancestors 'none'/);
    assert.match(csp, /form-action 'none'/);
    assert.doesNotMatch(csp, /script-src[^;]*unsafe-inline/);
    const body = await response.text();
    for (const secret of SECRET_VALUES) assert.equal(body.includes(secret), false);
    if (path === '/lobby') {
      assert.match(body, /Owner Lobby/);
      assert.match(body, /reconcile the local adapter/i);
      assert.match(body, /OpenClaw tool policy applies/);
      assert.match(body, /not proof that an agent is online/);
      assert.doesNotMatch(body, /online now/i);
      assert.match(body, /href="\/control"/);
      assert.match(body, /href="\/"/);
    } else {
      assert.match(body, /textContent/);
      assert.doesNotMatch(body, /innerHTML/);
      assert.match(body, /\/api\/lobby\/chat/);
      assert.doesNotMatch(body, /lobby-transport\.shardsinc\.co\.uk/);
      assert.doesNotMatch(body, /openclaw|127\.0\.0\.1|18790/i);
    }
  }
  assert.equal(accepted.calls.length, 2);
  for (const call of accepted.calls) {
    assert.equal(call.path, '/session');
    assert.equal(call.assertion, jwt);
  }

  const other = new Request('https://other.example/lobby', {headers: {'Cf-Access-Jwt-Assertion': jwt}});
  assert.equal((await hub.fetch(other, env(accepted.binding))).status, 404);
  const post = new Request(HUB + '/lobby', {method: 'POST', headers: {'Cf-Access-Jwt-Assertion': jwt}});
  assert.equal((await hub.fetch(post, env(accepted.binding))).status, 404);
});

test('lobby chat denies missing, rejected and structurally invalid sessions before transport', async () => {
  let mock = transport(() => Response.json({}));
  let response = await hub.fetch(new Request(HUB + '/api/lobby/chat', {
    method: 'POST',
    headers: {origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'},
    body: JSON.stringify({conversation_id: UUID_A, message: 'hi'})
  }), env(session().binding));
  assert.equal(response.status, 401);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  const jwt = assertion('owner-a');
  mock = transport(() => Response.json({}));
  const rejected = session(() => false);
  response = await hub.fetch(chat({conversation_id: UUID_A, message: 'hi'}, {jwt}), env(rejected.binding));
  assert.equal(response.status, 401);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  const noSub = b64({alg: 'RS256', kid: 'k'}) + '.' + b64({iss: 'https://team.cloudflareaccess.com', aud: ['hub-audience'], exp: Math.floor(Date.now() / 1000) + 300}) + '.sig';
  mock = transport(() => Response.json({}));
  response = await hub.fetch(chat({conversation_id: UUID_A, message: 'hi'}, {jwt: noSub}), env(session(() => true).binding));
  assert.equal(response.status, 401);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  mock = transport(() => Response.json({}));
  const expired = assertion('owner-a', {exp: 1});
  response = await hub.fetch(chat({conversation_id: UUID_A, message: 'hi'}, {jwt: expired}), env(session(() => true).binding));
  assert.equal(response.status, 401);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  mock = transport(() => Response.json({}));
  response = await hub.fetch(chat({conversation_id: UUID_A, message: 'hi'}), {MCP_GATEWAY: session(() => true).binding});
  assert.equal(response.status, 503);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  mock = transport(() => Response.json({}));
  const unavailable = {fetch: async () => new Response(null, {status: 503})};
  response = await hub.fetch(chat({conversation_id: UUID_A, message: 'hi'}), {MCP_GATEWAY: unavailable, ...SECRETS});
  assert.equal(response.status, 503);
  assert.equal(mock.calls.length, 0);
  mock.restore();
});

test('lobby chat enforces same-origin Origin and Fetch Metadata', async () => {
  const {binding} = session(() => true);
  const cases = [
    {headers: {'content-type': 'application/json'}},
    {headers: {origin: 'https://evil.example', 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'}},
    {headers: {origin: HUB, 'sec-fetch-site': 'cross-site', 'content-type': 'application/json'}}
  ];
  for (const entry of cases) {
    const mock = transport(() => Response.json({}));
    const response = await hub.fetch(request('/api/lobby/chat', {
      method: 'POST',
      headers: entry.headers,
      body: {conversation_id: UUID_A, message: 'hi'}
    }), env(binding));
    assert.equal(response.status, 403);
    assert.equal(mock.calls.length, 0);
    mock.restore();
  }

  let mock = transport(() => Response.json({}));
  let response = await hub.fetch(request('/api/lobby/chat', {
    method: 'POST',
    headers: {origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'text/plain'},
    body: '{}'
  }), env(binding));
  assert.equal(response.status, 415);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  assert.equal((await hub.fetch(request('/api/lobby/chat'), env(binding))).status, 405);
  assert.equal((await hub.fetch(request('/api/lobby/other'), env(binding))).status, 404);

  mock = transport(() => Response.json({}));
  response = await hub.fetch(new Request('https://other.example/api/lobby/chat', {
    method: 'POST',
    headers: {'Cf-Access-Jwt-Assertion': assertion(), origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'},
    body: JSON.stringify({conversation_id: UUID_A, message: 'hi'})
  }), env(binding));
  assert.equal(response.status, 404);
  assert.equal(mock.calls.length, 0);
  mock.restore();
});

test('lobby chat forwards only fixed transport credentials and a server-derived UUID', async () => {
  const jwt = assertion('owner-a');
  const accepted = session(value => value === jwt);
  const mock = transport(({body}) => Response.json({conversation_id: body.conversation_id, reply: 'Hello owner'}));
  try {
    const response = await hub.fetch(request('/api/lobby/chat?url=https://evil.example/chat&path=/health&owner=owner-b', {
      method: 'POST',
      jwt,
      headers: {
        origin: HUB,
        'sec-fetch-site': 'same-origin',
        'content-type': 'application/json; charset=utf-8',
        'cf-access-client-id': 'attacker-client',
        'cf-access-client-secret': 'attacker-secret',
        authorization: 'Bearer attacker-token',
        cookie: 'session=attacker',
        'x-forwarded-host': 'evil.example',
        'x-real-ip': '203.0.113.9'
      },
      body: {conversation_id: UUID_A, message: 'Hello there'}
    }), env(accepted.binding));

    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.deepEqual(payload, {reply: 'Hello owner'});
    assert.equal(JSON.stringify(payload).includes(SECRETS.LOBBY_ADAPTER_TOKEN), false);
    assert.equal(accepted.calls.length, 1);
    assert.equal(accepted.calls[0].path, '/session');
    assert.equal(accepted.calls[0].assertion, jwt);

    assert.equal(mock.calls.length, 1);
    const call = mock.calls[0];
    assert.equal(call.url, TRANSPORT + '/chat');
    assert.equal(call.init.method, 'POST');
    assert.equal(call.init.redirect, 'manual');
    assert.equal(call.init.cache, 'no-store');
    assert.ok(call.init.signal instanceof AbortSignal);
    const headers = call.init.headers;
    assert.equal(headers.get('cf-access-client-id'), SECRETS.LOBBY_CF_ACCESS_CLIENT_ID);
    assert.equal(headers.get('cf-access-client-secret'), SECRETS.LOBBY_CF_ACCESS_CLIENT_SECRET);
    assert.equal(headers.get('authorization'), 'Bearer ' + SECRETS.LOBBY_ADAPTER_TOKEN);
    assert.equal(headers.get('content-type'), 'application/json');
    assert.equal(headers.get('accept'), 'application/json');
    for (const name of ['origin', 'cookie', 'cf-access-jwt-assertion', 'x-forwarded-host', 'x-real-ip', 'host']) {
      assert.equal(headers.get(name), null, name + ' must not be forwarded');
    }
    assert.notEqual(headers.get('cf-access-client-id'), 'attacker-client');
    assert.notEqual(headers.get('authorization'), 'Bearer attacker-token');

    assert.deepEqual(Object.keys(call.body).sort(), ['conversation_id', 'message']);
    assert.equal(call.body.message, 'Hello there');
    assert.match(call.body.conversation_id, /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.notEqual(call.body.conversation_id, UUID_A);
    assert.equal(JSON.stringify(call.body).includes('owner-a'), false);
    assert.equal(JSON.stringify(call.body).includes('owner-b'), false);
  } finally {
    mock.restore();
  }
});

test('lobby derives stable owner-namespaced UUIDs and separates owners', async () => {
  const jwtA = assertion('owner-a');
  const jwtB = assertion('owner-b');
  const {binding} = session(() => true);
  const seen = [];
  const run = async (jwt, query = '') => {
    const mock = transport(({body}) => {
      seen.push(body.conversation_id);
      return Response.json({conversation_id: body.conversation_id, reply: 'ok'});
    });
    try {
      const response = await hub.fetch(request('/api/lobby/chat' + query, {
        method: 'POST',
        jwt,
        headers: {origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'},
        body: {conversation_id: UUID_A, message: 'hi'}
      }), env(binding));
      assert.equal(response.status, 200);
    } finally {
      mock.restore();
    }
  };
  await run(jwtA);
  await run(jwtA, '?owner=owner-b');
  await run(jwtB);
  assert.equal(seen.length, 3);
  assert.equal(seen[0], seen[1]);
  assert.notEqual(seen[0], seen[2]);
  assert.notEqual(seen[0], UUID_A);
  assert.notEqual(seen[0], UUID_B);
});

test('the actual private session bridge rejects forged and unauthorized owners', async t => {
  const source = await readFile(new URL('../worker.js', import.meta.url));
  const {default: edge} = await import('data:text/javascript;base64,' + source.toString('base64'));
  const {privateKey, publicKey} = generateKeyPairSync('rsa', {modulusLength:2048});
  const issuer = 'https://lobby-test.cloudflareaccess.com';
  const audience = 'lobby-hub-test';
  const jwt = (claims = {}, key = privateKey) => {
    const header = b64({alg:'RS256', kid:'lobby-test'});
    const payload = b64({iss:issuer, aud:[audience], sub:'owner-a', exp:Math.floor(Date.now()/1000)+300, ...claims});
    const data = header + '.' + payload;
    return data + '.' + sign('RSA-SHA256', Buffer.from(data), key).toString('base64url');
  };
  const namespaces = [];
  let deleted = false;
  const binding = {fetch: req => {
    assert.equal(req.url, 'https://agent-hub-registry.internal/session');
    return edge.fetch(req, {
      ACCESS_TEAM:'lobby-test', HUB_REGISTRY_AUD:audience, ACCESS_AUD:'operator-test',
      CONNECT_ACCESS_AUD:'connect-test', EDGE_DB:{prepare(sql) {
        assert.match(sql, /^SELECT deleted_at FROM operator_accounts WHERE id=\?$/);
        return {bind: () => ({first: async () => deleted ? {deleted_at:'2026-11-25'} : null})};
      }}
    });
  }};
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    if (String(url) === issuer + '/cdn-cgi/access/certs') {
      return Response.json({keys:[{...publicKey.export({format:'jwk'}), kid:'lobby-test'}]});
    }
    assert.equal(String(url), TRANSPORT + '/chat');
    const payload = JSON.parse(init.body);
    namespaces.push(payload.conversation_id);
    return Response.json({conversation_id:payload.conversation_id, reply:'sample reply'});
  });
  const send = assertion => hub.fetch(chat({conversation_id:UUID_A, message:'sample'}, {jwt:assertion}), env(binding));
  const forged = generateKeyPairSync('rsa', {modulusLength:2048}).privateKey;
  for (const assertion of [jwt({}, forged), jwt({aud:['operator-test']}), jwt({iss:'https://other.example'}), jwt({exp:1})]) {
    assert.equal((await send(assertion)).status, 401);
  }
  assert.equal(namespaces.length, 0);
  assert.equal((await send(jwt())).status, 200);
  assert.equal((await send(jwt())).status, 200);
  assert.equal((await send(jwt({sub:'owner-b'}))).status, 200);
  assert.equal(namespaces[0], namespaces[1]);
  assert.notEqual(namespaces[0], namespaces[2]);
  deleted = true;
  assert.equal((await send(jwt())).status, 401);
  assert.equal(namespaces.length, 3);
});

test('Lobby transport JSON and outcome mapping work with the merged loopback adapter', {timeout:10000}, async t => {
  const child = spawn('python3', ['-u', '-c', `
import sys, tempfile
from pathlib import Path
from test_lobby_adapter import Harness
with tempfile.TemporaryDirectory() as root:
    harness = Harness(state_dir=Path(root) / "state")
    try:
        print(harness.port, harness.token(), flush=True)
        for line in sys.stdin:
            harness.upstream.server.mode = "error"
            print("ready", flush=True)
    finally:
        harness.close()
`], {cwd:new URL('../../oracle/lobby-adapter/', import.meta.url), stdio:['pipe','pipe','pipe']});
  const exited = once(child, 'exit');
  const lines = createInterface({input:child.stdout});
  t.after(async () => {child.stdin.end(); await exited;});
  const [ready] = await once(lines, 'line');
  const [port, token] = ready.split(' ');
  assert.match(port, /^\d+$/);
  const loopback = 'http://127.0.0.1:' + port;
  const actualFetch = globalThis.fetch;
  t.mock.method(globalThis, 'fetch', (url, init) => {
    const target = new URL(url);
    assert.equal(target.origin, TRANSPORT);
    // Node supplies the local Host and Content-Length. The external tunnel
    // still has to preserve equivalent framing and strip external headers.
    const headers = new Headers(init.headers);
    headers.delete('cf-access-client-id');
    headers.delete('cf-access-client-secret');
    return actualFetch(loopback + target.pathname, {...init, headers});
  });
  const config = env(session().binding, {LOBBY_ADAPTER_TOKEN:token});
  const send = () => hub.fetch(chat({conversation_id:UUID_A, message:'sample 🌲'}), config);
  const health = () => hub.fetch(request('/api/lobby/health'), config);
  assert.deepEqual(await (await health()).json(), {status:'ok'});
  assert.deepEqual(await (await send()).json(), {reply:'fake upstream reply'});
  const changed = once(lines, 'line');
  child.stdin.write('error\n');
  await changed;
  assert.equal((await (await send()).json()).outcome, 'unknown');
  assert.equal((await (await send()).json()).outcome, 'blocked');
  assert.deepEqual(await (await health()).json(), {status:'blocked', reconcile:true});
});

test('lobby rejects caller owner input, unknown fields and invalid text/UUID/size', async () => {
  const {binding} = session(() => true);
  const cases = [
    [{conversation_id: UUID_A, message: 'hi', owner: 'owner-b'}, 400],
    [{conversation_id: UUID_A, message: 'hi', model: 'openclaw/shards'}, 400],
    [{conversation_id: UUID_A, message: 'hi', messages: []}, 400],
    [{conversation_id: UUID_A, message: 'hi', headers: {}}, 400],
    [{conversation_id: UUID_A, message: 'hi', url: 'https://evil.example'}, 400],
    [{conversation_id: 'not-a-uuid', message: 'hi'}, 400],
    [{conversation_id: 'abcdefab-cdef-4abc-8def-abcdefabcdef'.toUpperCase(), message: 'hi'}, 400],
    [{conversation_id: UUID_A, message: '   '}, 400],
    [{conversation_id: UUID_A, message: 'bad\u0000null'}, 400],
    [{conversation_id: UUID_A, message: 'x'.repeat(8001)}, 413],
    [{conversation_id: UUID_A, message: '\u00e9'.repeat(7000)}, 413],
    [null, 400],
    [[], 400],
    ['text', 400],
    [JSON.stringify('text'), 400]
  ];
  for (const [body, status] of cases) {
    const mock = transport(() => Response.json({}));
    const response = await hub.fetch(request('/api/lobby/chat', {
      method: 'POST',
      headers: {origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'},
      body
    }), env(binding));
    assert.equal(response.status, status, JSON.stringify(body));
    assert.equal(mock.calls.length, 0);
    mock.restore();
  }

  const mock = transport(() => Response.json({}));
  const response = await hub.fetch(request('/api/lobby/chat', {
    method: 'POST',
    headers: {origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'},
    body: JSON.stringify({conversation_id: UUID_A, message: 'x'.repeat(20000)})
  }), env(binding));
  assert.equal(response.status, 413);
  assert.equal(mock.calls.length, 0);
  mock.restore();
});

test('lobby maps adapter outcomes conservatively and never retries', async () => {
  const {binding} = session(() => true);
  const cases = [
    {status: 503, body: {error: 'reconciliation required'}, expectStatus: 503, outcome: 'blocked', reconcile: true},
    {status: 504, body: {error: 'upstream timeout', outcome: 'unknown'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 502, body: {error: 'upstream unavailable'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 502, body: {error: 'upstream unavailable', outcome: 'not_dispatched'}, expectStatus: 502, outcome: 'not_dispatched'},
    {status: 503, body: {error: 'busy'}, expectStatus: 503, outcome: 'not_dispatched', retryable: true},
    {status: 503, body: {error: 'dispatch state unavailable'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 500, body: {error: 'internal error'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 504, body: {error: 'upstream timeout', outcome: 'not_dispatched'}, expectStatus: 502, outcome: 'not_dispatched'},
    {status: 401, body: {error: 'unauthorized'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 429, body: {error: 'proxy rate limited'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 403, body: {error: 'proxy denied', outcome: 'not_dispatched'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 503, body: {error: 'busy', outcome: 'unknown'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 302, body: null, headers: {location: 'https://evil.example'}, expectStatus: 502, outcome: 'unknown', reconcile: true},
    {status: 200, body: {conversation_id: 'wrong', reply: 'x'}, expectStatus: 502, outcome: 'unknown', reconcile: true}
  ];
  for (const entry of cases) {
    const mock = transport(() => new Response(
      entry.body === null ? null : JSON.stringify(entry.body),
      {status: entry.status, headers: {'content-type': 'application/json', ...(entry.headers || {})}}
    ));
    const response = await hub.fetch(chat({conversation_id: UUID_A, message: 'hi'}), env(binding));
    assert.equal(response.status, entry.expectStatus, JSON.stringify(entry));
    const data = await response.json();
    assert.equal(data.outcome, entry.outcome, JSON.stringify(entry));
    assert.equal(response.headers.get('x-shards-lobby-outcome'), entry.outcome === 'not_dispatched' ? 'not_dispatched' : null);
    if (entry.reconcile) assert.equal(data.reconcile, true, JSON.stringify(entry));
    if (entry.retryable) assert.equal(data.retryable, true, JSON.stringify(entry));
    assert.equal(mock.calls.length, 1, 'exactly one attempt');
    mock.restore();
  }
});

async function loadLobby(fetch, storage = new Map()) {
  const response = await hub.fetch(request('/lobby.js'), env(session().binding));
  assert.equal(response.status, 200);
  const element = () => ({
    value: '', disabled: false, hidden: false, listeners: {},
    append() {},
    addEventListener(name, listener) { this.listeners[name] = listener; }
  });
  const nodes = new Map();
  const get = name => {
    if (!nodes.has(name)) nodes.set(name, element());
    return nodes.get(name);
  };
  runInNewContext(await response.text(), {
    document: {getElementById: get, createElement: element}, fetch, crypto, AbortSignal,
    sessionStorage: {
      getItem: key => storage.get(key),
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    }
  });
  await new Promise(setImmediate);
  return get;
}

test('Lobby requires explicit reconciliation after unknown, blocked or disconnected sends', async () => {
  for (const failure of [
    () => Response.json({outcome:'unknown'}, {status:502}),
    () => Response.json({outcome:'blocked'}, {status:503}),
    () => Response.json({outcome:'not_dispatched'}, {status:429}),
    () => { throw Error('connection lost'); }
  ]) {
    const storage = new Map();
    let sends = 0, blocked = false;
    const fetch = async path => {
      if (path === '/api/lobby/health') {
        return blocked ? Response.json({status:'blocked'}, {status:503}) : Response.json({status:'ok'});
      }
      assert.equal(path, '/api/lobby/chat');
      sends++;
      return failure();
    };
    const get = await loadLobby(fetch, storage);
    const submit = () => get('composer').listeners.submit({preventDefault() {}});
    assert.equal(get('send').disabled, false);
    get('message').value = 'sample';
    await submit();
    assert.equal(get('send').disabled, true);
    await submit();
    assert.equal(sends, 1);
    const reloaded = await loadLobby(fetch, storage);
    assert.equal(reloaded('send').disabled, true, 'a healthy transport alone cannot unlock a reload');
    blocked = true;
    await reloaded('reconciled').listeners.click();
    assert.equal(reloaded('send').disabled, true);
    blocked = false;
    await reloaded('reconciled').listeners.click();
    assert.equal(reloaded('send').disabled, false);
    assert.equal(sends, 1, 'checking recovery does not resend');
  }
});

test('Lobby re-enables Send after a confirmed non-dispatch from the Hub', async () => {
  const get = await loadLobby(async path => path === '/api/lobby/health'
    ? Response.json({status:'ok'})
    : Response.json({outcome:'not_dispatched', retryable:true}, {
      status:503, headers:{'x-shards-lobby-outcome':'not_dispatched'}
    }));
  get('message').value = 'sample';
  await get('composer').listeners.submit({preventDefault() {}});
  assert.equal(get('send').disabled, false);
  assert.equal(get('reconciled').hidden, true);
});

test('Lobby refuses malformed UTF-8 response bodies and unpaired Unicode in requests', async () => {
  const invalid = await runChat({conversation_id:UUID_A, message:'\ud800'});
  assert.equal(invalid.response.status, 400);
  assert.equal(invalid.calls.length, 0);
  const reply = await runChat({conversation_id:UUID_A, message:'sample'}, {handler:({body}) =>
    new Response(Buffer.concat([
      Buffer.from('{"conversation_id":"' + body.conversation_id + '","reply":"'),
      Buffer.from([0xff]), Buffer.from('"}')
    ]), {headers:{'content-type':'application/json'}})
  });
  assert.equal(reply.data.outcome, 'unknown');
});

test('Lobby transport deadline also bounds reading a stalled response body', async t => {
  const controller = new AbortController();
  const timeout = AbortSignal.timeout;
  t.mock.method(AbortSignal, 'timeout', ms => ms === 45000 ? controller.signal : timeout(ms));
  const mock = transport(() => new Response(new ReadableStream({
    pull() { controller.abort(); }
  }), {headers:{'content-type':'application/json'}}));
  try {
    const response = await Promise.race([
      hub.fetch(chat({conversation_id:UUID_A, message:'sample'}), env(session().binding)),
      new Promise(resolve => setTimeout(() => resolve(null), 300))
    ]);
    assert.ok(response, 'response must terminate when its transport deadline expires');
    assert.equal((await response.json()).outcome, 'unknown');
    assert.equal(mock.calls.length, 1);
  } finally { mock.restore(); }
});

test('Lobby bounds reading a stalled inbound request before dispatch', async t => {
  const controller = new AbortController();
  t.mock.method(AbortSignal, 'timeout', () => controller.signal);
  const req = new Request(HUB + '/api/lobby/chat', {
    method:'POST', duplex:'half',
    headers:{'Cf-Access-Jwt-Assertion':assertion(), origin:HUB, 'content-type':'application/json'},
    body:new ReadableStream({pull() { controller.abort(); }})
  });
  const mock = transport(() => { throw Error('unexpected transport call'); });
  try {
    const response = await Promise.race([
      hub.fetch(req, env(session().binding)),
      new Promise(resolve => setTimeout(() => resolve(null), 300))
    ]);
    assert.ok(response, 'an expired request body must be rejected');
    assert.equal(response.status, 400);
    assert.equal(mock.calls.length, 0);
  } finally { mock.restore(); }
});

test('lobby treats malformed, oversized, secret-bearing and failed responses as unknown', async () => {
  const {binding} = session(() => true);
  const send = () => chat({conversation_id: UUID_A, message: 'hi'});

  let mock = transport(() => new Response('not json', {status: 200, headers: {'content-type': 'application/json'}}));
  let response = await hub.fetch(send(), env(binding));
  assert.equal(response.status, 502);
  assert.equal((await response.json()).outcome, 'unknown');
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(() => new Response(JSON.stringify({conversation_id: UUID_A, reply: 'x'.repeat(70000)}), {status: 200, headers: {'content-type': 'application/json'}}));
  response = await hub.fetch(send(), env(binding));
  assert.equal(response.status, 502);
  assert.equal((await response.json()).outcome, 'unknown');
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(({body}) => Response.json({conversation_id: body.conversation_id, reply: '   '}));
  response = await hub.fetch(send(), env(binding));
  assert.equal(response.status, 502);
  assert.equal((await response.json()).outcome, 'unknown');
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(({body}) => Response.json({conversation_id: body.conversation_id, reply: 'bad\u0000reply'}));
  response = await hub.fetch(send(), env(binding));
  assert.equal(response.status, 502);
  assert.equal((await response.json()).outcome, 'unknown');
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(({body}) => Response.json({conversation_id: body.conversation_id, reply: 'leak ' + SECRETS.LOBBY_ADAPTER_TOKEN}));
  response = await hub.fetch(send(), env(binding));
  assert.equal(response.status, 502);
  const data = await response.json();
  assert.equal(data.outcome, 'unknown');
  assert.equal(JSON.stringify(data).includes(SECRETS.LOBBY_ADAPTER_TOKEN), false);
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(() => { throw new Error('network down'); });
  response = await hub.fetch(send(), env(binding));
  assert.equal(response.status, 502);
  assert.equal((await response.json()).outcome, 'unknown');
  assert.equal(mock.calls.length, 1);
  mock.restore();
});

test('lobby health reports transport state without liveness or internal details', async () => {
  const {binding} = session(() => true);
  const health = () => request('/api/lobby/health', {headers: {'sec-fetch-site': 'same-origin'}});

  assert.equal((await hub.fetch(request('/api/lobby/health', {jwt: null, headers: {'sec-fetch-site': 'same-origin'}}), env(binding))).status, 401);
  assert.equal((await hub.fetch(health(), env(session(() => false).binding))).status, 401);

  let mock = transport(() => Response.json({status: 'ok', model: 'openclaw/shards'}));
  let response = await hub.fetch(health(), env(binding));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {status: 'ok'});
  assert.equal(mock.calls.length, 1);
  assert.equal(mock.calls[0].url, TRANSPORT + '/health');
  assert.equal(mock.calls[0].init.method, 'GET');
  assert.equal(mock.calls[0].init.redirect, 'manual');
  assert.equal(mock.calls[0].init.headers.get('authorization'), 'Bearer ' + SECRETS.LOBBY_ADAPTER_TOKEN);
  assert.equal(mock.calls[0].init.body, undefined);
  mock.restore();

  mock = transport(() => Response.json({status: 'blocked', model: 'openclaw/shards', reason: 'pending upstream dispatch requires local reconciliation'}, {status: 503}));
  response = await hub.fetch(health(), env(binding));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {status: 'blocked', reconcile: true});
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(() => Response.json({status:'ok'}));
  response = await hub.fetch(health(), env(binding));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {status:'unavailable'});
  mock.restore();

  mock = transport(() => new Response(null, {status: 401}));
  response = await hub.fetch(health(), env(binding));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {status: 'unavailable'});
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(() => { throw new Error('network'); });
  response = await hub.fetch(health(), env(binding));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {status: 'unavailable'});
  assert.equal(mock.calls.length, 1);
  mock.restore();

  mock = transport(() => Response.json({status: 'ok'}));
  response = await hub.fetch(request('/api/lobby/health', {headers: {origin: 'https://evil.example', 'sec-fetch-site': 'same-origin'}}), env(binding));
  assert.equal(response.status, 403);
  assert.equal(mock.calls.length, 0);
  mock.restore();

  assert.equal((await hub.fetch(request('/api/lobby/health', {
    method: 'POST',
    headers: {origin: HUB, 'sec-fetch-site': 'same-origin', 'content-type': 'application/json'},
    body: '{}'
  }), env(binding))).status, 405);
});

test('existing control, workspace and public hub routes are unchanged', async () => {
  const binding = {
    fetch: async request => {
      const path = new URL(request.url).pathname;
      if (path === '/session') return Response.json({authenticated: true});
      if (path === '/dashboard') return Response.json({
        agents: [],
        tasks: [],
        limits: {agents: 100, tasks: 100, agents_truncated: false, tasks_truncated: false},
        checked_at: '2026-11-25T00:00:00Z'
      });
      return new Response(null, {status: 404});
    }
  };
  const jwt = assertion('owner-a');
  const envObj = {MCP_GATEWAY: binding, AI: {run: async () => ({})}};

  let response = await hub.fetch(request('/api/control', {jwt, headers: {origin: HUB, 'sec-fetch-site': 'same-origin'}}), envObj);
  assert.equal(response.status, 200);
  const snapshot = await response.json();
  assert.deepEqual(snapshot.agents, []);
  assert.deepEqual(snapshot.tasks, []);
  assert.equal(snapshot.limits.agents, 100);

  response = await hub.fetch(request('/control', {jwt}), envObj);
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Control centre/);

  response = await hub.fetch(request('/', {jwt}), envObj);
  assert.equal(response.status, 200);
  const page = await response.text();
  assert.match(page, /href="\/control"/);
  assert.match(page, /href="\/lobby"/);
  assert.match(page, /LLM Workspace/);

  response = await hub.fetch(request('/api/health', {jwt}), envObj);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).service, 'shards-agent-hub-edge');

  response = await hub.fetch(request('/api/models', {jwt}), envObj);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).models.length, 4);

  const inference = {run: async (model, options) => {
    assert.equal(model, '@cf/qwen/qwen3.8-27b');
    assert.equal(options.stream, true);
    assert.deepEqual(options.messages.at(-1), {role:'user', content:'sample'});
    return new Response('data: {"response":"sample reply"}\n\n').body;
  }};
  response = await hub.fetch(request('/api/chat', {
    jwt, method:'POST', headers:{origin:HUB, 'content-type':'application/json'},
    body:{model:'qwen', messages:[{role:'user', content:'sample'}]}
  }), {...envObj, AI:inference});
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /^text\/event-stream/);
  assert.match(await response.text(), /sample reply/);

  assert.equal((await hub.fetch(request('/nope', {jwt}), envObj)).status, 404);
});
