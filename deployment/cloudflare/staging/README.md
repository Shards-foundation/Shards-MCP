# PR #46 isolated staging acceptance gate

Candidate: `c99fa809bc17e71859466ce23b5f306ed05118ff` (PR #46).
This is a **separate draft infrastructure/test change**, stacked on that candidate.
It does not deploy a Worker, provision a database, change Access or certify native
Codex Cloud/ChatGPT persistence. Primary workflow: security-review; supporting:
client-integration. Production release decision: **NO-GO** from this gate alone.

## Infrastructure audit (16 November 2026)

Repository evidence: [edge operations](../README.md),
[source reconciliation](../PRODUCTION_RECONCILIATION_20261115.md),
[PR46 audit](../../../docs/native-mcp-integration.md),
[existing live smoke](../../../.github/workflows/edge-smoke.yml) and
[post-deployment verification](../../../.github/workflows/edge-production-release-gate.yml).

- The edge Worker `shards-mcp-edge` uses `EDGE_DB`, `ACCESS_TEAM`, `ACCESS_AUD`,
  `CONNECT_ACCESS_AUD` and `HUB_REGISTRY_AUD`. It is separate from Python/SQLite.
  Do not copy the production binding values or credentials into staging.
- Existing smoke checks call production public endpoints. The manual release gate
  verifies an active production version and custom-domain association with a
  read-only token. Neither is an isolated authenticated staging acceptance gate.
- Production Worker source hardcodes its origin/hostname. There is no tracked
  Wrangler staging configuration. VM fixtures mock D1; existing schema tests use
  SQLite and signed SDK tests use synthetic Access identity.
- Read-only Cloudflare APIs confirmed **12 Workers and five D1 databases**, including
  `shards-mcp-edge` and `shards-mcp-edge-prod`. No Worker/database with the proposed
  staging names exists. The account workers.dev subdomain is `bow-eucalyptus`.
  No production database rows, token values or secret bindings were read.
- **BLOCKED_QUOTA:** `GET /accounts/{account_id}/subscriptions` returned HTTP 403;
  this connection lacks Billing Read and OAuth cannot cover that endpoint. The
  script usage-model read also returned HTTP 415. Worker/D1 inventory is readable,
  but plan entitlement, current usage, free capacity and incremental cost are
  unverified. These are access/verification blockers, **not evidence of exhaustion**.
  Do not buy a plan or expand production permissions to clear them.
- **BLOCKED_ACCESS:** a separately approved staging Access app/audiences and actual
  staging login are absent. Production Access apps/policies must remain unchanged.

## Isolation design

Two dedicated Worker names: `shards-mcp-pr46-staging` and
`shards-mcp-pr46-staging-fault`; one **new, empty** D1 database named
`shards-mcp-pr46-staging`. Prefer a separate existing Free test account; if using
an existing account, verify spare free quotas and interference limits first.
Only workers.dev hostnames are used: no custom domain, production route, queue,
cron, service binding, registry federation, external tasks or copied data.
The fault Worker has **no D1 binding**, and omits `EDGE_DB` explicitly.

[build.mjs](build.mjs) reads Worker and schema bytes using `git show` at the exact
candidate SHA. It substitutes only the hardcoded MCP hostname, changes the export
for a staging wrapper, and records original-source, schema and artifact SHA-256.
It never edits the production Worker. The wrapper requires the expected staging
origin and marker, allows only MCP and metadata paths, and denies operator UI/API
and hub routes. Its manifest identifies this **transformed staging artifact**;
it is not proof of an unchanged production binary or a provider deployment ID.

Generated Wrangler configs have empty routes, no preview URLs, no Access settings,
no secrets and no production D1 binding. The zero UUID placeholder is deliberately
unusable for hosted deployment. The builder rejects the known production MCP D1
ID. An operator must independently verify **any** real D1 ID belongs to the new
staging database, not another service. Creation/deployment are outside this task.

Local tests use workerd via Miniflare **4.20260730.0** (locked), with patched
`undici` 7.30.1 and `sharp` 0.35.5 overrides, plus ephemeral Miniflare D1, and a CSPRNG fixture per
run. Only token hashes enter D1/SQL; raw synthetic tokens stay in memory or exclusive
0600 files under `work/`. Token TTL is one hour. The revocation step changes the
actual D1 row and repeats authenticated requests. Local Access uses a temporary RSA
key and mocked JWKS with all outbound network disabled. This verifies signed-token
validation without changing trust rules or using production credentials; it does
not prove a real Access browser flow. No mock issuer is configured in hosted configs.

## Exact local commands (safe, no Cloudflare credentials)

From the repository root on this draft branch; Node must be **22.16.0**:

```sh
node --version
npm ci --prefix deployment/cloudflare/staging --ignore-scripts --audit=false --fund=false
npm test --prefix deployment/cloudflare/staging
node deployment/cloudflare/staging/build.mjs --out work/pr46-stage --subdomain acceptance-local
node --check work/pr46-stage/worker.js
node --check work/pr46-stage/storage-failure.js
python deployment/cloudflare/schema_migrations_test.py -v
python scripts/docs_check.py
python scripts/skillctl.py validate
```

The new [CI workflow](../../../.github/workflows/edge-staging-acceptance.yml) runs
local workerd/D1 acceptance and regression only, with `contents: read`, full Git
history and no Cloudflare secrets. It has **no deployment step**. Source SHA-256:
`7a19a15a01311142348307d610249e367d79eea58339098f69e210555710e3a7`.
Schema SHA-256:
`51c86764014f87b7c1abf30f9636c23d495ab0847aa3441a71013040314ffdd3`.

## Hosted procedure prepared for a later authorized session

**Not executed or authorized by this PR.** Before any resource creation, an operator
must confirm free capacity, request/D1 quotas, exact staging account, worker.dev
availability and a dedicated staging-only credential. Keep a copy of the inventory
and cost/quota decision. Do not reuse production API tokens, `smcp_*` keys, Access
JWTs or D1 data. Do not enable paid products or relax existing Access policies.

The commands below use Wrangler **4.163.0**, installed on the operator's trusted
machine. No Cloudflare login/token is needed for the local commands above. For
hosted commands, the operator supplies an appropriate staging-only credential
through the CLI's protected environment, with shell tracing disabled. Do not put
credentials into argv, this document, CI secrets for production or output files.

After **separate authorization** for provisioning, a new empty database and two
Workers may be created; the account and new ID must be confirmed out of band:

```sh
wrangler --version
export CLOUDFLARE_ACCOUNT_ID="${STAGING_ACCOUNT_ID:?Set the dedicated staging account first}"
node deployment/cloudflare/staging/build.mjs --out work/pr46-stage --subdomain "$STAGING_SUBDOMAIN" --account-id "$STAGING_ACCOUNT_ID"
wrangler d1 create shards-mcp-pr46-staging --jurisdiction eu --config work/pr46-stage/wrangler.json
node deployment/cloudflare/staging/build.mjs --out work/pr46-stage --subdomain "$STAGING_SUBDOMAIN" --database-id "$STAGING_D1_ID" --account-id "$STAGING_ACCOUNT_ID"
node deployment/cloudflare/staging/fixtures.mjs work/pr46-stage-fixtures
wrangler d1 execute shards-mcp-pr46-staging --remote --config work/pr46-stage/wrangler.json --file work/pr46-stage/schema.sql
wrangler d1 execute shards-mcp-pr46-staging --remote --config work/pr46-stage/wrangler.json --file work/pr46-stage-fixtures/seed.sql
wrangler deploy --config work/pr46-stage/wrangler.json
wrangler deploy --config work/pr46-stage/wrangler-fault.json
```

These commands change **only dedicated staging resources** and must not be run now.
Before running them, compare account and D1 IDs with all existing production/service
IDs, inspect the generated configs, record both uploaded Worker version IDs and
artifact hashes, and verify their active deployment/bindings independently via the
Cloudflare API. The runner's manifest check is an additional guard, not a substitute
for provider evidence. Cap the run at two passes (under 150 HTTP requests and a small
number of D1 rows); no load test, retry storm, DNS or GitHub fetch is performed.
D1 quotas are account-shared unless a separate account is used.

Hosted acceptance (after an independently approved staging deployment):

```sh
export STAGING_URL="https://shards-mcp-pr46-staging.${STAGING_SUBDOMAIN}.workers.dev"
export STAGING_FAULT_URL="https://shards-mcp-pr46-staging-fault.${STAGING_SUBDOMAIN}.workers.dev"
export STAGING_FIXTURES_FILE="$PWD/work/pr46-stage-fixtures/fixtures.json"
node deployment/cloudflare/staging/acceptance.mjs > work/pr46-stage-before.json
wrangler d1 execute shards-mcp-pr46-staging --remote --config work/pr46-stage/wrangler.json --file work/pr46-stage-fixtures/revoke.sql
node deployment/cloudflare/staging/acceptance.mjs --revoked > work/pr46-stage-after.json
```

The runner emits only static case names, statuses and reason codes, never headers,
tokens, response bodies or identities. Exit **0 = all PASS, 1 = FAIL, 2 = BLOCKED**.
It refuses production/shared hostnames and checks the staging manifest **before
sending credentials**. Redirects are never followed. Repeat with a **fresh** database
and fixture directory; old/revoked/expired fixtures intentionally fail.

Without a dedicated Access application, the two hosted `/connect` cases remain
**BLOCKED**, so exit 2 is expected; do not interpret other PASS rows as full acceptance.
After separately reviewed staging-only Access setup, its three non-secret bindings
(`ACCESS_TEAM`, `ACCESS_AUD`, `CONNECT_ACCESS_AUD`) must be configured on the staging
Worker, with distinct application audiences and no production app changes. A 0600
file referenced by `STAGING_ACCESS_FILE` can then contain `issuer` and a current
staging-only Access `token`; do not echo this file. Re-run the same gate to prove
metadata, challenge, signed identity and denial of agent privileges. The fault
Worker needs no Access setup. This PR does not provision Access or implement OAuth.

## PASS / FAIL / BLOCKED matrix

| Boundary | Local result | Hosted result / evidence still required |
| --- | --- | --- |
| Exact pinned source and staging guards | PASS: Git SHA, hashes, forbidden-host/config guards | BLOCKED: no staging version/bindings provisioned |
| Invalid, unknown, expired, disabled bearers | PASS: HTTP 401 in workerd | BLOCKED: hosted run not executed |
| Anonymous public discovery and private denial | PASS: seven public tools, private call denied | BLOCKED: hosted run not executed |
| Valid bearer, identity, exact tool scopes | PASS: separate synthetic principals | BLOCKED: hosted D1 acceptance |
| Scope and tenant isolation | PASS: D1 queries with two synthetic tenants | BLOCKED: hosted D1 acceptance |
| Revocation | PASS: D1 update, repeated subsequent 401 | BLOCKED: hosted D1 update/run |
| Storage failure | PASS: separate Worker, omitted D1, sanitized 503 | BLOCKED: separate hosted fault Worker |
| Root and `/mcp` metadata isolation | PASS: 404, no redirect/authority | BLOCKED: hosted artifact verification |
| `/connect` path metadata and challenge | PASS: unchanged resource/issuer mapping | BLOCKED: dedicated staging Access app |
| Signed `/connect` identity, no agent grants | PASS: temporary RSA/JWKS, no network | BLOCKED: real staging Access login |
| Credential-free CI and regression | PASS locally; draft CI reported separately | Hosted permission/capacity unverified |
| Free quota / billing entitlement | BLOCKED: Billing API 403; usage-model API 415 | Operator review required; no paid upgrade |
| Native fresh-task Cloud persistence | BLOCKED: outside this gate | Actual supported client acceptance required |

**FAIL:** no remaining local acceptance failures at preparation time. FAIL conditions
include authentication bypass, unexpected metadata redirect, wrong scope/tenant,
revocation failure, storage-failure fallback, unknown staging identity or malformed
responses. Any FAIL is NO-GO; do not weaken assertions to obtain a green result.
All local PASS entries apply to the transformed staging artifact and isolated D1,
not production or a Cloudflare-hosted deployment.

## Teardown and rollback

Local tests dispose both runtimes and their ephemeral databases in `finally`.
Remove only the generated directory and fixture directory you created; keep redacted
matrix/hash receipts as evidence, then delete the synthetic token file. Package
`node_modules/` and `work/` artifacts are not committed. No production rollback is
necessary because no production service was changed.

After a future separately authorized hosted run, first confirm the account,
Worker names, staging D1 UUID and zero production routes. Stop/delete **both staging
Workers first**, then remove **only the staging database**:

```sh
wrangler delete --name shards-mcp-pr46-staging --config work/pr46-stage/wrangler.json
wrangler delete --name shards-mcp-pr46-staging-fault --config work/pr46-stage/wrangler-fault.json
wrangler d1 delete shards-mcp-pr46-staging --config work/pr46-stage/wrangler.json
```

Review the CLI confirmation before each deletion. Remove any separately created
staging Access app only after verifying its distinct ID; never delete or modify
existing Access applications. Re-inventory names to prove teardown. Delete protected
fixture/token files. No production database drop, credential rotation or data restore
is involved. If a test fails, preserve safe evidence and tear down staging rather
than retrying unknown mutations. Source rollback is to revert this separate PR;
staging redeployment, if later authorized, uses a previously recorded staging-only
artifact/version with its matching empty test schema and freshly minted fixtures.


## Preparation verification receipt

Local runtime: Python 3.12.14, Node 22.16.0, Miniflare 4.20260730.0. Acceptance:
three automated tests, including a ten-row matrix before and after real D1
revocation, all PASS with zero failed/cancelled/skipped tests. Existing edge suite:
47 PASS; Python suite: 208 PASS; SQLite schema/audit: six PASS. Syntax, generated
artifact checks, skill validation and documentation checks passed. Dependency
review found vulnerable transitive packages in an older runtime candidate; the
committed lock uses the current runtime and patched overrides. `npm audit` reports
zero known advisories for this staging package at preparation time; this is not an
independent security certification. Wrangler 4.163.0 D1 command syntax was checked
with `--help` only. No hosted provisioning/deployment/test was executed.
