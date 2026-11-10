# ADR-0002: Python is the sole authority; Cloudflare is an ingress edge

**Status:** PROPOSED — requires architecture/security owner sign-off; not a deployed change.  
**Date:** 2026-11-10  
**Supersedes:** none. Extends ADR-0001 for a *future hosted, multi-organisation v2*. ADR-0001 continues to govern the shipped single-host SQLite v0.1 package.

## Decision

The Python Shards-MCP service (backed by an authoritative database) is the **only source of truth** for organisation membership, scoped agent identity, policy decisions, task state, idempotency, external-effect intents, independent verification and the audit ledger. Neither a browser portal nor Cloudflare Worker may be a second task/tenant/audit authority.

Cloudflare acts as the public TLS/MCP edge: protocol normalisation, request limits, origin checks, coarse abuse controls and authenticated forwarding to a **private origin**. It does not own D1 messages/tasks, issue gateway principals, independently finalise work or accept customer-supplied `org_id` as authority. Edge telemetry is non-authoritative and may be emitted to an operations sink; durable transactional events and receipts are written by Python in its database.

**Not yet true:** the deployed Worker currently has D1-backed agent identities/messages/tasks and the Python gateway uses single-organisation SQLite. Neither is automatically migrated by this ADR. The current Worker remains unchanged until a phased, verified cutover.

## Invariants

1. **Tenant identity is server-derived.** An authenticated principal resolves to one explicitly selected organisation membership, and all reads/writes use that `org_id`. No `org_id` from an MCP tool argument, message, issue description, URL path or UI field is trusted without membership checks. Explicit tenant switching requires reauthorisation. Missing tenant context is DENY, never a global fallback.
2. **Every tenant-bearing row has `org_id NOT NULL`.** Primary/foreign keys and idempotency uniqueness include `org_id`. Cross-tenant object references fail even when object IDs collide or a worker knows the other ID. Organisational root rows use `org_id` as their PK; platform-wide migration metadata is not customer data.
3. **One registered authorisation server** serves the MCP protected resource and the portal. Google/GitHub/Discord/Apple are upstream IdPs, not separate MCP token issuers. Choose a proven issuer after an adapter/security comparison (e.g. managed WorkOS, Keycloak or Ory Hydra operated outside the request-routing edge); do not implement authorisation-code or refresh-token issuance ad hoc. Selection is an open ADR subdecision.
4. **OAuth:** require authorisation-code + PKCE S256; RFC 9728 protected-resource metadata and RFC 8707 resource audience binding; exact `iss`, `aud`, `exp`, `nbf`, `sub`, client and scope checks. Support compatible registered clients and/or Client ID Metadata Documents per the selected MCP version. Portal login does not itself authorise tool execution. JWT maximum accepted lifetime is 300 seconds unless active introspection yields stronger revocation guarantees. An emergency revocation path must have a measured denial latency.
5. **Origin cannot be bypassed.** The Python origin rejects any request without verified edge-to-origin mTLS or a dedicated, audience-bound short-lived edge assertion. For signed assertions, verify trusted `iss`, `aud`, `iat`, `exp`, `jti`, HTTP method/path/body digest and atomic one-use replay record. User OAuth credentials must be independently verified at the origin; the edge assertion alone is not user authorisation. Private network/firewall isolation is additional defence.
6. **No confused deputy.** Client MCP access tokens terminate at Shards-MCP; connector/provider actions use separately provisioned per-organisation delegated credentials, minimal granted scopes, explicit target and short lifetime. Never relay the MCP bearer token to GitHub, another MCP server or an arbitrary URL.
7. **Prompt injection is untrusted data.** Issue text, repository files, MCP results and PR bodies cannot grant scopes or change deployment policy. Execution workers have branch-only write access, no main-branch/secret/elevated deployment permissions. Verifiers use different credentials and read-only access to immutable CI artifacts, the diff and provider evidence. Creator, worker and verifier are distinct identities **and** segregated credentials.
8. **Side effects have an origin-owned outbox.** In one database transaction, store the task transition, scoped effect intent, idempotency key, audit entry and outbox record. Dispatch uses the outbox; ambiguous external effects enter `needs_reconciliation` and cannot be automatically replayed. Reconciliation records independent provider evidence before any new intent. Never assert exactly-once effects merely from a database uniqueness constraint.
9. **Audit is append-only, tenant-bound and DB-validated.** A tenant's `org_id` participates in the canonical record hash. A PostgreSQL BEFORE INSERT trigger takes a tenant-head row lock, reconstructs canonical JSONB bytes and validates sequence, previous SHA-256 and entry SHA-256 before advancing that head in the same transaction. The runtime DB role is denied direct UPDATE on heads. Heads must still be independently anchored outside database-owner control. A database owner can still tamper with local data; hash chaining alone is not third-party immutability.
10. **No credentials or request payloads at the edge.** Edge ingress may emit redacted telemetry but persists no tenant/task authoritative state. Coarse per-IP rate limiting and passive DNS validation remain in the edge; origin enforces per-tenant/principal quotas. DNS calls are not arbitrary HTTP fetches and must have abuse tests.


## Org identity bootstrap: one issuer, organisation-bound resource audience

