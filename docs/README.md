# Shards-MCP Documentation Centre

**Document set:** 2026-11-07 | **Product:** Shards-MCP 0.1.x | **Evidence rule:** implementation != certification.

Shards-MCP is a self-hosted, single-organisation gateway. The Python package, optional Next.js private-preview console and remote deployment have **different** assurance boundaries. No public hosted service, contractual SLA or certification is represented by these pages.

## Start here

| Audience | First document | Follow-on |
| --- | --- | --- |
| Developer | [Quick start](getting-started.md) | [Cookbook](cookbook.md), [spec](specification.md) |
| AI/IDE agent | [AGENTS.md](../AGENTS.md) | [Get started skill](../skills/get-started/SKILL.md), [skills map](../skills/MAP.md) |
| Operator | [Rulebook](rulebook.md) | [Operations](operations.md), [security](../SECURITY.md), [release gates](releasing.md) |
| Reviewer | [Acceptance evidence](acceptance-evidence.md) | [Compliance mapping](compliance/controls.md), [threat model](threat-model.md) |
| Business/legal | [Terms draft](legal/terms.md) | [Privacy draft](legal/privacy.md), [DPA outline](legal/dpa.md), [licensing](../LICENSING.md) |
| Contributor | [CONTRIBUTING.md](../CONTRIBUTING.md) | [Code of Conduct](../CODE_OF_CONDUCT.md), [support](../SUPPORT.md) |

- [Portable skill installation](skills-distribution.md) — supported clients, explicit dry run, file integrity and safe recovery

## Reference library

- [Architecture](architecture.md), [protocol support](interoperability.md), [API specification](specification.md), [A2A diagnostics](a2a-doctor.md)
- [FAQ](faq.md), [use cases](use-cases.md), [reference demonstrations](demo.md)
- [Privacy](legal/privacy.md), [terms](legal/terms.md), [cookies](legal/cookies.md), [data processing agreement outline](legal/dpa.md)
- [Control matrix](compliance/controls.md), [data inventory](compliance/data-inventory.md), [publication sign-off](compliance/publication-gates.md)
- [Contribution rules](../CONTRIBUTING.md), [governance](../GOVERNANCE.md), [license](../LICENSE), [third-party licensing](../LICENSING.md)
- [Deployment runbook](../deploy/README.md), [Web console setup](../web/README.md), [release automation](releasing.md), [roadmap](roadmap.md)

## Documentation authority and release status

1. Source code and executable tests define current behaviour; a documentation claim that conflicts with them is a defect.
2. `LICENSE` is the actual MIT copyright grant. A drafted commercial Terms document does not revoke or supersede it.
3. `docs/legal/*` are **operator-review drafts**, not evidence that any entity operates a public service. Do not publish as live legal notices until ownership, contact, jurisdiction, vendors, data flows and counsel review are complete.
4. `docs/compliance/controls.md` is a mapping of evidence and gaps, **not** ISO 27001, SOC 2 or GDPR certification.
5. Unsupported A2A/MCP optional capabilities, multi-tenancy, hosted OAuth sign-in and external-effect recovery must not appear as supported features.

When documentation changes, use [the documentation review procedure](../GOVERNANCE.md). Links and examples are checked by `python scripts/docs_check.py` in CI.


## Authority v2 design (not deployed)

The v2 schema acceptance gate now includes the separate [operator cluster-role bootstrap](../infra/postgres/bootstrap_roles.sql) and [cross-session row-lock race test](../tests/sql/race_contract.py). **Neither procedure is safe against an existing customer database without operator-reviewed migration and rollback evidence.**

- [ADR-0002 — Python as sole authority](adr/0002-python-authoritative-tenancy.md): separation of Cloudflare ingress and authoritative Python state, OAuth, origin trust, replay and verification boundaries.
- [Tenancy migration and cutover plan](tenancy-migration-plan.md): preserving legacy SQLite/D1 integrity while migrating to a separately verified v2 datastore.
- [New PostgreSQL schema contract](../migrations/postgres/0001_tenancy.sql): tenant-bound keys and forced RLS; follow with [audit/outbox migration](../migrations/postgres/0002_effects_audit.sql). These files are not safe to run against an existing live database.
