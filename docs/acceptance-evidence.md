# Interoperability acceptance evidence (operator worksheet)

This worksheet separates local protocol behaviour from live platform compatibility. It does **not** certify the gateway or authorize deployment.

## Reproducible baseline

Record the exact commit SHA, interpreter, operating system, installed wheel hash, MCP SDK version and test command for each run. A passing badge without a corresponding commit and run URL is not sufficient evidence.

| Gate | Command / observation | Acceptance |
| --- | --- | --- |
| Unit and HTTP | `python -m unittest discover -s tests -v` | All tests pass; no skipped security tests without an explicit justification. |
| Cross-runtime | `python -m unittest discover -s tests -p 'test_gateway_e2e.py' -v` | MCP, stdio, independent worker/reviewer, revocation and restart assertions pass. |
| Compilation | `python -m compileall -q src tests` | Exit status zero. |
| Package | `python -m build && python -m twine check dist/*` | Wheel and sdist are valid; isolated wheel installation and CLI smoke tests pass. |
| Container | `docker build --pull -t shards-mcp:acceptance .` | Image builds and non-loopback binding without explicit opt-in fails closed. |
| Deployment config | `docker compose -f deploy/compose.yaml config --quiet` | Configuration parses with **test-only** secrets and example hostnames. |

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
