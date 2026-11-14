// Read-only, unauthenticated Cloudflare MCP Portal acceptance gate.
// Never send real credentials or a legitimate OAuth token from CI.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const PORTAL = 'https://portal.shardsinc.co.uk/mcp';
const TIMEOUT_MS = 10000;

function rpc(method, params = {}) {
  return JSON.stringify({ jsonrpc: '2.0', id: 101, method, params });
}

export async function checkPortalBoundary({ fetchImpl = fetch, endpoint = PORTAL } = {}) {
  const target = new URL(endpoint);
  assert.equal(target.protocol, 'https:', 'An MCP portal must use HTTPS');
  assert.equal(target.pathname, '/mcp', 'An MCP portal must use /mcp');
  const log = [];

  async function request(name, method, path, body, authorization) {
    const headers = {
      Accept: 'application/json, text/event-stream',
      'MCP-Protocol-Version': '2025-11-25',
    };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (authorization !== undefined) headers.Authorization = authorization;
    const opts = { method, headers, redirect: 'manual', signal: AbortSignal.timeout(TIMEOUT_MS) };
    if (body !== undefined) opts.body = body;
    const response = await fetchImpl(new URL(path, target.origin), opts);
    const evidence = { name, status: response.status };
    if (response.status === 401) {
      evidence.bearerChallenge = /^Bearer\b/i.test(response.headers.get('www-authenticate') || '');
    }
    log.push(evidence);
    return response;
  }

  const unauthenticatedList = await request(
    'unauthenticated_tools_list', 'POST', '/mcp', rpc('tools/list'),
  );
  assert.equal(unauthenticatedList.status, 401, 'Anonymous tool enumeration must be denied');
  assert.equal(log.at(-1).bearerChallenge, true, 'Anonymous denial must advertise OAuth Bearer');

  const unauthenticatedCall = await request(
    'unauthenticated_tool_execution', 'POST', '/mcp',
    rpc('tools/call', { name: 'shards_gateway_status', arguments: {} }),
  );
  assert.equal(unauthenticatedCall.status, 401, 'Anonymous tool execution must be denied');

  const invalidTokenCall = await request(
    'invalid_bearer_tool_execution', 'POST', '/mcp',
    rpc('tools/call', { name: 'shards_gateway_status', arguments: {} }),
    'Bearer deliberately-invalid-test-token',
  );
  assert.equal(invalidTokenCall.status, 401, 'Invalid Bearer token must not execute tools');

  const protectedResource = await request(
    'oauth_resource_metadata', 'GET', '/.well-known/oauth-protected-resource/mcp',
  );
  assert.equal(protectedResource.status, 200, 'OAuth resource metadata must be discoverable');
  const contentType = protectedResource.headers.get('content-type') || '';
  assert.match(contentType, /application\/json/i, 'OAuth metadata must be JSON');
  let metadata;
  try {
    metadata = await protectedResource.json();
  } catch {
    assert.fail('OAuth resource metadata must be valid JSON');
  }
  assert.ok(metadata && typeof metadata === 'object' && !Array.isArray(metadata), 'Metadata must be an object');
  assert.ok(
    typeof metadata.resource === 'string' &&
    new URL(metadata.resource).href === target.href,
    'Resource metadata must identify the exact protected endpoint',
  );
  assert.ok(
    Array.isArray(metadata.authorization_servers) && metadata.authorization_servers.length > 0 &&
    metadata.authorization_servers.every(uri => new URL(uri).protocol === 'https:'),
    'Resource metadata must advertise secure authorization server(s)',
  );

  return { verdict: 'PASS', portal: target.origin, checks: log, validatedAt: new Date().toISOString() };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  try {
    const result = await checkPortalBoundary();
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  } catch (error) {
    // No request, token or response body is ever emitted. Safe on public CI.
    // Unexpected transport/parser failures may embed untrusted response data in error.message.
    // Only locally authored assertion messages are safe for public CI logs.
    const safeMessage = error instanceof assert.AssertionError
      ? error.message
      : 'unexpected transport or response failure';
    process.stderr.write('Portal boundary acceptance FAIL: ' + safeMessage + '\n');
    process.exitCode = 1;
  }
}
