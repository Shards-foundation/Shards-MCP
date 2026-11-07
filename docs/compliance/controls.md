# Compliance Control Matrix — mapping, not certification

**Baseline:** v0.1.x source review, 7 November 2026. **Assessment:** internal evidence mapping only. No assertion of ISO 27001 certification, SOC 2 report, Cyber Essentials accreditation, UK GDPR compliance or regulatory authorisation.

| Control family | Implemented evidence | Gap / owner action | Status |
| --- | --- | --- | --- |
| Identity/least privilege | `core.py` scopes; local agent provisioning; optional OAuth verifier; deny tests | Real IdP onboarding, rotation and periodic access reviews | Partial |
| Tenant isolation | Authenticated agent and task/message ownership boundaries | No persistent organisation tenancy, RBAC or cross-tenant penetration test | **Not implemented** |
| Secure development | CI 3.11–3.15, PR review, protocol and worker regressions | SAST/SCA/SBOM baseline, independent penetration testing, patch SLA | Partial |
| Transport security | HTTPS Caddy reference; OAuth remote-mode requirement | Real cert, hostname, proxy headers, rate limits, WAF/load validation | Template only |
| Logging and audit | SQLite hash-chain, audit verify, redacted access log | Immutable off-host anchor, monitoring, tamper and retention exercises | Partial |
| Data protection | Scoped access and protected files | Data inventory, lawful basis, retention, encryption at rest and DSAR workflow | Partial |
| Availability/recovery | SQLite snapshots, restart checks, single scheduler | Encrypted off-host backup, restore RTO/RPO, incident alerting | Partial |
| Change management | GitHub PR/CI and release runbook | Release approvers, separation of duties, environment/tag protection | Partial |
| Incident response | Sensitive-error suppression, local revocation | Contact/rota, playbooks, breach notification deadlines and drills | Partial |
| Third-party risk | Dependency pins in CI/web lockfile | Supplier approvals, data-transfer and subprocessor assessment | Partial |
| AI-specific safety | No arbitrary code/tools in reference worker; independent verify | Prompt-injection red team and external-effect authorisation testing | Partial |
| Cryptographic assurance | JWT signature/audience tests; audit hashing | Threat-modelled rotation, key custody and independent audit anchoring | Partial |

## Suggested standards crosswalk (non-certifying)

- ISO/IEC 27001:2022: governance, access control, operations, supplier management, incident response, backup and cryptography.
- SOC 2 Trust Services Criteria: security, availability, confidentiality, processing integrity and privacy as applicable.
- UK GDPR: Article 5 principles, Article 6 lawful bases, Articles 13–14 notices, Article 28 contracts, Article 32 security and Articles 33–34 breach obligations as applicable.
- OWASP guidance: HTTP authentication, input validation, SSRF and secrets management.
- MCP/A2A: documented supported *subsets*, negative auth cases and honest capability negotiation.

These mappings create **work items**, not audit opinions. Map actual clause IDs, reviewers, policies, dated test evidence and exceptions in a GRC register before requesting external assurance.

## Evidence acceptance

Every claimed control needs (1) requirement owner, (2) source/config path, (3) test or operational proof, (4) dated commit/deployment SHA, (5) reviewer, (6) expiration or recertification interval, (7) exception and compensating control. A CI badge alone never establishes legal or operational compliance. See [publication gates](publication-gates.md).
