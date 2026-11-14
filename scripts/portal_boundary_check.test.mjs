import test from 'node:test';
import assert from 'node:assert/strict';
import { checkPortalBoundary } from './portal_boundary_check.mjs';

function mockGateway({ anonymousListStatus = 401, anonymousCallStatus = 401, invalidStatus = 401, challenge = true, metadataValid = true } = {}) {
  const seen = [];
  async function fetchImpl(url, opts) {
    const body = opts.body && JSON.parse(opts.body);
    seen.push({ path: url.pathname, method: opts.method, authorization: opts.headers.Authorization || null });
    if (url.pathname === '/.well-known/oauth-protected-resource/mcp') {
      return Response.json(metadataValid
        ? { resource: 'https://portal.shardsinc.co.uk/mcp', authorization_servers: ['https://portal.shardsinc.co.uk'] }
        : { authorization_servers: [] });
    }
    const invalid = !!opts.headers.Authorization;
    return new Response(JSON.stringify({ error: 'invalid_token' }), {
      status: invalid ? invalidStatus : body?.method === 'tools/list' ? anonymousListStatus : body?.method === 'tools/call' ? anonymousCallStatus : 401,
      headers: challenge ? { 'WWW-Authenticate': 'Bearer realm="OAuth"' } : {},
    });
  }
  return { fetchImpl, seen };
}

test('all four read-only acceptance probes PASS; no real credentials are sent', async () => {
  const { fetchImpl, seen } = mockGateway();
  const result = await checkPortalBoundary({ fetchImpl });
  assert.equal(result.verdict, 'PASS');
  assert.equal(result.checks.length, 4);
  assert.deepEqual(result.checks.map(x => x.status), [401, 401, 401, 200]);
  assert.equal(seen.filter(x => x.authorization).length, 1);
  assert.equal(seen[2].authorization, 'Bearer deliberately-invalid-test-token');
  assert.ok(seen.every(x => x.method === 'GET' || x.method === 'POST'));
});

test('anonymous tool enumeration accidentally exposed fails closed', async () => {
  await assert.rejects(checkPortalBoundary(mockGateway({ anonymousListStatus: 200 })), /Anonymous tool enumeration/);
});

test('anonymous tool execution accidentally exposed fails closed', async () => {
  await assert.rejects(checkPortalBoundary(mockGateway({ anonymousCallStatus: 200 })), /Anonymous tool execution/);
});

test('invalid Bearer token accepted fails closed', async () => {
  await assert.rejects(checkPortalBoundary(mockGateway({ invalidStatus: 200 })), /Invalid Bearer token/);
});

test('missing OAuth challenge fails closed', async () => {
  await assert.rejects(checkPortalBoundary(mockGateway({ challenge: false })), /advertise OAuth Bearer/);
});

test('invalid resource metadata fails closed', async () => {
  await assert.rejects(checkPortalBoundary(mockGateway({ metadataValid: false })), /Resource metadata must identify the exact protected endpoint/);
});

test('insecure portal URL fails before network access', async () => {
  await assert.rejects(checkPortalBoundary({
    ...mockGateway(), endpoint: 'http://portal.shardsinc.co.uk/mcp',
  }), /HTTPS/);
});
