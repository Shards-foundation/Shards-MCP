# Security Policy and Threat Boundary

**Version:** v0.1.x | **Status:** experimental, single-host, single-organisation software, **not production-certified**. This repository does not evidence an operating public hosted service.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** for this repository when enabled, or a privately arranged trusted maintainer channel. Do not publish exploit payloads, live credentials, customer content or unpatched issues in public discussions. If no private reporting channel is available, do not publish secrets to request one; ask a maintainer to enable a secure disclosure channel.

Include exact commit/version, minimal reproducible environment, affected trust boundary, steps, impact, optional proposed fix and contact path. The project currently offers **no staffed response SLA, guaranteed embargo period or bug bounty**. Maintainers should acknowledge and triage privately where possible; severe credential or authorisation bypasses block release.

## Support and security scope

- **In scope:** authenticated MCP/REST/A2A boundaries, resource metadata and JWT validation, principal ownership, task leases, idempotency, verification, audit/snapshot integrity, stdio/worker network handling, NextAuth preview configuration, build/release supply chain.
- **Out of scope / not offered:** third-party AI models, client IDE security, custom downstream workers, consumer wallet/exchange systems, public production hosting, multi-tenant IAM and billing. Do not test infrastructure that you do not own or have permission to assess.

## Authentication and least privilege

- Local bootstrap admin credential must be high-entropy and kept on the gateway **host only**, supplied via `SHARDS_ADMIN_TOKEN` or a protected `SHARDS_ADMIN_TOKEN_FILE`. Never pass it into any MCP/IDE/LLM client or browser.
- Host-only `shards-mcp-admin` creates individual bearer credentials in exclusive owner-only files and revokes by agent ID. The network tool surface cannot register or revoke agents.
- Local token digests are stored in SQLite. Agents cannot enrol wildcard/admin scope; tool discovery and every tool invocation apply the authenticated principal's scopes and owner constraints.
- Remote listener explicitly requires `SHARDS_AUTH_MODE=oauth`, an HTTPS reverse proxy, pinned trusted JWT issuer/JWKS URI, exact resource audience and separately enrolled `oauth_subject`. The gateway is a **resource server**, not an authorisation server; it does not issue code/PKCE/refresh tokens. Local agent tokens are rejected in OAuth mode.
- Console Google/GitHub/Discord sign-in is provider-subject allowlisted; it does not authorise gateway operations or implement tenant RBAC.

## Storage, message and task security

SQLite WAL provides transactional claims and mutation-plus-audit commits **on one host**. A 64-connection limit, request timeouts and strict payload parsing reduce accidental overload, not production rate abuse. Message and task visibility is owner-scoped; `shared.*` events are untrusted broadcasts; `system.*` is operator-only.

The default worker executes deterministic `echo`, `sha256` and `health` actions only, plus A2A text echo. Never interpret a received payload as shell, web, payments, deployment or trading authorisation. Claimed work cannot be cancelled/rolled back automatically. Success is `reported` until a distinct authorised verifier attests; expired leases require explicit external-effect reconciliation rather than retry.

## Audit and backups

Audit hash-chain entries are appended transactionally; application-level UPDATE/DELETE triggers reject ordinary edits. **A database owner can remove triggers and rewrite/re-hash the entire ledger.** Immutable independent off-host anchoring is required before claiming tamper-evidence against a privileged database attacker. Verification evidence and task payloads are stored in plaintext SQLite; sensitive deployments need encryption, minimisation and retention policies.

The backup CLI creates verified local SQLite snapshots, not automated encrypted off-host backups or tested disaster recovery. The operator must copy, encrypt, restore-test and rotate them. A restored database cannot undo downstream actions.

## Known residual gaps

No general application-layer rate limiting/quotas; no enterprise multi-tenant isolation; no Postgres HA/fencing; no independent audit anchoring; no default data retention/DSAR/subject export; no running-task kill; no globally exactly-once downstream effects; no public OAuth provider/client E2E proof; no full MCP extensions or A2A streaming/push. Hosted use requires separate security review, monitor/alert system, incident handling and data-processing controls.

## Incident procedure

1. Contain access and consequential integrations; keep task/event state intact.
2. Revoke suspected identities using host-only admin CLI; rotate operator/issuer secrets as needed.
3. Preserve redacted logs, snapshot and immutable external evidence if available.
4. Check audit validity and any downstream effects before reconciling a blocked task.
5. Assess regulatory/contract notification duties with the actual operator; no automation may declare legal compliance.
6. Reopen only after denied-token and owner-boundary tests pass, with recorded approver.

See [threat model](docs/threat-model.md), [rulebook](docs/rulebook.md), [recovery skill](skills/incident-recovery/SKILL.md) and [operational signoff](docs/compliance/publication-gates.md).