**Chosen design for v2:** **no global cross-tenant subject lookup**. The authorisation server issues an organisation-scoped access token whose *audience* is the exact canonical per-org MCP resource, proposed as \`https://mcp.shardsinc.co.uk/orgs/{org_id}/mcp\`. This path is **not yet routed or deployed**. The one issuer can authenticate multiple social IdPs, but it must explicitly bind organisation membership before issuing an org-scoped resource token. The host's existing public \`/mcp\` remains a separately tested compatibility endpoint during transition and must never imply tenant rights.

On each request the origin must (1) verify issuer and token cryptography, (2) require the HTTP resource path to equal the signed \`aud\` and securely extract its tenant UUID **from the verified audience**, (3) check principal issuer+subject against \`principals\` and a non-revoked \`memberships\` record for that org and active lifecycle, (4) intersect granted scopes with the enrolled principal's scopes and exact \`agent_grants\`, and (5) **only then** begin the DB transaction and \`SET LOCAL shards.org_id\` through trusted runtime code. No MCP tool input or unsigned path selector can choose an org.

A verified subject may legitimately have memberships in multiple organisations; every session selects exactly one via an issuer-approved token audience. If a target MCP client cannot request the per-org resource audience, **block that client until compatibility is designed and tested**. Never fall back to global \`sub\` lookup or an unverified \`org_id\` claim.

The runtime DB role is NOLOGIN, non-owner and NOBYPASSRLS, with explicit table grants. It cannot enroll controllers/principals, mint grants or update audit heads. The enrolment/issuer service needs a **separate, reviewed role and implementation** before production. \`controller_id\` is trusted only after issuer-backed ownership mapping; a different string alone is not proof of independent control.

## Database acceptance is not identity authentication

The schema now enforces allowed task transitions, rejects \`reported → succeeded\` without approved evidence, and disallows approval by a reviewer whose controller matches the creator or worker. \`self_attested\` evidence may be stored but can **never** authorise success. These are schema safeguards; role-bound verification, CI artifact provenance, cryptographic receipt signatures and external effect truth still require tested services.

Idempotency is based on a canonical \`idempotency_requests\` ledger (org, actor, operation, key, payload SHA-256). The per-table unique keys and payload digests are additional database safeguards, not independent token or policy authorities. Policy grants have exact (org, principal, connector, resource, action) coordinates but their runtime matching and approval workflow remain unimplemented.

Connection pooling requires \`set_config('shards.org_id', verified_org, true)\` **inside a single transaction**, with no session-scoped tenancy GUC. The PostgreSQL contract tests assert that context vanishes after COMMIT **on the same connection**. Privileged maintenance must separately expire edge nonces and revoked-token markers after their validity and skew windows, with audit evidence; that expiry job is not yet operational.

## Dependency chain and engineering gates

| Gate | Artifact | Acceptance |
| --- | --- | --- |
| D0 | This ADR and target tenancy schema | Explicit decision; no D1/Python authority split concealed |
| D1 | `org_id` on the *target* data model; composite FK, denial tests; verified migration/backfill plan | Missing tenant context and cross-tenant references denied; legacy audit unaffected |
| D2 | Selected single OAuth issuer and portal/MCP clients | PKCE, discovery, resource audience, subject binding and expiry/revocation tested with real issuer |
| D3 | Private origin and edge assertion/mTLS | Direct origin bypass, mismatched body, expired/replayed assertion denied |
| D4 | One governed vertical slice with origin outbox | Two agents; one task; independent evidence; crash/retry leaves no blind replay |
| D5 | Real-client E2E and operated beta | Live deployed SHA, backups/restore, security review, tenant isolation, incident drills |

Cheap parallel changes (not substitutes for D0–D5): pin deployed Worker versions; triage issue #28 dependency vulnerabilities; configure Vercel environment variables using approved secret management.

## Alternatives and tradeoffs

- **Keep Cloudflare D1 as agent/task authority** — rejected for the hosted v2: two independent policy/audit and idempotency domains cannot support one truthful governance receipt.
- **Make Cloudflare the sole authoritative implementation** — deferred: requires porting and retesting Python lease/reconciliation/verification semantics and removes existing advantage.
- **Edge-hosted OAuth state** — rejected for the ingress Worker. A dedicated, independently operated issuer is an upstream authentication authority, not a second task/policy/audit authority. Any issuer implementation storing grants or revocation state on the public routing edge breaches this ADR.
- **Customer social login as MCP OAuth** — rejected: upstream IdP login is not a properly audience-bound MCP resource token.
- **Hand-roll issuer** — rejected: protocol and security lifetime is high-risk; integrate a maintained solution.
- **PostgreSQL v2 vs SQLite v1** — choose PostgreSQL for the new multi-organisation shared authority, while retaining the single-organisation SQLite package. This is *not* a silent in-place migration.
- **Row-level security** — use PostgreSQL RLS plus composite tenant FKs as defence-in-depth, not as a substitute for validated principal binding. Custom transaction settings such as `shards.org_id` can be set by a raw SQL client, so unrestricted SQL/query tool access to the runtime database is forbidden.

## Consequences and non-goals

- Implement new code paths behind explicit release gates; never point production traffic at an incomplete v2 schema.
- A legacy SQLite audit chain is **not rewritten** to insert historical `org_id`. Preserve its old digest algorithm, seal its final head externally, and start a new versioned tenant-bound chain with an audited bridge entry.
- Existing `blocked` tasks cannot be silently relabelled or requeued; map to explicit `needs_reconciliation` only after an operator-approved effect review.
- This ADR does not implement an issuer, cross-tenant runtime, edge assertion, production PostgreSQL migration or customer billing. It defines the reviewable prerequisites.

## Rejection/rollback criteria

NO-GO if any tenant row can be selected without verified membership, a cross-organisation FK succeeds, an origin endpoint is directly usable without edge attestation, a provider receives the user MCP bearer, audit backfill invalidates an existing chain or an ambiguous external effect is automatically replayed.

**References:** [ADR-0001](0001-single-host-first.md), [tenancy migration plan](../tenancy-migration-plan.md), [RFC 9728](https://www.rfc-editor.org/rfc/rfc9728), [RFC 8707](https://www.rfc-editor.org/rfc/rfc8707), [MCP authorisation](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
