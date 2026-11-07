# Publication and Enterprise Assurance Sign-off

**Two separate decisions**: (A) publish an MIT-licensed source/PyPI package, and (B) operate a public hosted gateway/console. A passes without claiming B.

## A — Source/package (public release)

- [ ] Owner verifies copyright/licensing notices, third-party licences and SBOM/dependencies.
- [ ] Secret scan includes history, fixtures, logs and release artifacts; confirmed leakage causes NO-GO.
- [ ] CI Python 3.11–3.15, official SDK tests, package build/wheel install and Docker config all pass for one commit.
- [ ] PR security review resolved, version/tag/contents match, provenance and digest recorded.
- [ ] PyPI trusted publisher, protected release environment, appropriate GitHub tags and reviewer signoff configured.
- [ ] README, supported feature table, examples, vulnerability disclosure and licence are accurate.
- [ ] Published package URL and release artifacts independently verified; do not claim completion beforehand.

## B — Public hosted service (additional mandatory controls)

- [ ] Operator legal name, registration/contact address, governing law and security/privacy contact are confirmed.
- [ ] Human-approved [terms](../legal/terms.md), [privacy notice](../legal/privacy.md), cookie inventory, DPA and subprocessors/transfer register are live and reviewed.
- [ ] Controller/processor data map, Article 6 bases, privacy request workflow and retention/deletion jobs validated.
- [ ] OAuth code/PKCE from a real external issuer, audience/expiry/subject/scope tests and safe account recovery demonstrated.
- [ ] Production tenancy and RBAC boundaries proven if accepting multiple organisations; preview allowlist is not tenancy.
- [ ] TLS, rate limiting, secret rotation, monitoring, paging and tested incident escalation are operational.
- [ ] Encrypted off-host backup, restore drill, RTO/RPO, recovery roles and disaster-recovery evidence recorded.
- [ ] Immutable audit anchoring and database-owner tamper-detection tested.
- [ ] Independent security assessment and live deny/allow MCP E2E across advertised client integrations documented.
- [ ] Support and service claims have operators, measurable targets and customer contracts.
- [ ] Risk register exceptions accepted by named accountable owner; critical auth/security fail => NO-GO.

## Evidence record (complete before approval)

| Field | Value |
| --- | --- |
| Artifact/deployment SHA and date | Pending |
| Accountable legal operator | Pending |
| Security and privacy approvers | Pending |
| Package release approver | Pending |
| CI/test/penetration evidence URLs | Pending |
| Open risks, mitigation and expiry | Pending |
| Decision A / Decision B | **NO-GO / NO-GO until evidenced** |

Do not interpret the existence of this checklist as implementation, legal signoff, third-party certification or an active service.
