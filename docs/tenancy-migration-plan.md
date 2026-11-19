# Authority v2: tenancy migration and cutover plan

**Status: DESIGN / NO-GO for production.** The SQL under `migrations/postgres/` creates an *empty, independent v2 PostgreSQL schema*. It is **not** an in-place mutation of the existing SQLite gateway or Cloudflare D1. Running DDL alone does not make the current Python runtime tenant-safe.

## Current v1 evidence (2026-11-10, `main` commit a960eebe)

The Python `Gateway` in `src/shards_mcp/core.py` uses single-host SQLite and creates tables `agents`, `messages`, `tasks`, `verifications`, `checkpoints`, `schedules`, `events` and `audit` without `org_id`. `Principal` carries agent ID and scopes, not tenant membership. Many queries use a bare task/agent ID; `agents.name`, `agents.oauth_subject`, token hashes and idempotency indexes are global. The old audit digest canonicalises `at,actor,action,subject,details`, *not* tenant ID. Its `audit` table rejects updates/deletes through SQLite triggers. The deployed Cloudflare Worker has a separate D1 identity and task store. **No federation or safe legacy automatic migration exists.**

## Migration phases, ordered

1. **Inventory and freeze.** Require owner confirmation of all SQLite/D1 deployments, per-table row counts, schema versions, audit head hashes, storage/jurisdiction and backups. Take encrypted off-host snapshots, checksum and dry-run restores. Suspend new writes during final cutover or use a proven dual-read **with a single writer**; never operate two active authorities.
2. **Provision roles and an empty v2.** Before installing schemas, the operator runs `infra/postgres/bootstrap_roles.sql` **once per PostgreSQL cluster** (or obtains equivalent managed-role provisioning from the DBA). This cluster-level bootstrap is repeatable and rejects LOGIN/BYPASSRLS/inherited/escalated role properties. Apply `0001_tenancy.sql` then `0002_effects_audit.sql` once **per empty database**. The migrations independently reject insecure roles and do not create them. CI runs both migrations in two distinct databases under one PostgreSQL 16 or 17 cluster. Use a non-owner, `NOBYPASSRLS` runtime role with explicit table privileges. Run `tests/sql/tenancy_contract.sql` and `tests/sql/race_contract.py` against disposable databases. All runtime transactions use `BEGIN` + `set_config('shards.org_id', verified_org, true)` after actual issuer/membership validation; COMMIT/ROLLBACK must clear the GUC. `schema SQL PASS` alone cannot validate that identity resolution or connection pooling is safe.
3. **Deterministic legacy mapping.** A trusted operator explicitly assigns all legacy records to one *quarantined* legacy organisation (`org_legacy_<...>` in an external mapping manifest; v2 uses UUID `org_id`). Validate every agent/message/task/checkpoint/event reference. Unknown/orphan links are **BLOCKED**, never mapped to a default public/customer org. Preserve old external opaque IDs with scoped uniqueness. Rehashing or mutating old rows to add tenancy is forbidden.
4. **Audit bridge.** Verify full legacy hash chain before export; copy the final head, record count, snapshot digest, time, migration code SHA and operator receipt in an externally controlled evidence store. Insert the first **new v2** tenant-bound audit record referencing this sealed old head, rather than changing historical hashes. New audit hashes MUST include `org_id`, version and canonical field ordering. Verify via independent replay and off-host anchor.
5. **Token/key migration.** Use one issuer with an **organisation-bound resource audience** such as `https://mcp.shardsinc.co.uk/orgs/{org_id}/mcp`. Verify signed audience against the requested resource path, then check `(org_id,issuer,subject)` against active membership before setting `shards.org_id`. Never resolve a `sub` by scanning all tenant rows or trust an unverified browser/org hint. 
    Do not silently import long-lived bootstrap/operator credentials or let the same agent token identify multiple orgs. Re-enrol external OAuth principals under a trusted issuer and explicit organisation membership; rotate agent and connector credentials. If old access must be supported temporarily, isolate it behind a single-org compatibility endpoint with separate issuer/audience and expiration.
6. **Runtime isolation.** Modify Python gateway queries and all auth, A2A, MCP, scheduler, worker and admin paths to require `org_id`; enforce cross-org composite foreign keys, scoped idempotency, independent reviewer credentials, tenant audit verification and bounded rate limits. Mandatory negative tests for all public APIs and internal job dispatch; never let tenant identifiers be selected by untrusted tool content.
7. **Edge cutover.** Verify configured private origin, signed audience-bound edge-to-origin assertion (or mTLS), body binding and replay denial. Make Worker a stateless forwarding edge. Export/validate D1 records if approved, then disable D1 writes after the new authority and failback strategy are proven. Do not delete D1 while rollback remains necessary.
8. **One vertical slice + deployment gates.** Authenticated client (issuer) → edge → origin → scoped outbox → restricted connector → independent verifier → audit receipt. Test 2 tenants, one worker crash after dispatch, duplicate requests, expiry/revocation, hostile prompt content, read-only verifier and direct-origin bypass. Require named GO/NO-GO evidence and rollback drill before any traffic switch.


