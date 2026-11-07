# Interoperability acceptance evidence (operator worksheet)

This worksheet separates local protocol behaviour from live platform compatibility. It does **not** certify the gateway or authorize deployment.

## Reproducible baseline

Record the exact commit SHA, interpreter, operating system, installed wheel hash, MCP SDK version and test command for each run. A passing badge without a corresponding commit and run URL is not sufficient evidence.

| Gate | Command / observation | Acceptance |
| --- | --- | --- |
| Unit and HTTP | `python -m unittest discover -s tests -v` | All tests pass; no skipped security tests without an explicit justification. |
| Cross-runtime | `python -m unittest discover -s tests -p 'test_gateway_e2e.py' -v` | MCP, stdio, independent worker/reviewer, revocation and restart assertions pass. |
| Official MCP SDK client compatibility | CI runs the `test_official_sdk.py` integration against `mcp==2.0.0` and isolated `mcp==2.3.0` environments on Python 3.11–3.15. | Each SDK must negotiate with Shards-MCP, discover tools, and execute the read-only system-status tool over HTTP. This verifies backward-compatible clients on the established 2025-11-25 wire path; modern 2026-07-28 tool-only support is tested separately, not a full-conformance claim. |
| Dual-era MCP 2026 stateless tool client | Official Python SDK `Client(..., mode="auto")` must negotiate `2026-07-28` for both operator and restricted enrolled agent credentials, discover the gateway identity, invoke `agent_identity`, and confirm administrator tools stay hidden and denied to the restricted agent. The dedicated HTTP suite also verifies `server/discover`, `_meta`, routing headers and legacy fallback. | All five interpreters and both pinned official SDKs pass, without weakening 2025 legacy paths. This verifies the **tool-only subset**, not extensions, SSE subscriptions or an unrestricted 2026 implementation. |
| Read-only dual-wire connection diagnostic | `shards-mcp-doctor --protocol both --json` (or `--protocol modern`) on a separately enrolled scoped credential | Both wire contracts must independently discover the same principal, effective scopes and tools, without writing audit/task state or exposing credentials. A failed modern result MUST NOT silently fall back to legacy. The CLI's private-credential and transport restrictions remain enforced. |
| OAuth-authenticated SDK client | `python -m unittest discover -s tests -p 'test_official_sdk.py' -v` in the CI OAuth+SDK environments | With a generated RSA key and test-only OAuth JWT, a real SDK client must negotiate MCP, see only the scopes granted by enrolment, call `agent_identity` and be denied the operator-only `system_status` tool. Does **not** exercise a real OAuth login/consent/PKCE provider. |
| Compilation | `python -m compileall -q src tests` | Exit status zero. |
| Package | `python -m build && python -m twine check dist/*` | Wheel and sdist are valid; isolated wheel installation and CLI smoke tests pass. |
| Container | `docker build --pull -t shards-mcp:acceptance .` | Image builds and non-loopback binding without explicit opt-in fails closed. |
| Deployment config | `docker compose -f deploy/compose.yaml config --quiet` | Configuration parses with **test-only** secrets and example hostnames. |

For the Compose syntax gate in a fresh checkout, run the following **locally only** from the repository root. The values are deliberately non-routable examples; this checks configuration parsing, not OAuth, TLS, container startup or deployment. Do not run `docker compose up` with these values. The temporary secret file is removed on exit, and an existing secret is never overwritten.

```sh
set -eu
if [ -e secrets/admin_token ]; then
  echo "Refusing to overwrite existing secrets/admin_token" >&2
  exit 1
fi
mkdir -p secrets
umask 077
printf '%s\n' 'compose-config-validation-only-not-a-real-secret' > secrets/admin_token
trap 'rm -f secrets/admin_token' EXIT HUP INT TERM
SHARDS_GATEWAY_DOMAIN=gateway.example.invalid \
SHARDS_OAUTH_ISSUER=https://issuer.example.invalid \
SHARDS_OAUTH_JWKS_URI=https://issuer.example.invalid/jwks.json \
  docker compose -f deploy/compose.yaml config --quiet
```

Use the CI workflow for the full Python 3.11–3.15 matrix. A single workstation run does not establish multi-interpreter or multi-platform compatibility. Verify the workflow run and external checks for the *same* commit before merging.

## Remote MCP / ChatGPT acceptance (requires a separately approved test deployment)

1. Use an HTTPS endpoint with a valid certificate and an external OAuth authorization server. Never use the bootstrap operator credential as a remote MCP client token.
2. Retrieve protected-resource metadata unauthenticated and verify its advertised resource and authorization-server relationship. Exercise a missing-token request and inspect its `WWW-Authenticate` challenge.
3. Complete authorization-code + PKCE with the intended client. Confirm issued access-token audience, issuer, expiry, subject and scope are enforced by the gateway. Verify a token for a different audience is denied.
4. Initialize with a supported MCP protocol version, list tools with least-privilege scopes, invoke a harmless read-only tool, and verify an unscoped tool is neither discoverable nor callable.
5. Test revocation, expired credentials, malformed JSON-RPC, oversized/deep payloads, invalid origin and unsupported protocol versions. Confirm fail-closed responses without credential leakage.
6. Disconnect and reconnect a client. Confirm no reliance on process-local sessions for durable task/message state. Exercise restart and observe cursor continuity and audit verification.
7. Record the actual client product/version, authorization-server implementation, timestamp, request IDs, redacted HTTP status/headers and corresponding gateway audit evidence. Do not claim ChatGPT App Directory compatibility solely from MCP SDK tests.

## A2A acceptance boundary

The A2A adapter is a deliberately constrained v1.0 subset. Verify authenticated Agent Card access, text-only `SendMessage`, ownership-filtered `GetTask`, and `CancelTask` for **unclaimed queued tasks only**. A claimed or running task must return a not-cancelable error: cancellation must not imply interruption or rollback of external effects. Independently verify results before reporting a task as succeeded. Streaming, multi-turn interactions and push notifications are not certified by this worksheet.

## Evidence record

| Field | Value |
| --- | --- |
| Commit SHA / PR | |
| CI run URLs and conclusion | |
| External status contexts | |
| Python/OS matrix | |
| Wheel SHA-256 and installed package version | |
| MCP SDK and A2A client versions | |
| Docker image digest | |
| OAuth issuer (non-secret) and test client | |
| Negative authorization cases and results | |
| Independent review threads resolved | |
| Remaining exceptions / release decision | |

**Release decision:** NO-GO until the intended deployment's required gates are evidenced and approved. Do not interpret a completed worksheet as permission to publish a package or deploy a public endpoint.
