# Support and Escalation

**Current support model:** open-source, best-effort. No 24×7 coverage, commercial support contract, SLA or response-time guarantee is advertised.

## Routing

| Issue | Route | Include |
| --- | --- | --- |
| Usage/configuration | GitHub Discussion or issue, when enabled | Version, OS, installation method, redacted command/output |
| Bug/regression | GitHub Issue | Minimal reproduction, expected/actual result, exact commit, test logs |
| Feature/API proposal | GitHub Issue | Use case, risk/permission scope, protocol reference, acceptance test |
| Security issue | [Private vulnerability reporting](SECURITY.md) | Reproducer, affected SHA, impact; never include secrets publicly |
| Hosted billing/legal/privacy | **Not offered** | Future operator must publish a monitored contact before launch |

## Diagnostic information

Use `shards-mcp-doctor --protocol both --json` with a separately scoped agent credential; it is intentionally read-only. Remove bearer tokens, OAuth JWTs, private URLs, user payloads and personal information from any issue or transcript. Do not post a database snapshot unless anonymised and separately authorised.

## Incident severity

- **Critical:** confirmed authorisation bypass, leaked operator credential, external-effect escalation or ledger integrity failure. Contain, rotate/revoke, suspend affected access, preserve evidence.
- **High:** reproducible privilege isolation failure or production outage within the operator's supported envelope.
- **Normal:** non-sensitive regression, usability issue or documentation gap.

Self-hosters own their deployment-specific alerts, recovery and notifications. Consult [operations](docs/operations.md) and [threat model](docs/threat-model.md) before exposing a public endpoint.
