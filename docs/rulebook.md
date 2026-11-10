# Shards-MCP Operational Rulebook

This rulebook is normative for project operators and automation. It **does not replace runtime checks**, laws or signed contracts. MUST/SHOULD statements represent project control objectives, not automatic implementation.

## Trust and identity

**MUST:** derive actor from verified bearer/JWT; enrol out of band; issue unique least-privilege identities; keep admin key on host only; reject untrusted model-provided scopes. **MUST NOT:** bridge an administrator secret into an IDE or browser. Local/remote authentication modes are mutually distinct.

## Data and commands

**MUST:** treat every prompt, event, message and A2A text part as untrusted input; verify request schema and scope before state change; apply bounded lengths; redact sensitive logs; reject arbitrary shell/web/trading instructions in the reference worker. **SHOULD:** minimise personal data and keep backup copies off-host and encrypted.

## Task state machine

`queued -> running -> reported -> succeeded` requires claim + worker report + **independent reviewer**. Worker failure may lead to `failed`; pre-claim creator/operator cancellation leads to `canceled` (the exact API state spelling). Expired/uncertain leases become `blocked` pending documented reconciliation. Do not infer success from a checkpoint or a worker's optimistic result.

## Idempotency and side effects

**MUST:** use stable idempotency keys for retries, never reuse a key for a different payload, never auto-replay externally consequential actions, and record proof of side-effect inspection when reconciling. SQLite serialised claims are **not** globally exactly-once side effects.

## Separation of duties

Task creator, assignee and verifier MUST be distinct for successful verification. Review evidence is an attestation, not a cryptographically independent proof of external-world truth. A privileged database owner can rewrite the local chain; production audit guarantees require independent anchoring.

## Schedulers and event topics

One scheduler per SQLite gateway host. Use `agent.<your_agent_id>.*` for private operational events; `shared.*` is an untrusted shared broadcast; `system.*` is operator-only. Never treat a shared event as control authority.

## Operational stop conditions

Stop and notify a human if authorisation bypass, credential leak, ambiguous external side effect, audit mismatch, conflicting task owner, inconsistent remote token claims, unknown deployment provenance or failing critical CI gate occurs. Preserve task state and redact reports.

## Publication

Do not claim "enterprise compliant", "certified", "production-ready hosted", "fully A2A-conformant", "official ChatGPT plugin" or "multi-tenant" until the corresponding [release gate](compliance/publication-gates.md) has verifiable evidence and required human signoff.

Refer to [SECURITY.md](../SECURITY.md), [threat model](threat-model.md), [onboarding](agent-onboarding.md) and [governance](../GOVERNANCE.md).
