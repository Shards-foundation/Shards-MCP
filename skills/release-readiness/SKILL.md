---
name: release-readiness
description: Verify source/PyPI release or hosted-service gates with evidence and human approvals; prevent false production claims.
---
# Release Readiness

**Trigger:** version tag, publishing request, new public deployment or enterprise-ready claim.

1. **Decide envelope:** A=public package, B=public hosted service. Do not conflate them.
2. **Inputs:** exact main SHA, project version/tag, CI workflows, artefact hashes, independent reviews, operator signoffs.
3. **A package:** check `docs/compliance/publication-gates.md` A, source/licence rights, no secrets, full CI and version equality. Verify protected tag, PyPI Trusted Publisher and environment controls. Never re-tag a published version.
4. **B hosted:** additionally confirm actual TLS/DNS, external OAuth code flow with correct audience, deny tests, operational monitoring, encrypted off-host restore, audit anchoring, regulatory/contact/legal notices and tenancy controls if offered.
5. **Stop:** any P0 auth failure, uncertain origin of release artifacts, missing legal approvals or evidence of unauthorised external effects is NO-GO. Do not declare completion from a YAML file existing.
6. **Output:** dated SHA, evidence links and owner by gate, A GO/NO-GO, B GO/NO-GO, unresolved risks and explicit operator approvals. Publication requires the approved release operator action.
