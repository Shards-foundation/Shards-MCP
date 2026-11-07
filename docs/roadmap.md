# Product Roadmap and Release Boundaries

**Maintained:** 7 November 2026. This roadmap distinguishes code shipped from live external verification, security assessment and future architecture. Dates are not commitments.

| Phase | Capability | Engineering status | Acceptance gap |
| --- | --- | --- | --- |
| Foundation | Scoped MCP/REST, messages, tasks, atomic claims, audit | **Implemented** in local single-host package | Live external operator acceptance |
| Compatibility | 2025 MCP plus 2026 stateless tool subset, official SDK tests | **Implemented, subset** | Full optional features and per-vendor live tests |
| Auth | Local bearer + external signed JWT resource server / RFC 9728 | **Implemented, partial OAuth** | Live external auth code/PKCE client, token lifecycle and edge hardening |
| A2A | Authenticated cards, v1.0 text tasks, pre-claim cancel | **Implemented subset** | Streaming, push, multi-turn, files, wider conformance |
| Operations | Single scheduler, metrics, snapshot/verify, Caddy Compose | **Implemented reference** | Alerts, off-host encryption/restore, SLO, audit anchoring |
| Web | Allowlisted Google/GitHub/Discord NextAuth console + diagnostics | **Private-preview code** | Real provider deployment, persistent tenant IAM and task operations |
| Distribution | CI, release/publishing workflow and security documentation | **Workflow implemented** | Verified PyPI public artifact, protected environment approvals, operator signing |
| Enterprise | HA Postgres, fencing, RBAC, policy/audit controls, remote federation | **Not implemented** | Independent multi-host/tenant tests and security assurance |
| Marketplace | ChatGPT and other agent platform submissions | **Not published** | Hosted endpoint, real client OAuth/tool tests and platform review |

## Shippable product boundary

**v0.1.x package:** useful as a deliberately bounded self-hosted single-organisation gateway. Do not postpone the package indefinitely for enterprise features; satisfy the [package gate](compliance/publication-gates.md).

**Hosted business:** requires separate security, data protection, OAuth, operation and legal controls. A deployable Compose example is not a hosted production service.

## Next milestones (ordered by customer utility)

1. Verify actual first package release on PyPI/GitHub with hashes, provenance and reproducible install.
2. Run a closed private deployment using a real protected HTTPS endpoint and independent OAuth issuer; test two external clients.
3. Complete persistent console identity/roles, agent/task observability and a safe scoped write bridge.
4. Establish off-host encrypted backups, restore RTO, rate limits/alerts and independently anchored audit before customer-hosted production.
5. Validate connectors (Cursor, Claude Code, Codex, VS Code and ChatGPT) against installed versions, not generated templates.
6. Add Postgres HA, multi-tenant boundaries and full A2A/MCP optional features only as independently scoped, demand-backed releases.

## Evidence process

Each milestone requires owner, commit SHA, CI, live test artefacts if applicable, explicit customer value, risks, acceptance thresholds and binary GO/NO-GO. Do not describe unresolved features as production-ready.
