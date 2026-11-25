# Agent Hub control centre

The existing Agent Hub Worker is retained, with an additional read-only `/control` route and `/api/control` snapshot. It shares the MCP gateway's existing private service binding and verifies the original Cloudflare Access JWT on the gateway using the Hub-specific audience. The snapshot selects only agents enrolled by the signed operator and task records involving those agents, within the internal tenant. A shared task can disclose the assignee's registered name to its creator, including an assignee enrolled by another operator; unrelated agent directory entries are not returned. It returns at most 100 records of each kind, reports truncation and omits credentials, message bodies and task inputs. Recorded authentication is not proof of runtime liveness. Malformed stored scopes render as an empty list, not a grant of authority.

## Owner Lobby v0.2 (source only, not deployed)

`GET /lobby` and `GET /lobby.js` serve a small mobile-friendly owner chat page linked from `/` and `/control`. The page calls only the same-origin routes below; it never contacts the Lobby transport directly and holds no transport credential.

| Route | Behaviour |
| --- | --- |
| `POST /api/lobby/chat` | Same-origin JSON `{conversation_id, message}`; verified owner session required; forwards text only. |
| `GET /api/lobby/health` | Same-origin transport health; returns `ok`, `blocked` or `unavailable` only. |

**Authentication.** The route reuses the existing private `/session` bridge with the Hub-specific `HUB_REGISTRY_AUD` audience. That bridge performs the real Cloudflare Access JWT signature, issuer, audience, expiry and operator-account verification. The Hub reads `sub` from the **same exact assertion** only after `/session` returns authenticated; it never trusts a caller-supplied owner, an unsigned JWT or a query parameter. A missing `MCP_GATEWAY` binding, a private-bridge 5xx, or a redirect fails closed with `503`.

**Owner namespace.** The upstream conversation UUID is derived server-side as a UUIDv5-shaped value from `SHA-256("shards-lobby-owner-v1" + NUL + sub)` and the validated caller conversation UUID. The raw owner identifier is never sent upstream, and two owners using the same client UUID receive different upstream UUIDs.

**Transport.** The only target is the fixed `https://lobby-transport.shardsinc.co.uk/chat` and `/health`. The Worker sends a fresh header set: `CF-Access-Client-Id`, `CF-Access-Client-Secret`, `Authorization: Bearer <adapter secret>`, `Content-Type: application/json` and `Accept: application/json`. It does not forward cookies, the Access assertion, `Origin`, `Host`, forwarding headers or any caller header. Redirects are not followed and there is exactly one attempt. Required bindings are `LOBBY_CF_ACCESS_CLIENT_ID`, `LOBBY_CF_ACCESS_CLIENT_SECRET` and `LOBBY_ADAPTER_TOKEN`; any missing or malformed value fails closed before a transport call. These are Worker secret bindings; no value belongs in source, the browser or a prompt.

**Limits and failure handling.** The request body is capped at 16 KiB, the message at 8,000 characters and 12 KiB of UTF-8, and the transport response at 64 KiB. The transport fetch has a 45-second abort signal, longer than the adapter's 30-second upstream deadline. The page uses `textContent` only, no HTML injection, and a strict CSP (`script-src 'self'`, `connect-src 'self'`, `form-action 'none'`, `frame-ancestors 'none'`). Unknown or blocked outcomes return `outcome` and a visible instruction to reconcile the local adapter before resubmitting; there is no automatic retry and no fake reply. Health is transport reachability, not agent liveness. The route does not expose approvals, task dispatch, new agent privileges, files, streaming or an OpenClaw endpoint.

**Deployment boundary.** The proposed transport hostname is not provisioned in this change. This source does not install, tunnel, change DNS, Cloudflare Access, Oracle, credentials or the Edge service. The required secret bindings and the transport itself are separate deployment prerequisites.

## Tests

```sh
node --test deployment/cloudflare/agent-hub/control.test.mjs deployment/cloudflare/agent-hub/lobby.test.mjs
```

The control suite exercises actual Worker modules with ephemeral RSA-signed test JWTs, a mocked JWKS endpoint, a read-only database double and real in-memory SQLite using the repository schema. CI pins Node 24.22.1. Independent review at `df10ecdc37bfad7e82a17c8987d7ba871509d444` reports 10/10 control tests passing on Node 24.22.2; all three hosted workflows passed at that commit. The reviewer additionally verified same-origin Fetch Metadata without an Origin header using a separate harness. Real JWKS rotation and authenticated Cloudflare browser/D1 acceptance remain unverified.

The Lobby suite adds ten focused tests against the actual Worker route and mocked `/session` binding and transport fetch. It covers denied and structurally invalid sessions, missing transport configuration, cross-origin and Fetch Metadata denial, fixed transport routing and header hygiene, secret exclusion, stable owner-namespaced UUIDs and owner separation, strict body/UUID/text/size validation, every adapter outcome including unknown/blocked/busy, malformed/oversized/redirected/failed responses, health sanitisation, one-attempt-only behaviour, and unchanged `/control`, `/api/control`, `/`, `/api/health` and `/api/models` routes. The suite does not prove a live transport, a real Cloudflare browser session, or OpenClaw inference.

## Release boundary

No OpenClaw execution, external provider credentials, task dispatch, or coordination authority changes are included. Do not enable public previews or bypass Access to test the interface. The legacy Hub header-presence guard still covers `/`, `/api/chat`, `/api/health` and `/api/models`; the new Lobby routes add `/session` verification but do not harden those legacy routes. The transport must also satisfy the adapter's strict loopback HTTP rules (expected `Host`, `Content-Length`, no `Origin`, no content encoding); a proxy or tunnel that rewrites or chunks those headers is a separate deployment blocker.

Staged 2026-11-25 Cloudflare versions (not deployed):
- Hub candidate `c3684aad-168b-4529-ad68-803eb6e0c9b6` (v14), production baseline `91a2a23c-d22c-4e08-a688-7770cc6b7ca1` (v12).
- Edge candidate `819e4bac-ed4b-47f1-accc-8792f9258e7c` (v17), production baseline `7c2e2756-a69a-402d-91cd-170de6d6adf9` (v15).

Hub v13 and Edge v16 are superseded; do not deploy them. Both current candidate Worker sources were retrieved and compared byte-for-byte against the independently reviewed `df10ecdc37bfad7e82a17c8987d7ba871509d444` source files. Edge v17 includes the newer main Kernel receipt-validation changes, unlike v16. Existing bindings were strictly inherited. Any later release must recheck source equivalence, branch head, reviews, live deployment baselines and Access configuration before activation.

Deploy compatible Edge first, then Hub. Roll back Hub first, then Edge if needed, using verified prior versions. Confirm signed-in operator records, no-access rejection, filter/refresh behaviour, existing chat and enrolment, and no unintended writes. If a protected route or existing capability regresses, stop and roll back. Signed-in acceptance requires an actual authorised operator browser; do not label a mocked test as live acceptance. Existing unresolved message/audit discrepancy remains a separate blocker for write-enabled coordination.

Live Access configuration was checked: Hub and MCP manage allowlist the same single email; Hub also requires Cloudflare account membership. Hub JWT audience matches the gateway binding. Both public Worker subdomains and public previews remain disabled. No production changes were made during staging.