## Schema guarantees and explicit gaps

- Runtime worker and reviewer use different, non-inheriting database roles; only the reviewer role may insert a verification. The gate checks transaction-local `shards.principal_id`, which is safe only when a trusted identity middleware controls the connection.
- `principals.controller_id` references tenant-scoped `controllers`; independent approval requires a distinct verifier controller and active auditor membership. Authority-side controller enrolment is **not yet built**, so controller strings alone cannot certify independence.
- **No close over live effects:** outbox initiation locks the parent task; a task may not close if any effect is pending, dispatching or unresolved. Direct `needs_reconciliation → failed` is disabled until a separately reviewed provider-evidence procedure exists. A confirmed/reconciled outbox result is *not* proof of provider truth; the runtime is not yet connected to an independent external-effect verifier.
- **Audit by construction:** triggers emit tenant-bound task, outbox and verification events in the same transaction as each row mutation; runtime cannot insert an arbitrary audit event. Composite receipt foreign keys require matching approval action, task, verifier and evidence digest. Distinguish row-party attribution from authenticated principal provenance.
- **PostgreSQL version contract:** PG16 and PG17 must pass schema and two-session row-lock race tests; CI must apply migrations in two DBs in the same cluster and reject insecure roles before table grants.
- Task-state triggers enforce `queued → running → reported → succeeded` with approved verification, plus explicit failure/cancellation/reconciliation paths; no resurrection of terminal or uncertain tasks.
- Audit append validates `seq`, the previous hash and SHA-256 of independently constructed canonical JSONB, then updates the head under a per-org row lock. Only the SECURITY DEFINER trigger has permission to modify the head; the v2 runtime role lacks it. This does not prevent database owner tampering or replace off-host anchoring.
- No raw SQL/API permission is offered to tenants. The DB role is a **NOLOGIN, NOBYPASSRLS** role with constrained grants; authenticated tenancy enforcement is still a mandatory application-layer control.
- Token revocation and edge nonce tables exist, but safe expiry cleanup under a separately authorised maintenance role and scheduled retention evidence still need implementation.
- The SQL migration is intentionally mutable **in this draft PR only**. Once a production database applies either migration, future changes must use an additive versioned migration. Do not reapply these files to an existing schema.

## Contract: idempotency and reconciliation

- `tasks.state`: `queued`, `running`, `reported`, `succeeded`, `failed`, `canceled`, `needs_reconciliation`. Legacy `blocked` requires operator review before translation. No transition automatically requeues `needs_reconciliation`.
- `effect_outbox.state`: `pending` → `dispatching` → `confirmed` or `needs_reconciliation`; `needs_reconciliation` → `reconciled` only with evidence. A new attempt must be an explicitly separately authorised operation; never silently reset a row.
- Uniqueness: `(org_id, actor_id, operation, idempotency_key)` for requests, and `(org_id, connector, idempotency_key)` for side effects. Duplicate identical bodies return the recorded receipt; conflicting payloads return conflict. Persist intent + audit transactionally before dispatch. A uniqueness constraint does not prove the provider performed an operation only once.
- An externally anchored audit receipt binds schema version, `org_id`, principal, action, target, input/effect digest, outbox ID, verification evidence, previous/entry hash and the deployment/source SHA. Proof validity requires independent verification of provider results and CI/diff, not an agent-written summary.

## Evidence gates (all FAIL/CANNOT CLAIM until exercised)

| Gate | Failure test |
| --- | --- |
| Tenant default deny | No validated membership / no `shards.org_id` returns no rows and cannot write |
| Tenant FKs | Cross-organisation creator, assignee, reviewer or task reference rejected |
| Edge bypass | Direct origin call without trusted edge assertion denied |
| Confused deputy | No downstream connector accepts an MCP user token |
| Prompt injection | Malicious issue/PR text cannot expand worker or verifier permissions |
| Review independence | Verifier has separate read-only credential and independently fetched CI/diff/effect proof |
| Crash/replay | Ambiguous dispatch quarantined; repeated request cannot duplicate provider side effect |
| Revocation | Max accepted token lifetime <= 300s; emergency revocation latency measured |
| Audit integrity | Old ledger still validates; v2 digest binds org; independent anchor matches |
| Recovery | Off-host encrypted restore and schema+ledger checks match recorded RTO/RPO |

**Rollback:** before production switch, drop *disposable* v2 instance and keep v1 unchanged. After switch, do not revert to an independently writable v1 or D1 store: stop writes, preserve v2 audit/outbox state, reconcile provider effects, and use an approved state-preserving recovery plan. Unilateral database rollback is not safe.

**No live migration or hosted-service certification is performed by adding these files.**
