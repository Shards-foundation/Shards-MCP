# Agent Hub control centre

The existing Agent Hub Worker is retained, with an additional read-only `/control` route and `/api/control` snapshot. It shares the MCP gateway's existing private service binding and verifies the original Cloudflare Access JWT on the gateway using the Hub-specific audience. The snapshot selects only agents enrolled by the signed operator and task records involving those agents, within the internal tenant. It returns at most 100 records of each kind, reports truncation and omits credentials, message bodies and task inputs. Recorded authentication is not proof of runtime liveness.

## Tests

```sh
node --test deployment/cloudflare/agent-hub/control.test.mjs
```

The suite exercises actual Worker modules with ephemeral RSA-signed test JWTs, a mocked JWKS endpoint and a read-only database double. It is not a substitute for authenticated Cloudflare browser acceptance or a live SQL isolation test.

## Release boundary

No OpenClaw execution, external provider credentials, task dispatch, or coordination authority changes are included. Do not enable public previews or bypass Access to test the interface.

Staged 2026-11-25 Cloudflare versions (not deployed):
- Hub candidate `97dcdb8e-4b2d-4e64-8dc0-a7383a719b34` (v13), production baseline `91a2a23c-d22c-4e08-a688-7770cc6b7ca1` (v12).
- Edge candidate `bfc7803d-db17-4ec9-a84d-d88be29eab42` (v16), production baseline `7c2e2756-a69a-402d-91cd-170de6d6adf9` (v15).

The Hub file records the staged source. The Edge patch is ported onto the repository main baseline, which is newer than the currently deployed Edge. Do not assume the staged Edge is byte-identical to repository HEAD. After review, build and verify the exact release candidate against the approved source; preserve the production bindings and recheck both deployed versions immediately before rollout. Deploy compatible Edge first, then Hub. Roll back Hub first, then Edge if needed, using verified prior versions. Confirm signed-in operator records, no-access rejection, filter/refresh behaviour, existing chat and enrollment, and no unintended writes. If a protected route or existing capability regresses, stop and roll back. Existing unresolved message/audit discrepancy remains a separate blocker for write-enabled coordination.
