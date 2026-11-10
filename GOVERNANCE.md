# Project Governance and Documentation Change Control

## Scope and authority

Shards-MCP is an MIT-licensed project maintained through the Shards Foundation GitHub organisation. No single document can grant an AI agent additional runtime authority; the Python gateway's authenticated policy and CI checks are authoritative for behaviour. External public commitments require explicit accountable human approval.

## Decision rights

- **Code maintainers:** review source, tests, docs, release changes and merge protected PRs.
- **Security reviewers:** verify identity, scopes, persistence and threat model changes; critical gaps block release.
- **Legal/privacy approver:** approves public-facing terms, notices, DPA, retention and controller roles; technical contributors must not invent legal facts.
- **Deployment operator:** owns DNS, OAuth issuer, secrets, monitoring, backups and incident response.
- **AI contributors:** may propose changes and run checks but cannot silently alter legal obligations, disable protections, publish secrets or approve their own high-impact actions.

## Change workflow

1. Open a scoped PR with issue/context, intended users, updated docs and tests.
2. Identify the exact code version being documented; cite the relevant source paths.
3. Run `python scripts/docs_check.py` and affected Python/console tests.
4. For protocol changes update `docs/specification.md`, `docs/interoperability.md` and relevant code examples together.
5. For security changes update `SECURITY.md` and `docs/threat-model.md`, add adversarial regression proof.
6. For data changes update privacy inventory, retention decisions and any applicable contracts; get legal approval.
7. Resolve independent reviewer threads, capture SHA/CI links, merge only on passing gates.
8. Stamp effective date and record new policy acceptance only when an actual service/policy publication system exists.

## Conflict resolution

Where claims conflict: **actual code/test evidence > source-specific spec > operations guide > README > marketing**. A restrictive safety statement prevails until a reviewer substantiates relaxing it. Historical roadmap descriptions do not override source behaviour.

## Release gates

Package publication and hosted-service readiness are distinct [sign-off decisions](docs/compliance/publication-gates.md). Lack of observed defects is not proof of multi-tenant, financial or platform compliance.
