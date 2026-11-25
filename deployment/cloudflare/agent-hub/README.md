# Agent Hub control centre

The existing Agent Hub Worker is retained, with an additional read-only `/control` route and `/api/control` snapshot. It shares the MCP gateway's existing private service binding and verifies the original Cloudflare Access JWT on the gateway using the Hub-specific audience. The snapshot selects only agents enrolled by the signed operator and task records involving those agents, within the internal tenant. A shared task can disclose the assignee's registered name to its creator, including an assignee enrolled by another operator; unrelated agent directory entries are not returned. It returns at most 100 records of each kind, reports truncation and omits credentials, message bodies and task inputs. Recorded authentication is not proof of runtime liveness. Malformed stored scopes render as an empty list, not a grant of authority.

## Tests

```sh
node --test deployment/cloudflare/agent-hub/control.test.mjs
```

The ten-test suite exercises actual Worker modules with ephemeral RSA-signed test JWTs, a mocked JWKS endpoint, a read-only database double and real in-memory SQLite using the repository schema. CI pins Node 24.22.1. Independent review at `df10ecdc37bfad7e82a17c8987d7ba871509d444` reports 10/10 tests passing on Node 24.22.2; all three hosted workflows passed at that commit. The reviewer additionally verified same-origin Fetch Metadata without an Origin header using a separate harness. Real JWKS rotation and authenticated Cloudflare browser/D1 acceptance remain unverified.

## Release boundary

No OpenClaw execution, external provider credentials, task dispatch, or coordination authority changes are included. Do not enable public previews or bypass Access to test the interface. The legacy Hub header-presence guard needs separate hardening before any expansion of exposure.

Staged 2026-11-25 Cloudflare versions (not deployed):
- Hub candidate `c3684aad-168b-4529-ad68-803eb6e0c9b6` (v14), production baseline `91a2a23c-d22c-4e08-a688-7770cc6b7ca1` (v12).
- Edge candidate `819e4bac-ed4b-47f1-accc-8792f9258e7c` (v17), production baseline `7c2e2756-a69a-402d-91cd-170de6d6adf9` (v15).

Hub v13 and Edge v16 are superseded; do not deploy them. Both current candidate Worker sources were retrieved and compared byte-for-byte against the independently reviewed `df10ecdc37bfad7e82a17c8987d7ba871509d444` source files. Edge v17 includes the newer main Kernel receipt-validation changes, unlike v16. Existing bindings were strictly inherited. Any later release must recheck source equivalence, branch head, reviews, live deployment baselines and Access configuration before activation.

Deploy compatible Edge first, then Hub. Roll back Hub first, then Edge if needed, using verified prior versions. Confirm signed-in operator records, no-access rejection, filter/refresh behaviour, existing chat and enrolment, and no unintended writes. If a protected route or existing capability regresses, stop and roll back. Signed-in acceptance requires an actual authorised operator browser; do not label a mocked test as live acceptance. Existing unresolved message/audit discrepancy remains a separate blocker for write-enabled coordination.

Live Access configuration was checked: Hub and MCP manage allowlist the same single email; Hub also requires Cloudflare account membership. Hub JWT audience matches the gateway binding. Both public Worker subdomains and public previews remain disabled. No production changes were made during staging.
