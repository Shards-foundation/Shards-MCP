# Terms of Use — operator review draft

**Status: DRAFT / NOT IN FORCE.** Last edited 7 November 2026. This template describes intended terms for a **future hosted Shards-MCP console/gateway**, not a currently offered service. It must not be represented as accepted, enforceable or published production terms without completion of the release checklist and legal approval.

## 1. Parties, scope and effective date

A future operator must identify its **legal trading name, registration number (if any), physical service address, legal contact, governing law, effective date, version history and dispute channel** in the published notice. Those facts are **not verified in this repository**. The open-source Python package is separately licensed under [MIT](../../LICENSE); these terms are **not** a substitute for or restriction on that licence.

These draft terms are intended for hosted accounts, website access, connectors and operation of the service. Local self-hosted deployments are operated by the deploying organisation under its own arrangements.

## 2. Eligibility and accounts

An account holder must have authority to act for their organisation. Operators should require accurate registration details, protect account credentials, maintain least-privilege access, and promptly revoke compromised identities. Console social login only proves an allowlisted identity in the current preview; it does **not** confer gateway administration or persistent organisational membership.

## 3. Acceptable use and automation

Users must not attempt unauthorised access, credential sharing, vulnerability exploitation, malicious payload distribution, excessive traffic or unlawful processing. All agents require their own scoped identity. The gateway coordinates messages/tasks but does not guarantee correctness, independent evidence authenticity, exactly-once execution or reversal of external actions. Organisations remain responsible for reviewing tool permissions, model outputs, human approvals and any third-party effects they introduce.

## 4. Customer data and responsibilities

The hosted operator's [published privacy notice](privacy.md), [data-processing agreement](dpa.md) if applicable, and documented subprocessor list must specify handling of personal information. Customers must have a valid basis for content they send, avoid unnecessary personal/special-category data, and configure retention and backups appropriately. Current self-hosted software persists task, message and verification data locally; it has no general automated retention schedule.

## 5. Availability, changes and charges

There is **no hosted commercial service, paid plan, SLA, refund policy or uptime guarantee** established by this repository. Any future fees, invoices, renewal/cancellation terms, service credits, maintenance windows and support response targets require separately published and accepted schedules **before** charging or onboarding customers.

## 6. Intellectual property and third parties

MIT-licensed source retains its own licence and copyright notices. Third-party identities, AI models, IDEs, OAuth providers and services have separate terms. Service users must have adequate rights to transmit their own content and to run their selected integrations.

## 7. Suspension, termination and data return

A future operator must specify objective suspension grounds, notice/appeal processes, account closure procedures, lawful retention and deletion/return of data, and security exceptions. These are not yet implemented as multi-tenant hosted workflows. Do not claim users can self-serve data export or erasure unless tested.

## 8. Warranties and liability

The MIT licence supplies the open-source software **as-is**. Commercial warranties, liability caps and exclusions must be drafted for the actual contracting entity, customer type and applicable law; no unreviewed limitation here displaces mandatory consumer or data-protection rights.

## 9. Legal review required before publication

Confirm the provider's identity and contract law jurisdiction; B2B vs consumer eligibility; applicable UK consumer protections; payment/refund treatment; liability and indemnity language; DPA/transfer terms; complaints and contact points; record of approval and effective date. **Do not place this draft into a live signup acceptance checkbox.**
