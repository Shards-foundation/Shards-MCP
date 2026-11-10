# ADR-0001: Ship a bounded single-host agent gateway before enterprise SaaS

**Status:** Accepted as current implementation boundary (recorded 7 November 2026).
**Context:** Shards-MCP provides audited, authenticated task coordination. Future scope includes public SaaS, multi-organisation accounts, more agent protocols and external tools.

## Decision

Maintain an operable single-organisation, single-host SQLite gateway with least-privilege principals and explicit external-effect reconciliation as a shippable package. Treat multi-tenant SaaS, distributed Postgres/fencing, full OAuth provider flow, HA and ChatGPT directory approval as separate products/gates, not implied by a passing local test.

## Consequences

**Benefits:** fewer trust boundaries, reproducible Python environment, straightforward local installation, explicit task ownership and honest documentation.

**Constraints:** no cross-host exactly-once effects, no live hosted service guarantee, no enterprise tenancy isolation, manual encrypted off-host backup and immutable audit anchoring are deployment responsibilities.

## Alternatives considered

- Ship an integrated multi-tenant platform immediately: rejected for current release because identity, retention and operational controls are not yet proven.
- Add arbitrary worker execution by default: rejected because untrusted task payloads cannot safely become commands.
- Ignore external effect ambiguity after lease expiry: rejected because blind replay can cause duplicate irreversible actions.

## Exit criteria

Revisit when customer demand is demonstrated and multi-host state/correctness, audited identity/tenancy, recovery and consequential-action authorisation have independent test evidence.
