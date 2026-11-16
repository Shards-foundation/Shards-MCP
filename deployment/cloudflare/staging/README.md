# PR #47 staging security acceptance gate

Candidate source: `c99fa809bc17e71859466ce23b5f306ed05118ff` (PR #46).
Primary skill: security-review; supporting: client-integration. This PR changes the
staging harness only. It does not authorize resource creation, deployment, Access,
billing, credential changes or merge. Keep draft for Claude's independent re-review.

## Review corrections and evidence

[Independent F1–F3/F4/F6/F7/F9 review](https://github.com/Shards-foundation/Shards-MCP/pull/47#issuecomment-6927184149)
reviewed `a7281cbbc81a696a4a5778e6817800b2c6b73b4a`. The earlier empty-inbox and
self-manifest checks were insufficient security evidence. They have been replaced.

| Requirement | Correction / executable evidence |
| --- | --- |
| F1 populated isolation | Seven local principals; nonempty distinct messages, tasks and audit rows; exact own-row content checks; same-tenant other-owner and foreign-tenant canaries |
| F1 mutation sensitivity | Six mutations remove tenant or owner predicates and their corresponding SQL bindings, one per message/task/audit query; every mutation must be killed by the real workerd/D1 test |
| F2 exact approved identity | Mandatory reviewed approval file, exact account ID/name, workers.dev subdomain, both hostnames/names, D1 UUID/name/jurisdiction, deployment/version IDs and artifact digests |
| F3 independent proof | Read-only Cloudflare API: account, subdomain, D1 metadata, both deployments at 100%, version and current binding sets, downloaded single-module bytes; before/after checks; manifest is supplementary only |
| F4 authority denials | Exact HTTP status and authorization error text; forbidden task arguments are syntactically valid, so an unrelated parser/validation error cannot pass |
| F6 fixture hygiene | Root `/work/` is ignored; tests create exclusive 0600 fixtures and execute `git check-ignore --no-index` |
| F7 negative paths | Invalid credentials across handshake, discovery, calls, ping and notifications; malformed schemes, expired/disabled keys, joint Access/bearer boundaries, parallel storage failures and post-revocation requests |
| F9 pin lifecycle | Immutable Git source is required; no HEAD fallback after squash or branch deletion; see source-pinning procedure below |

Canaries intentionally include a foreign-tenant row referencing the caller's agent
ID. The schema permits these independent tenant/agent references. Normal globally
unique agent IDs would otherwise mask a removed tenant predicate. Other canaries
have the correct tenant but wrong recipient/assignee/audit agent. None of these rows
are sent to hosted D1 in this task; they exist only in ephemeral local test stores.
The reader and foreign fixture scopes include message/task read for those tests;
no real principal is granted or broadened. Existing hosted tokens are untouched.

## Existing staging resources: preserve them

The operator review confirms existing zero-cost Shards-inc Workers Free staging,
with a dedicated EU D1. Read-only API checks on 16 November 2026 confirm:

Exact account, subdomain, Worker/D1, deployment/version and digest identifiers are
kept in an operator-approved **0600 file under ignored `work/`**, not published to
GitHub. The existing Shards-inc Free-plan same-account profile was checked locally
and is supported; neither a new account nor a host-specific ban is introduced.
The main Worker has its dedicated EU D1 and marker; the fault Worker has the marker
only. Both exact versions are active at 100%, with public URLs and previews disabled.

[local-target.example.json](local-target.example.json) contains **synthetic** local
identities for CI only. It is not operational approval. Copy its field structure
into a protected local profile and have the operator independently approve the
exact real identities. The builder requires explicit approval, emits `account_id`,
disabled workers.dev/previews and no routes, and does not infer a trusted account
or hostname from a regex. The hosted CLI requires the profile to be owner-only.
Alternate accounts likewise require a separately reviewed exact profile. Generated
configs set `no_bundle: true`; main and fault entries are `main/worker.js` and
`fault/worker.js`. Both upload a module named `worker.js` without esbuild rewriting
the reviewed bytes. Each entry has its own directory so Wrangler cannot collect
the root schema SQL as an extra text module. Tests assert each module directory,
entry basename and exact artifact bytes. Wrangler 4.163.0 local dry-runs (empty API
credentials, isolated configuration) produced one `worker.js` for each Worker,
byte-identical to the reviewed artifact. No upload/deployment occurred. This
fixes future upload reproducibility, not the existing hosted digest mismatch.

Shared-account request/D1 quotas are **not separate-account isolation**. That stronger
guarantee remains BLOCKED. The earlier billing-subscriptions API returned 403 and
usage-model read 415; no billing access or upgrade was requested. The operator's Free
plan statement does not turn unverified free capacity into a PASS. Do not create a
replacement account/database/Worker. No hosted token rows were read in this correction.
The operator reports the six existing test tokens revoked; they remain untouched.

## Independent deployed identity

[verify-deployment.mjs](verify-deployment.mjs) makes bounded GET requests only to
`api.cloudflare.com`, using a separate protected read credential. Redirects are denied;
remote bodies and credentials never enter receipts. It verifies account identity,
account subdomain and D1 metadata, then for **both** Workers verifies:

1. Exact active deployment and version, with one version at 100%.
2. Exact bindings in version metadata and current settings: marker, main staging
   D1 only, and no extra binding or D1 on the fault Worker.
3. Exactly one named downloaded module, with byte-for-byte SHA-256 equal to the
   reviewed transformed artifact. Etags and the Worker's manifest are insufficient.
4. Active deployment again after content download, and the same full proof after
   acceptance. A race, split rollout, changed binding or digest mismatch is FAIL.

Unavailable deployed bytes or read access are BLOCKED. A readable digest mismatch
is FAIL. Disabled URLs are BLOCKED for hosted acceptance. These checks run before
any synthetic token is sent, including to the fault Worker. The approval digest
and metadata proof are compared after acceptance. No cached receipt or self-attested
manifest alone can authorize a run. Local tests explicitly label hosted identity
BLOCKED rather than manufacturing a Cloudflare proof.

Current read-only download evidence does **not** match the reviewed builder:

The expected and observed digests for both modules were compared through read-only
Cloudflare download evidence. Both differ. Exact live deployment identifiers and
hash receipts stay with the protected approval/evidence files rather than in the
PR; expected artifact digests can be reproduced with the local builder.

This is **FAIL deployed-artifact identity**, not permission to adopt the observed
hash or redeploy. Both versions, disabled URLs and resources remain unchanged.
The read-only comparison below identifies the divergence; no hosted bearer request,
D1 mutation, hash approval change or deployment was performed.


### Independent artifact comparison at reviewed head e509fb4

The exact builder modules were checked against reviewed commit
`e509fb4d04ed54eca838c008d2992fa77555d15e` before generating expected bytes for
the protected approved target. Cloudflare's authenticated script-download API
supplied the deployed multipart payloads. Active deployment/version and binding
metadata matched the approved profile and stayed unchanged before/after download;
both public URLs and previews remained disabled. No Worker manifest endpoint was
used as identity evidence.

| Byte comparison | Main | Fault |
| --- | --- | --- |
| Expected bytes | 226,065 | 226,154 |
| Downloaded module bytes | 226,050 | 226,139 |
| First divergent byte (zero-based) | 225,500 | 225,565 |
| First divergent builder/module line (one-based) | 860 | 860 |
| First expected / observed byte | space / `c` | space / `c` |
| Observed edit groups in wrapper | 8 | 9 |

The first divergence is the second indentation space before `const u`: the builder
has two spaces, the deployed wrapper has one. Later wrapper statements have been
joined onto one line, and the final newline is missing. Every observed edit is
whitespace in the appended staging wrapper; the preceding transformed candidate
source and manifest bytes are identical. Wrapper lexical token streams also match.
A separate Python MIME parser reproduced the same extracted bytes as the strict
Node parser, ruling out multipart framing as the observed difference.

Likely cause: an upload built from a separately reconstructed/reformatted wrapper,
rather than the builder's exact output file. Whole-module esbuild rewriting is not
supported by this comparison because the candidate-code prefix is unchanged. The
uploader's actual procedure was not observed, so that procedural cause remains an
inference. No semantic or deployment approval follows from token equality.

Raw downloads, full diffs, identities and hash receipts stay in protected, ignored
`work/` files. The approved hashes and strict byte comparison are unchanged:
**FAIL deployed-artifact identity** remains the hosted outcome.

### Transport BLOCKED evidence correction

A fetch rejection now throws `GateBlocked('TRANSPORT_UNAVAILABLE')`, preserving the
static reason through the existing receipt recorder. A regression injects both a
network error and timeout, requires exact BLOCKED evidence, verifies that the run
stops after the failed manifest request, and checks that raw diagnostics and
synthetic tokens are absent from the report. It failed with empty evidence against
e509fb4 and passes with the correction.

## Final review remediation

See [the findings and verification matrix](REVIEW-REMEDIATION.md) for the final
Codex, Cubic, CodeAnt and Qodo review reconciliation. Interrupted response streams
now preserve static BLOCKED evidence; size/digest/authority assertions still fail.
The public `localRuntime` and verifier-override switches are rejected. Only a
transport constructed by the network-disabled local workerd harness receives the
local exemption, through an internal object-identity registry. Copying or overriding
its options loses that exemption and requires the full independent verifier.

Protected reads traverse directories with Linux descriptor-relative `O_NOFOLLOW`,
open the file once, validate owner/mode/type/link count/size with `fstat`, and read
that descriptor. Bounded reads and a second stat reject detected in-place changes.
Outputs use exclusive creation in a **new** 0700 directory under ignored `work/`;
files are 0600. Existing directories/files, symlink ancestors and public `work/`
are refused, not overwritten or chmodded. Choose a new output directory per run.
The helper safely creates missing `work/` on a clean checkout. Linux with procfs is
required; other platforms block. A malicious process with the operator's own UID
or root can still move/read private files or modify this program; this is not a
sandbox against a compromised operator account.

Hosted CLIs require `--receipt work/new-name.json`. They create exclusive 0600
receipts through the same protected directory traversal, **before** input reads or
network activity. The held descriptor is completed once, so a pathname swap cannot
redirect the evidence. An interrupted process can leave an empty receipt; treat
that as incomplete/BLOCKED and choose a new filename. The CLIs never print live identity
proofs to stdout, and refuse existing files or escapes. Do not redirect proof JSON
with the shell or commit operator profiles. A missing/unreadable protected input
is BLOCKED; an unsafe file's deliberate permission check remains FAIL.

Fixtures default to two hours, bounded to 30–240 minutes with
`node deployment/cloudflare/staging/fixtures.mjs work/new-fixtures --lifetime-minutes 120`.
Complete separately authorized before/revoke/after runs within that window. The
revocation row requires at least 30 seconds remaining both before and after its
requests; expired/near-expiry fixtures are BLOCKED, never evidence of revocation.
This does not authorize provisioning or changing the existing revoked credentials.

Optional staging Access bindings require an explicit protected approval `access`
object with `team`, `audience` and `connect_audience` strings. The builder and
verifier require exactly those three approved plain-text values on the main Worker;
the fault Worker remains marker-only. Profiles without this block still reject
all Access bindings. No Access configuration is added to the existing profile or
Cloudflare by this correction. Hosted Access remains BLOCKED until independently
approved and configured; local signed identity tests use synthetic keys only.

## Exact local commands

From the existing PR #47 branch, use Node **22.16.0**:

```sh
node --version
# Before npm/cache creation, safely create or verify private work (no credentials).
node deployment/cloudflare/staging/protected-file.mjs --init-work
umask 077
npm ci --prefix deployment/cloudflare/staging --ignore-scripts --audit=false --fund=false
npm test --prefix deployment/cloudflare/staging
node deployment/cloudflare/staging/build.mjs --out work/pr47-stage --approval deployment/cloudflare/staging/local-target.example.json
node --check work/pr47-stage/main/worker.js
node --check work/pr47-stage/fault/worker.js
node --test deployment/cloudflare/worker.test.mjs deployment/cloudflare/audit_atomic.test.mjs deployment/cloudflare/workspace.test.mjs deployment/cloudflare/verify_release_deployment.test.mjs
python3 deployment/cloudflare/schema_migrations_test.py -v
python3 scripts/docs_check.py
python3 scripts/skillctl.py validate
```

The locked runtime is Miniflare 4.20260730.0, with undici 7.30.1 and sharp 0.35.5
overrides. Local D1 is ephemeral and outbound network is disabled; signed Access
uses a temporary RSA key/JWKS. No synthetic fixture is uploaded. The local matrix
has explicit BLOCKED rows for hosted pre/post identity and an empty-header transport
limitation. Every other local boundary must PASS. Six owner/tenant mutations must
fail their exact row assertions. A separate test proves denial assertions reject
an unrelated `isError: true` validation error.

**Empty Authorization caveat:** the local HTTP adapter drops an empty header before
workerd sees it, as measured in an independent echo-runtime test. This path is
BLOCKED locally, not PASS or silently removed. The hosted runner still requires
401 for an empty supplied header. Existing VM-level empty-header assertions remain
unchanged. Auth scheme case-insensitivity requires separate PR #46 review; no
interoperability claim is made for lowercase `bearer` by this pinned candidate.

## Prepared hosted commands: read-only identity first

No resource creation, deployment, URL enablement, seeding, token revocation or
Access/billing changes are authorized now. Do not reuse the six revoked tokens.
For an independently authorized **read-only** verification session, a protected
0600 file may hold a dedicated Cloudflare read token. It is sent to the Cloudflare
API only, never the Worker; do not put a token value in argv or enable shell tracing.

```sh
export STAGING_APPROVAL_FILE="$PWD/work/pr47-approved-target.json"
# STAGING_CF_READ_TOKEN_FILE must point to an existing protected credential file.
umask 077
node deployment/cloudflare/staging/verify-deployment.mjs --receipt work/pr47-deployment-proof.json
```

Current mismatched bytes require FAIL; unavailable bytes/permissions require BLOCKED.
Even if an independent read later matches, disabled public URLs still block hosted
acceptance. After separately approved remediation and fixture provisioning, the
prepared runner requires a protected **version 2** fixture file and exact URLs:

```sh
# STAGING_URL and STAGING_FAULT_URL must be the exact protected profile origins.
# STAGING_FIXTURES_FILE: existing 0600 version-2 synthetic fixture JSON.
# STAGING_ACCESS_FILE: optional 0600 isolated staging issuer/token, once configured.
node deployment/cloudflare/staging/acceptance.mjs --receipt work/pr47-before.json
# Only after a separately authorized, completed revocation in staging D1:
node deployment/cloudflare/staging/acceptance.mjs --revoked --receipt work/pr47-after.json
```

These commands do not change token state themselves. Identity verification occurs
before and after each pass. Exit 0 means all rows PASS; 1 means FAIL; 2 means BLOCKED.
No retries/load tests, arbitrary fetches or external tool executions are performed.
Bound future runs conservatively (at most two passes, fewer than 400 Worker requests),
accounting for shared quotas and per-agent budgets. Hosted valid-bearer isolation,
actual revocation and separate staging Access login remain incomplete.

## Immutable source pin after squash

The builder uses `git show` on the exact SOURCE commit in [artifact.mjs](artifact.mjs).
It never switches to HEAD or accepts a Worker's claimed hash. Full-history CI and
this stacked branch currently retain the candidate. Before deleting/rebasing/squashing
its last reachable ref, maintainers must retain an independently reviewed immutable
ref/archive for the pin, or explicitly re-pin to a reachable immutable merge commit.
Verify the source and schema bytes against the recorded SHA-256 first:

```sh
python3 - <<'PIN'
import hashlib, subprocess
expected = {
    'deployment/cloudflare/worker.js': '7a19a15a01311142348307d610249e367d79eea58339098f69e210555710e3a7',
    'deployment/cloudflare/schema.sql': '51c86764014f87b7c1abf30f9636c23d495ab0847aa3441a71013040314ffdd3',
}
for filename, digest in expected.items():
    data = subprocess.check_output(['git', 'show', 'c99fa809bc17e71859466ce23b5f306ed05118ff:' + filename])
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit('FAIL: pinned source digest mismatch')
print('PASS: both pinned source digests match')
PIN
```

Worker source SHA-256: `7a19a15a01311142348307d610249e367d79eea58339098f69e210555710e3a7`.
Schema SHA-256: `51c86764014f87b7c1abf30f9636c23d495ab0847aa3441a71013040314ffdd3`.
An unavailable pin is BLOCKED, not a reason to rebuild from an unreviewed branch.
Re-pinning changes the embedded marker and transformed artifact identity even if
source bytes match, and therefore requires fresh independent review, expected hashes,
version/deployment approval and separately authorized rollout. None is done here.

## PASS / FAIL / BLOCKED and residual risks

| Boundary | Evidence / status |
| --- | --- |
| F1 populated own/foreign/other-owner reads | PASS in workerd/D1, with six killed predicate mutations |
| F2 approved account/host policy | PASS locally and read-only metadata; existing Free same-account mode retained |
| F3 verifier rejection and race tests | PASS locally; no trust in self manifest or etags |
| Current deployed module identity | FAIL: readable hashes differ from reviewed artifacts |
| Hosted token tests and D1 revocation | BLOCKED/incomplete; existing URLs disabled and tokens reported revoked |
| Staging Access app/login | BLOCKED/not configured; only synthetic local Access proof |
| Empty Authorization over local adapter | BLOCKED: adapter drops the field; no PASS claim |
| Separate-account quota isolation / free capacity | BLOCKED: same-account shared quotas, billing verification unavailable |
| Native fresh-task Cloud persistence | BLOCKED: requires actual supported client acceptance |

Local test success does not clear hosted FAIL/BLOCKED rows. Cloudflare account/API
integrity and the reviewed approval file remain trust anchors. Before/after reads
detect observed changes but cannot provide atomic fencing against a privileged
concurrent operator. Do not accept unknown mutations, blindly retry or weaken an
assertion to get PASS. Coordinate PR #46 separately: the live smoke legacy-200
allowance does not prove this auth fix deployed; per-request D1 auth lookups need
throttling/DoS review, and HTTP auth schemes need case-insensitive handling.

Rollback is a revert of this correction only. Local tests dispose their runtimes
and D1 stores in `finally`; remove only scratch directories you created under
ignored `work/`, keeping redacted receipts as needed. Do **not** tear down or
modify the existing disabled staging resources, Access apps or revoked token rows
as part of this task. No production rollback, credential rotation or restore is
needed because production was unchanged. Independent Claude re-review is still
required; no merge/deploy decision follows from this gate.

### Prior verification at reviewed head 0e3e939

Node 22.16.0, clean `npm ci` using the committed lock: **22 staging tests PASS**,
zero failed/cancelled/skipped. This includes the six independently killed SQL
mutations, exact denial rejection, independent API identity/race tests, protected
fixture ignore, builder CLI, pin failure, transport-limit and network/timeout evidence tests. The local
boundary matrix has 11 PASS and three explicitly BLOCKED hosted/transport rows
before and after revocation; those are not promoted to hosted PASS.

Existing exact-pinned edge/official SDK regressions: **47 PASS**. Python 3.12.14:
**208 PASS**. SQLite schema/audit: **six PASS**. Source/artifact syntax, compile,
documentation, skill validation and diff checks passed. Dependency audit reports
zero known advisories for the locked staging package. Exact-head CI and Claude's
fresh independent read-only review are reported separately on the draft PR.


Automatic approval review rejected publishing the live Cloudflare identifiers to
GitHub. They are retained in protected local configuration; this PR publishes only
synthetic examples and verification code. This does not relax the exact identity
checks or authorize any new Cloudflare operation.
