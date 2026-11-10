# Privacy Notice — scoping draft

**Status: DRAFT / NOT A LIVE PUBLIC NOTICE** | Reviewed for technical claims 7 November 2026.

This is a factual starting point for a **future Shards-MCP hosted service**. The actual controller identity, postal and privacy contact addresses, lawful bases, processors, data locations, retention schedule, rights handling and transfer safeguards have not been approved or verified. Publishing without completing them could mislead data subjects. Source reference: [ICO transparency guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/transparency-and-privacy-notices/).

## Current product boundaries

| Activity | Potential personal data | Where processing occurs |
| --- | --- | --- |
| Self-hosted gateway | Agent identifiers and names, enrolment subject, message/task payloads, checkpoints, reviewer evidence, audit events | Operator-managed SQLite and backups |
| Credentials | One-time local tokens, stored token hashes, OAuth token claims validated at request time | Gateway host; private token files held by operator |
| Preview console | Provider account identifier, optionally name/email, session information | NextAuth application and its configured session cookie; no persistent tenant database |
| HTTP access | Request ID, route class, duration/status; gateway metrics | Host/operator logs and monitoring if configured |
| Future hosted support/analytics | Unknown | **Not implemented or disclosed** |

Model prompts and task payloads may contain personal or sensitive content **if the deploying customer puts it there**. The gateway does not independently execute external AI models or send tasks to an AI provider. An OAuth identity provider and hosting platform may separately process data under their notices.

## Controller/processor allocation

For self-hosting, the deploying organisation ordinarily decides which personal data to ingest, the purposes and retention, and acts as controller/processor according to its own legal arrangements. The source-code publisher does not automatically become controller of all deployments. For a future hosted product, identify the accountable legal entity and distinguish processing for account administration from customer-directed processing, with a signed DPA where necessary.

## Purposes and lawful bases — to validate

Potential purposes include account authentication, gateway authorisation, message/task delivery, security auditing, debugging and legally required recordkeeping. **No Article 6 lawful basis is asserted here**: the future operator must determine and document the valid basis *per purpose*, legitimate-interest assessments where used and Article 9 conditions where relevant. No marketing or analytics consent collection is currently implemented.

## Retention and deletion

There is **no default end-to-end retention/deletion policy** or self-service data-subject export/erasure in v0.1.x. Audit entries are append-only to ordinary application actors and can include content references. Operators must set retention limits for database copies, logs, backups and issuer records; establish legal-hold exceptions; test deletion and subject access processes before accepting real user data.

## Recipients, transfer and security

A future hosted policy must enumerate actual hosting, OAuth, email/analytics, observability and support providers; regions; international transfer mechanisms where applicable; and a maintained subprocessor list. The local reference deployment contains Caddy and SQLite, but **no approved region, third-party data-sharing list or international-transfer arrangement is specified**. Safeguards include scoped bearer/JWT checks, credential redaction, SQLite access restrictions and audit chaining; residual risks are documented in [SECURITY.md](../../SECURITY.md).

## Rights, children and contact

The final notice must explain access, rectification, erasure, restriction, objection, portability, withdrawal of consent (where applicable), complaint to the applicable supervisory authority, automated decisions (if any), and how to exercise rights. Do not market the system to children or process children's personal data without a reviewed legal basis and safeguards. Provide an actual monitored privacy contact and company postal address **before publication**.

## Publication gate

Legal/controller identity, lawfully justified processing table, retention schedule, data transfer assessment, cookie inventory, processor contracts, rights workflow, breach response, notice version/date, and legal approval must be recorded in [publication gates](../compliance/publication-gates.md). Do not describe this draft as GDPR-compliant or certification evidence.
