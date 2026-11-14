# Threat Model (STRIDE-oriented, v0.1.x)

**Assets:** operator secret, per-agent credentials, OAuth issuer configuration, SQLite tasks/messages/evidence, audit chain, snapshots, session cookies, runtime availability. **Adversaries:** compromised agent, prompt-injection author, network client, leaked-token holder, database operator, malicious dependency, compromised host.

## Trust boundaries

`LLM/IDE client -> authenticated MCP/REST HTTP -> scope/schema checks -> SQLite`. Local CLI provisioning remains outside the network tool surface. Off-host OAuth uses a separately configured signed JWT issuer; NextAuth website sign-in is **not** a gateway authorisation grant. The reference worker receives untrusted payloads; it does not execute shell strings. Caddy protects a sample reverse-proxy boundary but is not an operated service.

| Threat | Current defence | Residual risk / required control |
| --- | --- | --- |
| Spoofed principal | Local secret digest or signed JWT issuer/subject/audience validation | Stolen token, issuer compromise, token rotation and proof-of-possession absent |
| Privilege escalation | Scope-based tool discovery and per-request actor checks | Multi-tenant RBAC absent, operator/host compromise critical |
| Malicious payload/prompt injection | Bounded JSON schema; deterministic reference worker | External custom agent may obey malicious text; enforce external policy/sandbox |
| Message/task tampering | SQLite transactional mutations, idempotency, audit chain | Database owner can rewrite/re-hash; external immutable anchor required |
| Repudiation | Actor-bound audit events, operator-assigned per-task reviewer and operator-labelled control domains | Labels cannot independently prove real-world ownership, external evidence authenticity or separate people; custody of signing keys matters |
| Information disclosure | Receiver/owner filtering, redacted logs, protected token files | Plaintext task/evidence in SQLite/backups; retention and encryption gaps |
| DoS/rate abuse | Bounded parser/connection semaphore | No robust edge quotas, WAF or per-agent rate limits |
| SSRF/outbound abuse | Trusted JWKS URI pinned, worker URL HTTPS except loopback; no arbitrary HTTP execution | Future adapters need outbound allowlisting and DNS/rebinding tests |
| Replay/double effects | Idempotency keys, atomic claims, expired lease quarantine | No exactly-once external effects; reconciliation required |
| Recovery compromise | Exclusive snapshot, local verification | No off-host restore rehearsal or key escrow by default |
| Supply chain | CI and pinned Actions, web lockfile | SBOM, dependency scanning and independent audit needed |
| Console access | NextAuth provider subject allowlist; read-only health | No persistent tenancy, MFA enforcement, global session revocation or gateway RBAC |

## Mandatory adversarial tests

Unknown/malformed JWT, issuer/audience mismatch, revoked agent, denied tool, operator-assigned reviewer and same-controller denial, creator/worker/verifier separation, duplicate request keys, simultaneous claim/cancel, worker crash mid-completion, expired lease reconciliation, invalid Origin/JSON, audit edit simulation, backup restore. Evidence should be per SHA in [acceptance worksheet](acceptance-evidence.md).

## Risk acceptance

Critical auth bypass or unauthorised external effects -> **NO-GO**. A private preview can be run only in explicitly bounded environments. Hosted enterprise go-live requires independent security assessment, rate limiting/alerts, encryption and retention decisions, isolated tenancy (if offered), and immutable external audit anchoring. See [control matrix](compliance/controls.md).
