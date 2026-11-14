import test from 'node:test';
import assert from 'node:assert/strict';
import { checkPortalBoundary } from './portal_boundary_check.mjs';

function mockGateway({ anonymousListStatus = 401, anonymousCallStatus = 401, invalidStatus = 401, challenge = true, authChallenge = 'Bearer realm="OAuth"', metadataValid = true, metadataMalformed = false, resource = 'https://portal.shardsinc.co.uk/mcp' } = {}) {
  const seen = [];
  async function fetchImpl(url, opts) {
    const body = opts.body && JSON.parse(opts.body);
    seen.push({ path: url.pathname, method: opts.method, authorization: opts.headers.Authorization || null });
    if (url.pathname === '/.well-known/oauth-protected-resource/mcp') {
      if (metadataMalformed) return new Response('{INVALID_JSON_SENSITIVE_MARKER}', {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
      return Response.json(metadataValid
        ? { resource, authorization_servers: ['https://portal.shardsinc.co.uk'] }
        : { authorization_servers: [] });
    }
    const invalid = !!opts.headers.Authorization;
    return new Response(JSON.stringify({ error: 'invalid_token' }), {
      status: invalid ? invalidStatus : body?.method === 'tools/list' ? anonymousListStatus : body?.method === 'tools/call' ? anonymousCallStatus : 401,
      headers: challenge ? { 'WWW-Authenticate': authChallenge } : {},
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
  assert.deepEqual(seen.map(x => [x.path, x.method]), [
    ['/mcp', 'POST'],
    ['/mcp', 'POST'],
    ['/mcp', 'POST'],
    ['/.well-known/oauth-protected-resource/mcp', 'GET'],
  ]);
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

test('a Bearer challenge after another valid scheme is accepted', async () => {
  const result = await checkPortalBoundary(mockGateway({
    authChallenge: 'Basic realm="other", Bearer realm="OAuth"',
  }));
  assert.equal(result.verdict, 'PASS');
});

test('a challenge advertising only Basic fails closed', async () => {
  await assert.rejects(
    checkPortalBoundary(mockGateway({ authChallenge: 'Basic realm="other"' })),
    /advertise OAuth Bearer/,
  );
});

test('invalid resource metadata fails closed', async () => {
  await assert.rejects(checkPortalBoundary(mockGateway({ metadataValid: false })), /Resource metadata must identify the exact protected endpoint/);
});

test('malformed OAuth JSON is rejected without leaking its response body', async () => {
  await assert.rejects(
    checkPortalBoundary(mockGateway({ metadataMalformed: true })),
    error => {
      assert.match(error.message, /OAuth resource metadata must be valid JSON/);
      assert.doesNotMatch(error.message, /SENSITIVE_MARKER/);
      return true;
    },
  );
});

test('OAuth metadata with same-origin but wrong resource path fails closed', async () => {
  for (const resource of ['https://portal.shardsinc.co.uk/', 'https://portal.shardsinc.co.uk/other']) {
    await assert.rejects(
      checkPortalBoundary(mockGateway({ resource })),
      /exact protected endpoint/,
    );
  }
});

test('insecure portal URL fails before network access', async () => {
  await assert.rejects(checkPortalBoundary({
    ...mockGateway(), endpoint: 'http://portal.shardsinc.co.uk/mcp',
  }), /HTTPS/);
});
