# Native MCP authentication and persistence audit

Audit date: 16 November 2026. Base: `e7e2f2c227171468734085962558e6e969a9bea7`.
Primary workflow: client-integration; supporting workflow: security-review.

## Decision and bounded implementation

Native persistent private-tool access remains **BLOCKED**, not supported by this
change. The smallest independently testable implementation is fail-closed bearer
handling in the edge MCP transport. Invalid, expired, revoked or disabled
credentials must return HTTP 401 with a Bearer challenge rather than silently
returning the public tool list. Authentication storage failure returns sanitized
503. Valid keys retain their existing scopes; anonymous public discovery remains
available. One request resolves one principal, including initialize and discovery.

Preconditions: clean feature branch; isolated synthetic fixtures; no production
credentials. Scope: Worker request authentication, offline tests and documentation.
Rollback: revert the code commit; no schema migration or provider change.
Evidence required: negative authentication, scope filtering, Access regression,
official SDK tests, docs validation and separate live/client acceptance.

## Architecture findings

| Boundary | Source evidence | Finding |
| --- | --- | --- |
| Edge `/mcp` | `deployment/cloudflare/worker.js`, `schema.sql` | D1 agent/token identity; hashed bearer keys, expiry, revocation, disabled-agent check; scope-filtered discovery; tenant from stored principal |
| Edge `/connect` | `accessClaims`, `mcp(..., signedIdentity)` | Signed Cloudflare Access identity; separate audience from operator; public tools and own identity only; no private agent grant |
| Operator | `/manage`, `accessActor` | Existing Access JWT verification is independent of MCP bearer identity and must remain intact |
| Python gateway | `src/shards_mcp/oauth.py`, `server.py` | Optional pinned issuer/JWKS JWT resource server; exact audience and enrolled subject; scope intersection; no authorization, consent or refresh server |
| Web console | `web/app/connection-hub.tsx`, `web/README.md` | Console social login does not authorize MCP agents |
| Plugin | root `plugin.json`, `mcp.json`, `plugins/shards-mcp` | Portable metadata/local stdio templates; no account-level Codex Cloud connection installation or credential persistence |
| Portal | external Cloudflare configuration | Repository cannot establish actual upstream identity/header mapping or refresh lifecycle from source alone |

The Worker supports JSON responses over HTTP POST, public initialize/discovery,
legacy protocol negotiation and a newer tool subset; no SSE push. Discovery must
be repeated with authenticated credentials. A successful public initialize is not
proof of private-tool access. The implementation intentionally adds no OAuth
metadata to `/mcp`: advertising `/connect` as its authorization authority would
confuse two distinct identity boundaries.

Concurrent open PRs observed: #36 (portal denial checks), #40 (Python verifier
policy), #35 (operator settings). This change does not incorporate those branches.
The path-specific `/connect` resource metadata names its Access issuer; it is a
discovery hint, not proof of PKCE, refresh, client compatibility or private scopes.

## Independent security review correction

