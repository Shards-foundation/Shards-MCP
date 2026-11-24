# Opt-in Shards-Kernel GitHub issue-label bridge

**Status** — The Edge bridge is source-only and disabled by default. Live MCP
Worker-to-Kernel acceptance is pending.

**Kernel dependency** — Shards-Kernel PR #162 merged at
`61cc6e82ee25aefa0a9c95ae75aedda42a7090ae`, the source revision reported for
the Oracle pilot. Pin the pilot build to its source SHA. Both that revision
and the public `v0.1.4` tag report version `0.1.4`, and the tag resolves to
`3106a0df39ec8c8e9abdd4071e92167a3ef085b4`.
[Kernel PR #162](https://github.com/Shards-foundation/Shards-kernel/pull/162) ·
[Public tag](https://github.com/Shards-foundation/Shards-kernel/tree/v0.1.4)

## What this adds

One opt-in authenticated MCP tool on the existing Cloudflare Edge Worker:

```text
shards_kernel_issue_label(issue_number: int, label: str, permit: object, request_id: str)
```

It requests exactly one trusted kernel action:

```text
github.issue.add_label(issue_number, label)
```

The Edge maps a verified D1 `smcp_` agent to a separately provisioned kernel
actor, adds the gateway identity/token and a Cloudflare Access service token,
and forwards the caller's operator-signed v2 permit to the kernel. The kernel,
not the Edge, verifies the permit, actor, arguments, nonce, replay state,
journal and GitHub read-back.

The Edge does **not**:

- sign permits, hold the permit issuer private key, or verify the Ed25519
  signature as the authority;
- hold a GitHub token, call GitHub, or accept a GitHub credential;
- accept a client-supplied actor, destination, URL, origin, authorization
  header or credential;
- expose an arbitrary URL-fetch, shell, delete-label, merge, close or create
  issue capability;
- retry an ambiguous external effect;
- add a second MCP runtime or mock a production gateway.

## Trust boundary

```text
verified smcp_ agent (D1 hashed token, kernel:github_label scope)
        |
        | MCP tools/call: issue_number, label, permit, request_id
        v
Cloudflare Edge Worker
  - derives the caller from the D1 principal, never from arguments
  - maps tenant/agent id -> exact kernel actor + kernel bearer (Worker secret)
  - adds gateway identity/token + Access service token (Worker secrets)
  - structural permit checks only; no signing and no authority
        |
        | HTTPS POST https://<private-tunnel-host>/submit
        | User-Agent: Shards-MCP-Kernel-Bridge
        | redirect: manual, 10 s timeout, 16 KiB response cap
        v
Cloudflare Access service token + private Tunnel
  - exact operator-configured origin, not user input
  - origin must not be publicly reachable
        |
        v
Shards-Kernel operator (127.0.0.1:8765 on Oracle ARM64)
  - gateway identity/token, per-agent actor-labelled bearer
  - signed v2 permit: signature, audience, subject, action, params, nonce
  - replay ledger + hash-chained audit + durable provider journal
        |
        | operator-held fine-grained GitHub token
        v
https://api.github.com  POST label, then authoritative GET read-back
```

The human approver, offline permit issuer, policy signer, kernel runtime,
Edge Worker and agent are separate identities. An agent can request an action
but cannot sign its own permit.

The Worker sets the fixed `User-Agent: Shards-MCP-Kernel-Bridge` on its
outbound POST. The value identifies the Worker service. The Access service
token, gateway credentials, actor bearer and signed permit continue to
govern the request.

`authenticate()` updates `agent_connection_activity`
(`last_authenticated_at`, `last_operation`) and `budget()` increments
`route_budgets`; neither is a per-request history.

Per-attempt auditing starts only after `authenticate()` returns a verified D1
principal. For every authenticated bridge call:

- a caller missing `kernel:github_label` gets one `kernel.issue_label.denied` /
  `SCOPE_DENIED` row before the generic `AUTH_REQUIRED` response;
- a caller over the bridge budget gets one `kernel.issue_label.denied` /
  `BUDGET_DENIED` row before the generic quota response;
- a call that reaches `kernelIssueLabel` gets
  `kernel.issue_label.attempt` / `ATTEMPTED` **before forwarding**, then
  `kernel.issue_label.<outcome>` / `<stable reason code>` after the result
  (`succeeded`/`OK`, `denied`/`KERNEL_DENIED`,
  `not_applied`/`PROVIDER_NOT_APPLIED`, `unknown`/`KERNEL_EFFECT_UNKNOWN` or a
  stable transport reason code, and so on).

If the denial audit or pre-forward attempt audit cannot commit, the Edge
returns `UNAVAILABLE: EDGE_AUDIT_UNAVAILABLE`, does not dispatch, and does not
retry automatically. If the outcome audit cannot commit after a forward, it
returns `UNKNOWN`/`EDGE_AUDIT_UNAVAILABLE`, never success, and does not retry.
The audit rows contain only tenant, agent, action, request id, status and
timestamp; they never contain the permit, kernel bearer, gateway token, Access
secret or private origin. The kernel's hash-chained audit and durable provider
journal remain authoritative for the effect.

Pre-auth, anonymous and invalid-token requests are deliberately **not** written
to the agent ledger: `runTool` returns the cheap `AUTH_REQUIRED`/401 path without
a D1 audit insert. Those network attempts belong to Cloudflare WAF/rate
limiting, not the per-agent ledger.

When the bridge is disabled or its configuration is invalid, `runTool` checks
configuration **before** the scope check, the denial audit and the bridge budget.
A caller without `kernel:github_label` receives the generic `AUTH_REQUIRED` text,
not a bridge-specific reason; a scoped caller receives
`BRIDGE_DISABLED`/`BRIDGE_NOT_CONFIGURED`. Neither path writes a
`kernel.issue_label.*` audit row or a `route_budgets` row; the existing
`authenticate()` activity upsert is unchanged. This prevents an authenticated
unscoped caller from generating bridge-specific denial writes or learning the
bridge's configuration state while the bridge is off. When the bridge is
enabled and valid, an unscoped caller still writes one `SCOPE_DENIED` row per
attempt.

Residual cost tradeoff: when the bridge is enabled and valid, an authenticated
scope/budget denial adds one D1 `audit_events` insert on top of the existing
`authenticate()` activity upsert. The pilot is capped at two agents and tokens
are revocable. Enabling therefore requires Cloudflare WAF/rate limiting and a
token-revocation runbook; if the operator requires zero extra writes on
authenticated denials, the bridge must stay disabled.

## Edge configuration

All values come from Worker bindings. None are read from MCP arguments.

| Binding | Kind | Requirement |
| --- | --- | --- |
| `KERNEL_BRIDGE_ENABLED` | variable | Exactly `1` enables the tool. Any other value disables it. |
| `KERNEL_OPERATOR_ORIGIN` | variable or secret | Exact `https://<private-tunnel-hostname>`. No trailing slash, path, query, fragment, userinfo, IP literal, `localhost`, `.local` or the public Edge hostname. |
| `KERNEL_ACCESS_CLIENT_ID` | secret | Cloudflare Access service-token client ID for the private origin. |
| `KERNEL_ACCESS_CLIENT_SECRET` | secret | Cloudflare Access service-token secret for the private origin. |
| `KERNEL_GATEWAY_IDENTITY` | variable or secret | Exact kernel `gateway.identity`; 1-128 ASCII `A-Z a-z 0-9 . _ -`, no wildcard. |
| `KERNEL_GATEWAY_TOKEN` | secret | Exact value of the kernel's `gateway.token_env`; at least 32 characters; distinct from the provider token, operator admin secret, issuer key and every actor token. |
| `KERNEL_ACTOR_MAP` | secret | JSON object with **1-2 exact** entries: `"<tenant>/<agent_id>": {"actor":"<kernel actor>","token":"<actor>.<secret>"}`. No wildcard. Never stored in D1. |
| `KERNEL_LABEL_ALLOWLIST` | variable | JSON array of 1-32 exact labels. Must be a subset of the kernel's `provider.allowed_labels`. |
| `KERNEL_MAX_ISSUE_NUMBER` | variable | Integer 1-100000. Must be less than or equal to the kernel's `provider.max_issue_number`. |

The Edge also adds the new scope `kernel:github_label` to the set of scopes the
operator console may assign. The existing role presets do not include it, so
the operator must enrol or re-enrol the two pilot agents through the
authenticated same-origin `POST /manage/api/agents` call with
`scopes:["agent:identity","kernel:github_label"]`, or add a reviewed preset in
a follow-up. A scope alone does not enable the tool: the bridge must be enabled
and the exact actor mapping must exist.

The Edge charges at most 50 bridge calls per agent per UTC day. This is an
availability limit, not an authorisation control.

## Kernel configuration handshake

The operator signs the kernel v3 configuration with the offline policy issuer.
The following values must match exactly.

| Edge binding | Kernel field | Notes |
| --- | --- | --- |
| `KERNEL_GATEWAY_IDENTITY` | `gateway.identity` | Same concrete ASCII identifier. |
| `KERNEL_GATEWAY_TOKEN` | value of the env var named by `gateway.token_env` | Use `SHARDS_KERNEL_GATEWAY_TOKEN`. |
| `KERNEL_ACTOR_MAP[].actor` | `agents[].actor` | Same kernel actor label. No dot. |
| `KERNEL_ACTOR_MAP[].token` | verifier in `agents[].token_scrypt` | Token is `<actor>.<secret>`; `token_scrypt` is computed with the kernel's `agent_token_kdf` and `SHARDS_KERNEL_AGENT_AUTH_PEPPER`. |
| `KERNEL_ACTOR_MAP` key | D1 `tenant_id` and `agent_id` | Exact `tenant/agent` pair. At most two. |
| `KERNEL_LABEL_ALLOWLIST` | `provider.allowed_labels` | The Edge list must be a subset; keep them identical for the pilot. |
| `KERNEL_MAX_ISSUE_NUMBER` | `provider.max_issue_number` | The Edge value must not exceed the kernel value. |
| n/a (offline issuer) | `issuer_keys[].public_key_hex` | Public key only. The private key stays offline and is never on the Edge or kernel runtime. |
| n/a (offline issuer) | `issuer_keys[].issuer`, `issuer_keys[].key_id` | Must match the signed permit. |
| n/a | `provider.kind` | `github_issue_label`. |
| n/a | `provider.owner`, `provider.repo` | One concrete repository. No URL or wildcard. |
| n/a | `provider.journal_db`, `audit_db` | Absolute paths on the Oracle host. |
| n/a | `provider.token_env` | `SHARDS_KERNEL_GITHUB_TOKEN`; must differ from `gateway.token_env`. |
| n/a | `port` | `8765`, loopback only. |

Minimal v3 shape (replace every placeholder; never commit real values):

```json
{
  "version": 3,
  "kernel_id": "github-issue-label-operator",
  "tools": ["github.issue.add_label", "echo"],
  "agents": [
    {
      "actor": "edge-agent-alice",
      "token_scrypt": "<64 lowercase hex>",
      "allowed_tools": ["github.issue.add_label"]
    }
  ],
  "issuer_keys": [
    {
      "key_id": "operator-policy-key-1",
      "issuer": "offline-operator-issuer",
      "public_key_hex": "<64 lowercase hex public key>",
      "revoked": false
    }
  ],
  "audit_db": "/var/lib/shards-kernel/github-operator/audit.sqlite3",
  "port": 8765,
  "provider": {
    "kind": "github_issue_label",
    "owner": "your-org",
    "repo": "your-repository",
    "allowed_labels": ["shards-agent"],
    "max_issue_number": 100000,
    "journal_db": "/var/lib/shards-kernel/github-operator/provider-journal.sqlite3",
    "token_env": "SHARDS_KERNEL_GITHUB_TOKEN"
  },
  "gateway": {
    "identity": "cloudflare-edge-prod",
    "token_env": "SHARDS_KERNEL_GATEWAY_TOKEN"
  }
}
```

Kernel environment (protected file on the Oracle host, never in this
repository):

```text
SHARDS_KERNEL_POLICY_PUBLIC_KEY_HEX=<offline policy public key>
SHARDS_KERNEL_AGENT_AUTH_PEPPER=<32+ character random pepper>
SHARDS_KERNEL_GATEWAY_TOKEN=<32+ character random gateway token>
SHARDS_KERNEL_GITHUB_TOKEN=<fine-grained GitHub token>
```

The kernel enforces that the gateway token and the GitHub provider token are
different values in different role-specific environment namespaces, and that
the gateway identity is not an agent actor. The Edge additionally rejects a
gateway token equal to an actor token or the Access secret.

## Per-agent credential provisioning on Linux

Use the helper in this repository on the protected host:

```sh
python3 scripts/kernel_bridge_provision.py \
  --tenant shards-internal \
  --agent-id <exact-enrolled-agent-id> \
  --actor edge-agent-alice \
  --out /secure/operator/kernel-bridge/alice.json
```

The script:

- writes atomically: a same-directory `O_EXCL|O_NOFOLLOW` temporary file with
  mode `0600`, `fsync`, revalidation, then `os.replace` for `--force`; without
  `--force` it uses an atomic hard-link create-if-absent, so a file that appears
  after validation is never overwritten. A failed write leaves the existing
  reviewed file byte-identical and removes the temporary file;
- rejects symlinks (including dangling symlinks), directories, non-regular
  files and output paths containing control characters;
- prints only the tenant, agent id, kernel actor, SHA-256 fingerprint, redacted
  token (`edge-agent-alice.****`) and a verifier command; the printed path is
  shell-quoted and raw control sequences are never emitted;
- never prints the bearer secret, never contacts the network and never writes
  to the Worker, D1, Cloudflare or the kernel.

The file contains two ready-to-copy structures:

- `worker_actor_map_entry`: the exact `KERNEL_ACTOR_MAP` entry.
- `kernel_agent_entry`: the actor, allowed tools and a placeholder for the
  scrypt verifier.

Compute the verifier inside the kernel virtual environment, not in a model
chat:

```sh
export SHARDS_KERNEL_AGENT_AUTH_PEPPER='<the kernel pepper>'
python -c 'import json,os;from pathlib import Path;from shards_kernel.integrations.auth import agent_token_kdf,resolve_agent_pepper;d=json.loads(Path("/secure/operator/kernel-bridge/alice.json").read_text());print(agent_token_kdf(d["kernel_token"],resolve_agent_pepper(os.environ["SHARDS_KERNEL_AGENT_AUTH_PEPPER"])))'
```

Place the printed verifier in the signed kernel configuration. Delete the
provisioning file after the Worker secret and the signed configuration have
been installed, or keep it in an encrypted operator store. Do not paste the
file, the bearer or the verifier into ChatGPT, GitHub, logs or a ticket.

The Worker secret is installed from the file without printing it:

```sh
# Read the exact entry from the protected file, then store it as a secret.
python3 -c 'import json;print(json.dumps(json.load(open("/secure/operator/kernel-bridge/alice.json"))["worker_actor_map_entry"]))' \
  | npx wrangler secret put KERNEL_ACTOR_MAP
```

If the operator uses the Cloudflare dashboard, copy the value from the
protected file into the secret field; do not copy it into a chat.

## Offline permit issuance

The permit issuer is a separate offline process. It holds the Ed25519 private
key that matches `issuer_keys[].public_key_hex`. The Edge never holds that key.

Run this in the kernel environment on the protected host:

```python
import time
from shards_kernel.issuer import sign_v2_permit
from shards_kernel.integrations.wire import permit_to_mapping
from shards_kernel.permits import PermitBuilder

now_ms = int(time.time() * 1000)
unsigned = (
    PermitBuilder()
    .issuer("offline-operator-issuer")
    .subject("edge-agent-alice")              # kernel actor, not the D1 id
    .jurisdiction("default")                  # exact kernel policy jurisdiction
    .action("github.issue.add_label")
    .params({"issue_number": 123, "label": "shards-agent"})
    .constraints({})
    .max_executions(1)
    .valid_from_ms(now_ms - 60_000)
    .valid_until_ms(now_ms + 300_000)
    .proposal_hash("approval-2026-11-24-001") # exact approval reference
    .build_unsigned_v2(
        key_id="operator-policy-key-1",
        audience="github-issue-label-operator", # exact kernel_id
    )
)
signed = sign_v2_permit(unsigned, issuer_private_key)
print(permit_to_mapping(signed))
```

The permit must satisfy all of the following:

- `version` 2 and `algorithm` `Ed25519`;
- `audience` equals the kernel `kernel_id`;
- `subject` equals the mapped kernel actor;
- `action` equals `github.issue.add_label`;
- `params` exactly equals `{"issue_number": <int>, "label": "<allowlisted>"}`;
- `max_executions` is 1;
- a bounded validity window around the kernel's system clock;
- `key_id` and `issuer` match a non-revoked `issuer_keys` entry;
- `jurisdiction` equals the kernel's active jurisdiction;
- a fresh nonce, generated by the builder;
- a non-empty `proposal_hash` that identifies the human approval.

The Edge performs structural checks on the same fields and rejects a v1
permit, a different action or subject, extra or missing params, more than one
execution, a malformed signature or permit id, and an oversized permit. The
kernel remains the authority for the signature, time window, replay and
journal.

The signed permit is a capability. Treat it as sensitive, deliver it to the
agent out of band, and do not post it in a model chat, issue or commit.

## Agent request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "shards_kernel_issue_label",
    "arguments": {
      "issue_number": 123,
      "label": "shards-agent",
      "permit": { "permit_id": "...": "signed v2 permit mapping" },
      "request_id": "req-20261124-001"
    }
  }
}
```

Any additional argument, including `actor`, `url`, `destination`,
`authorization`, `headers`, `origin`, `repository`, `token` or `credential`, is
rejected before dispatch. The Edge never reads an actor, origin, URL or
credential from the request.

## Result semantics

Only a kernel-verified read-back is reported as success, and only when the
success payload binds to the requested issue and label.

| Observation | Edge `state` | `applied` | `retryable` | Meaning |
| --- | --- | --- | --- | --- |
| Pre-auth, scope, mapping, config, permit, label or issue denial | `DENIED` | `false` | `false` | No kernel dispatch. |
| Kernel `ACCEPTED` / `ALLOW`, provider `SUCCEEDED` | `SUCCEEDED` | `true` | `false` | Label presence verified by read-back. |
| Kernel `ACCEPTED` / `ALLOW`, `already_present: true` | `SUCCEEDED` | `true` | `false` | Desired state already present; no new write. |
| Kernel `FAILED`, provider `PROVIDER_NOT_APPLIED` | `NOT_APPLIED` | `false` | `false` | Definitive non-effect. |
| Kernel `REJECTED` or permit denial | `DENIED` | `false` | `false` | No provider effect. |
| Kernel `FAILED`, provider `PROVIDER_EFFECT_UNKNOWN` | `UNKNOWN` | `null` | `false` | Quarantined. Inspect the issue and journal. |
| Any non-200 response after POST other than `3xx`/`5xx`/`429`, including proxy/Access `401`, `403`, `404`, `409`, `413` or `422` | `UNKNOWN` | `null` | `false` | Not a verified kernel receipt; `kernel_reached:null`. Do not retry. |
| Kernel `5xx` or `429` | `UNKNOWN` | `null` | `false` | Do not retry. |
| Redirect `3xx` | `UNKNOWN` | `null` | `false` | Not followed. |
| Network error or timeout | `UNKNOWN` | `null` | `false` | Do not retry. |
| Oversized, non-JSON or malformed receipt | `UNKNOWN` | `null` | `false` | Do not retry. |
| `200` receipt missing or mismatching the submitted `request_id` | `UNKNOWN` | `null` | `false` | `KERNEL_RECEIPT_CORRELATION_MISMATCH`; do not retry. |
| `200` `ACCEPTED`/`ALLOW` receipt whose `result.issue_number` or `result.label` does not match the request, or whose `result`/`provider_ref`/`already_present` is malformed | `UNKNOWN` | `null` | `false` | `KERNEL_RECEIPT_BINDING_MISMATCH`; never success; do not retry. |
| `200` receipt whose `status`/`decision`/`result`/`error` envelope is contradictory or incomplete | `UNKNOWN` | `null` | `false` | Envelope-coherence gate; `KERNEL_EFFECT_UNKNOWN`; never `DENIED`/`NOT_APPLIED`; do not retry. |
| Pre-forward audit insert unavailable | `UNAVAILABLE` | `null` | `false` | `EDGE_AUDIT_UNAVAILABLE`; no forward. |
| Outcome audit insert unavailable after forwarding | `UNKNOWN` | `null` | `false` | `EDGE_AUDIT_UNAVAILABLE`; never success, no retry. |

Only a `200` response carrying a valid kernel receipt with the exact submitted
`request_id` can produce `DENIED`/`applied:false` or `NOT_APPLIED`. A non-200
status, including a Cloudflare Access/proxy `403` or `404` returned after the
POST, is never treated as proof that no label was added.

### Receipt validation gates

The Edge accepts a `200` body only after four ordered gates, all of which must
pass before it can report `SUCCEEDED`, `DENIED` or `NOT_APPLIED`:

1. **Parse and shape.** `JSON.parse` must yield a non-null, non-array object;
   otherwise `KERNEL_RESPONSE_INVALID` → `UNKNOWN`.
2. **Correlation.** `receipt.request_id` must be a string equal to the
   submitted `request_id`; otherwise `KERNEL_RECEIPT_CORRELATION_MISMATCH` →
   `UNKNOWN`.
3. **Envelope coherence.** `status` must be one of `ACCEPTED`/`QUEUED`/
   `REJECTED`/`FAILED` and `decision` one of `ALLOW`/`DENY`/`HALT`. Only these
   combinations are honoured:
   - `ACCEPTED` + `ALLOW` + an object `result` whose `state` is `SUCCEEDED`,
     `NOT_APPLIED` or `UNKNOWN`, with no provider error marker;
   - `REJECTED` + `DENY` + `result: null` and no provider error marker →
     `DENIED`;
   - `FAILED` + `DENY` + `result: null` → `NOT_APPLIED` only when `error`
     contains `PROVIDER_NOT_APPLIED`; otherwise `UNKNOWN`.

   Provider error markers are never read from an `ACCEPTED`, `REJECTED` or
   `QUEUED` receipt, and a `FAILED` receipt that carries a tool `result` is
   contradictory. Any other status/decision/result/error combination →
   `UNKNOWN` (`KERNEL_EFFECT_UNKNOWN`), never `DENIED` or `NOT_APPLIED`.
4. **Success binding.** For an `ACCEPTED`/`ALLOW` receipt that would report
   `SUCCEEDED` or `NOT_APPLIED`, `result` must bind to the request:
   `result.issue_number` must equal the submitted integer, `result.label` must
   equal the submitted label, `already_present` (when present) must be boolean,
   and `provider_ref` (when present) must be a bounded, non-empty,
   control-free string. A mismatch or malformed payload →
   `UNKNOWN` (`KERNEL_RECEIPT_BINDING_MISMATCH`), `applied: null`, no retry.
   This matches the kernel provider `result` shape
   `{state, issue_number, label, already_present, provider_ref, detail, ...}`.

Scope/budget denials happen before `kernelIssueLabel` when the bridge
configuration is valid and enabled, and return the existing generic
`AUTH_REQUIRED` / quota text, not the structured bridge result. They still
write one `kernel.issue_label.denied` audit row (`SCOPE_DENIED` or
`BUDGET_DENIED`). If that audit insert fails, the response is
`UNAVAILABLE: EDGE_AUDIT_UNAVAILABLE`, with no dispatch and no automatic retry.
When the bridge is disabled or invalid, an unscoped caller receives the generic
`AUTH_REQUIRED` text and a scoped caller receives `BRIDGE_DISABLED` /
`BRIDGE_NOT_CONFIGURED`, before any of those writes. Anonymous/invalid-token
requests write no audit row.

Every result includes the client `request_id`, safe kernel status/decision
values, a kernel evidence hash when present, and a stable reason code. A `200`
receipt must echo the exact submitted `request_id`; a missing or different id is
`UNKNOWN`, never success. A non-200 response, including a proxy/Access `403` or
`404`, is `UNKNOWN` with `kernel_reached:null`; it never asserts that no label
was added. The result never includes the kernel bearer, gateway token, Access
secret, actor map, private origin or raw kernel error. A `UNKNOWN` result is not
success and must be reconciled by a human against GitHub and the kernel provider
journal. The same permit is denied as a replay if it is reused; a new action
needs a new signed permit and a new request id.

## Deployment gates

Keep the production bridge disabled until every gate below is satisfied.

1. **Kernel source and artifact are pinned.** Kernel #162 is merged and the
   operator reports the merge SHA on the Oracle pilot. Verify the provenance
   of the running artifact against that SHA during release sign-off.
2. **Private ingress exists.** The kernel binds `127.0.0.1:8765` only. A private
   Cloudflare Tunnel must expose exactly that loopback listener under an
   Access-protected hostname. The origin must not be reachable from the public
   internet; firewall it. The tunnel or reverse proxy must strip client-supplied
   `X-Shards-Gateway-Identity`, `X-Shards-Gateway-Token` and caller-identity
   headers and inject the operator-configured gateway identity/token. The Edge
   uses a Cloudflare Access service token as the outer authentication and fails
   closed when the token, origin or gateway secret is missing.
3. **No unauthenticated fallback.** There is no anonymous, public or
   Access-human path to the tool. Only a verified `smcp_` agent with the
   `kernel:github_label` scope can call it, and only when the exact mapping
   exists.
4. **Pilot cap.** At most two exact actor mappings. No wildcard, prefix match,
   tenant-wide mapping or self-service enrolment. Agents without a mapping are
   denied even if they hold the scope.
5. **Release gate update.** When the bridge is enabled, `/api/status` exposes
   10 protected tools instead of 9. The manual production release gate now takes
   `bridge_mode`: `disabled` (default) expects exactly 9 and rejects the bridge;
   `enabled` expects exactly 10 including `shards_kernel_issue_label`. Both modes
   always require exactly 7 public tools and no protected tool in anonymous
   discovery. Select `enabled` only in the approved enablement rollout; leaving
   the bridge disabled keeps the current 9-tool live gate valid.
6. **No paid resources.** This change provisions no Cloudflare, Oracle, GitHub
   or paid resource. The operator uses existing infrastructure under separate
   approval.
7. **The deployed MCP Worker passes bridge acceptance.** In a separately
   approved pilot, exercise the protected MCP tool from the identified
   Worker version through Access to the configured Kernel origin. Verify a
   correlated Kernel denial and the Edge attempt and outcome audit records.
   A permit-denial check at this boundary requires a request that passes the
   Worker's structural permit checks. Provider-effect acceptance requires
   separate authorization and GitHub read-back.

## Verification

### Operator-reported terminal acceptance

The operator reports Shards Kernel v0.1.4 on Oracle ARM64 at source revision
`61cc6e82ee25aefa0a9c95ae75aedda42a7090ae`, with an active signed v3 operator
policy and a dedicated Cloudflare Tunnel protected by Access Service Auth.

| Acceptance layer | Terminal result |
| --- | --- |
| Kernel operational acceptance | 7/7 PASS |
| HAProxy acceptance | 7/7 PASS |
| External HTTPS acceptance through the protected pilot hostname | 7/7 PASS |

In the controlled terminal A/B test, the default Python HTTP client received
HTTP 403 with Cloudflare error 1010. With the explicit
`User-Agent: Shards-Kernel-Pilot/0.1.4`, it received HTTP 200 with a valid
Kernel `MISSING_PERMIT` denial receipt. This shows that the identified
terminal client reached Kernel policy evaluation over the protected route.
The operator reports that the exercise left the pilot issue unmodified.
[Pilot issue and `documentation` label target](https://github.com/Shards-foundation/shards-agent-core/issues/3)

### Worker acceptance

A local workerd loopback probe observed no User-Agent on a fresh subrequest
with the header omitted. It received `Shards-MCP-Kernel-Bridge` when the
subrequest set it explicitly, even with a different inbound client value.
The bridge regression asserts that same fixed value on the actual outbound
request options. In hosted PR CI, the Edge workflow probes the currently
deployed MCP baseline with the bridge disabled.

The deployed Worker-to-Kernel path with the new service User-Agent still
requires acceptance through the pilot's Access policy. The terminal
`MISSING_PERMIT` receipt came from a direct request to the pilot origin.
The Worker requires a structurally valid permit to dispatch an MCP request.

### Local regression tests

Run these commands from the repository root. The bridge regression suite
uses an injected transport stub and synthetic credentials.

```sh
node --check deployment/cloudflare/worker.js
node --test deployment/cloudflare/worker.test.mjs
node --test deployment/cloudflare/kernel_bridge.test.mjs
python3 -m unittest tests.test_kernel_bridge_provision -v
python3 -m unittest discover -s tests -v
python3 scripts/docs_check.py
python3 -m compileall -q src tests scripts
```

The bridge tests prove:

- the tool is hidden and denied while disabled;
- only a verified `smcp_` actor with the new scope discovers it;
- anonymous, invalid, revoked, disabled, expired and wrong-tenant tokens never
  dispatch;
- missing scope, mapping, secret, origin, label list or issue bound fails
  closed;
- wildcard, extra-pilot, prefix-mismatched, duplicate and credential-reuse
  mappings are rejected;
- client-supplied actor, URL, destination, header or credential fields are
  rejected;
- malformed, stale-shaped, over-broad and oversized permits are rejected;
- a valid request dispatches exactly once with the fixed service User-Agent,
  the mapped kernel actor, the gateway headers, the Access service token and
  the exact permit, even when the inbound MCP User-Agent differs;
- kernel denials, provider `NOT_APPLIED`, provider `UNKNOWN`, authentication
  failures, redirects, 5xx, 429, network errors, aborts, oversized responses
  and non-JSON responses are reported truthfully;
- a `200` receipt with a missing or wrong `request_id` is `UNKNOWN` and is not
  retried; the exact matching id is required for success;
- every authenticated bridge call writes a sanitized audit row: scope/budget
  denials write one `kernel.issue_label.denied` row, and calls reaching
  `kernelIssueLabel` write an `attempt` row before forwarding plus an outcome
  row;
- an authenticated scope/budget denial audit failure returns `UNAVAILABLE`
  with zero dispatch; pre-auth/invalid-token calls write no D1 audit rows;
- a pre-forward audit failure returns `UNAVAILABLE` with zero dispatch, and a
  post-forward audit failure returns `UNKNOWN`, never success and no retry;
- audit rows contain only tenant, agent, action, request id, status and
  timestamp, with no permit, bearer, Access secret or private origin;
- no bridge credential or private origin appears in a result or text;
- existing public and protected tools are unchanged;
- a verified Cloudflare Access human identity cannot call the tool.

The provisioning tests prove atomic replacement, atomic create-if-absent (a
concurrent file is never clobbered), byte-identical preservation of the reviewed
file on injected write/fsync/replace failures, rotation, rejection of symlink
and dangling-symlink targets, rejection of control-character output paths, no
temporary secret leaks, and shell-safe verifier rendering.

The denial-audit tests simulate D1 failures. Live D1 audit evidence and any
GitHub write and read-back through the deployed bridge require the separate
Worker acceptance gate above.
Pre-auth/invalid-token attempts are outside the agent ledger by design and
should be handled by Cloudflare WAF/rate limiting.

## Rollback

1. Set `KERNEL_BRIDGE_ENABLED` to `0` and deploy the prior reviewed Worker
   version. The tool disappears from discovery and calls fail closed.
2. Revoke the two pilot D1 agent tokens. Remove or replace their kernel actor
   entries in a newly signed kernel policy. Rotate the gateway and Access
   secrets.
3. Kernel: stop the service, restore `audit.sqlite3`,
   `provider-journal.sqlite3` and the signed policy from the same snapshot, or
   issue a new higher-revision signed policy. Do not lower only the JSON
   revision.
4. If the provider journal is lost, treat every possibly dispatched operation
   as `UNKNOWN` and reconcile the issue manually. Do not assume no effect.

## Residual risks and blockers

- **Kernel artifact provenance.** Use the reported source SHA for the pilot
  artifact check. The public version tag identifies a different revision.
- **Shared-secret gateway auth.** The kernel trusts the proxy and compares a
  shared gateway token. A compromised proxy can impersonate the gateway. The
  Access service token, exact origin and private tunnel reduce exposure but do
  not replace mTLS.
- **No exactly-once effect.** An `UNKNOWN` may have applied the label. The Edge
  never retries. A human must inspect GitHub and the kernel journal.
- **Single-host journal.** The kernel's SQLite audit and provider journal have
  no HA or distributed locking. Safety is preferred over availability.
- **Manual GitHub token rotation.** The kernel uses a fine-grained GitHub token,
  not a GitHub App installation token.
- **Offline issuer compromise.** If the permit issuer private key is
  compromised, every permit signed by that key is compromised. Revoke the
  `issuer_keys` entry, rotate the key and re-sign the policy.
- **Live MCP bridge acceptance pending.** The deployed Worker must exercise
  the protected origin with its service User-Agent, and its audit records and
  receipt must be verified. A GitHub write and read-back through the Worker
  remain outside the terminal acceptance.

## Kernel #162 safety assessment

The kernel contract merged in #162 provides the required gateway
identity/token validation, per-agent actor-labelled bearer verification, signed
v2 permit verification with audience/subject/action/params/max-executions/nonce
binding, replay protection, a durable provider journal, authoritative GitHub
read-back and fail-closed `UNKNOWN` semantics. No code-level change to kernel
#162 is required to make this Edge bridge safe to review.

The supported deployment requires the private Tunnel, Access Service Auth
and the gateway credential together. Live MCP bridge acceptance and
independent review remain release gates.