Gitar finding on reviewed commit
`2f7f2ccbd922fd5b75265b2fb694fe8f9fdf3019`:
[review comment](https://github.com/Shards-foundation/Shards-MCP/pull/46#discussion_r4589942128).
The new `/mcp` HTTP 401 correctly rejected invalid keys, but the fallback from
`/.well-known/oauth-protected-resource/mcp` to root metadata followed a redirect
into `/connect`'s Cloudflare Access authority. The new negative regression failed
against that commit with root HTTP 302 instead of 404. This was an authentication
authority-confusion defect, not evidence that an Access token granted agent scope.

The correction returns non-cacheable HTTP 404 without redirects or issuer metadata
at root protected-resource metadata and the `/mcp` protected-resource path,
independently of Access configuration. It also removes the root
`/.well-known/oauth-authorization-server` redirect: the installed official SDK
falls back there when resource metadata is unavailable, so leaving that alias
would still lead `/mcp` clients to Access. No OAuth functionality is added.

Both path-specific `/connect` metadata routes, their CORS/cache behavior, the
Access challenge and signed Access validation remain intact. Clients must use
`/connect`'s resource-specific metadata to find its issuer; root discovery no
longer aliases it. Official SDK tests cover normal `/connect` resource discovery,
the metadata URL from its 401 challenge, and authenticated identity/tool access.
The `/mcp` challenge, invalid-bearer 401, storage-failure 503, anonymous public
discovery, scoped bearer access and per-request revocation checks are unchanged.

Primary correction workflow: security-review; supporting: client-integration.
Scope is Worker metadata routing, regression tests and this document; rollback is
a revert with no schema or provider change. All fixtures use synthetic identities.
No credentials, Access policies or production deployments were changed. Native
OAuth persistence and fresh-task acceptance remain **BLOCKED** as described below.

## OAuth 2.1 design for independent review

Prefer an established authorization server, with the edge acting as a resource
server. Do not build a bespoke issuer or exchange Access operator JWTs for agent
keys. Reuse the existing portal only after proving its authorization-server
capabilities and per-user upstream identity propagation. A shared upstream bearer
header cannot represent different enrolled agents safely.

1. Pin issuer, HTTPS metadata/JWKS and exact resource audience per endpoint.
   Publish RFC 9728 metadata at the resource-specific well-known path and link it
   in HTTP 401 challenges. Never derive issuer/JWKS from token headers. Validate
   algorithm, key ID, signature, issuer, audience, exp, nbf and subject; reject
   ID tokens, wrong resources and unknown issuers. Plan key rotation and outages.
2. Use authorization code with mandatory S256 PKCE, exact pre-registered redirect
   URIs, one-time short-lived codes, client binding, state and explicit consent.
   No implicit/password grants. Support RFC 8707 resource indicators through
   authorization and token exchange. Confirm each client's current registration
   method (pre-registration, supported client metadata or controlled DCR); never
   accept arbitrary redirect URLs or fetch arbitrary client metadata unchecked.
3. Store an operator-approved unique binding `(issuer, subject, client_id)` to
   `(tenant_id, agent_id)`; no automatic enrollment or email-derived authority.
   Verify active membership and agent on every request. Effective permissions are
   the intersection of consent, token scopes and current enrolled scopes.
   Tenant and agent claims are insufficient without the stored binding. Existing
   bearer identity remains separate and unchanged; no JWT-to-bearer fallback.
4. Use short access-token lifetimes and issuer revocation/introspection or a local
   grant/version check when immediate revocation is required. Refresh tokens belong
   in the client's protected credential store; rotate on every use, detect reuse,
   revoke the token family, enforce idle/absolute expiry and explicit disconnect.
   Scope reduction, agent disablement and binding deletion deny immediately even
   while a signed access token is otherwise valid. Test key rotation/outages.
5. Record grant, consent, binding changes, refresh reuse, revocation and denial
   reason codes with correlation IDs and pseudonymous actor/tenant identifiers.
   Never log tokens, authorization codes, verifiers, raw headers or user payloads.
   Define retention and restricted audit access. Durable mutations retain their
   transactional audit; authentication telemetry must not replace it.
6. Preserve `/manage` Access policy and audience. OAuth client tokens cannot
   authenticate as an operator. Keep `/connect` pilot privileges separate. Maintain
   current bearer expiry, revocation and tenant checks. Do not change production
   routes, Access applications, paid plans or enrollment as part of this PR.

The next implementation milestone requires verified issuer capabilities, an
operator-approved binding provisioner, a staging runtime and two isolated test
principals. Until those exist, adding advertised OAuth endpoints would be a false
capability claim. Python's single-organisation subject binding is not enterprise
multi-tenancy and must not be reused as tenant isolation proof.

## Client persistence acceptance gate

Local Codex CLI/app can retain a user-level MCP server configuration; secure
bearer environment injection or supported interactive OAuth remains necessary.
This does not imply fresh Codex Cloud tasks inherit that configuration. ChatGPT
account/workspace connections are client-managed and depend on available product
features and policy. Server-side OAuth cannot force either client to attach tools.

Use current official references when performing acceptance:
[Codex MCP](https://developers.openai.com/codex/mcp/),
[ChatGPT developer mode](https://platform.openai.com/docs/guides/developer-mode),
[MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization),
[OAuth security BCP](https://www.rfc-editor.org/rfc/rfc9700),
[resource metadata](https://www.rfc-editor.org/rfc/rfc9728).
These are design references, not a claim that live product documentation or a
specific installed client version was verified in this runtime.

Acceptance must record client/version/plan/workspace, resource/issuer, deployment
SHA, protocol and a redacted connection identifier. Authenticate once using the
client's supported connection UI; verify `tools/list`, own identity and a safe
read-only authorized call. Open a genuinely fresh task/conversation with no copied
workspace config, task-local token or setup script. Prove the connection remains
attached and discovers the expected scoped tools. Repeat after access-token expiry
and refresh, reconnect/restart, scope reduction, revocation and disconnect. Use a
second tenant/agent to test isolation and wrong audience/issuer denial. Record PASS,
FAIL and BLOCKED independently; never paste credential material into evidence.

## Evidence at audit time

- **PASS:** local source audit; focused edge transport/auth/Access/audit tests.
- **FAIL (baseline, remediated locally):** invalid supplied bearer could silently
  discover anonymous tools. Regression tests now require HTTP 401.
- **BLOCKED:** live gateway probes returned HTTP 403 for `/mcp` and metadata;
  portal requests failed to connect in this runtime. No production auth conclusion
  follows from these network results. No authenticated live probe was attempted.
- **BLOCKED:** fresh Codex Cloud/ChatGPT task acceptance, issuer PKCE/refresh,
  portal identity mapping, staging tenant isolation and production deployment.

No deployment or merge is authorized by this document. Independent review and
client/issuer staging acceptance remain required before claiming persistence.

### Local verification receipt

Runtime: Python 3.12.14; Node 22.16.0 (CI-pinned) and 24.22.1. Official SDKs:
Python MCP 2.0.0 and TypeScript MCP 1.32.2. Local checks are not the full CI matrix.
Commands executed from the repository:

| Command | Result |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests -v` | PASS: 208 tests, including OAuth and official Python SDK paths |
| `node --test deployment/cloudflare/*.test.mjs` | PASS: 47 tests on both Node runtimes, including 2 official SDK cases, deployment verifier, Worker/Access/audit/workspace; zero failed/cancelled/skipped |
| `python deployment/cloudflare/schema_migrations_test.py -v` | PASS: 6 SQLite schema/audit tests |
| `node --check deployment/cloudflare/worker.js` | PASS |
| `python -m compileall -q src tests scripts` | PASS |
| `python scripts/skillctl.py validate` | PASS |
| `python scripts/docs_check.py` | PASS |
| `.venv/bin/python scripts/demo_local.py` | PASS: temporary database, valid audit, no external actions |

The live smoke workflow accepts both the deployed legacy tool-error denial and
new HTTP 401 denial, without deploying either. Offline Worker tests require the
new 401 behavior. Existing signed-Access SDK acceptance is synthetic and does not
exercise a real OAuth browser flow. Database authentication fixtures verify the
expiry/revocation/disable predicates and loss of a valid principal; they do not
substitute for staging D1 isolation or issuer refresh/reuse tests.
