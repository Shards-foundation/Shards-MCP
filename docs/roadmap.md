# Roadmap and release gates

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Authenticated MCP, registry, messages, tasks, checkpoints, audit | Unit, HTTP and restart tests |
| 1 | OAuth 2.1 resource server and official MCP SDK conformance | Denial, issuer/audience, tool, client integration tests |
| 2 | Full A2A protocol adapter | Independent A2A agent interop and cancellation tests |
| 3 | Postgres transactional outbox, fencing, reliable worker and cron | Crash/replay/failover fault injection |
| 4 | OpenTelemetry, Sentry, dashboard and alarms | Traceability, health and incident drills |
| 5 | GitHub, Vercel, Neon, Supabase, Shards-Kernel adapters | Scoped end-to-end tests and human approvals |
| 6 | Security review, backups, disaster recovery and signed releases | Measured reliability and production release signoff |
| 7 | Platform distribution | Verified ChatGPT plugin and other runtime compatibility matrix |

## OAuth progress

An optional external JWT resource-server verifier and RFC 9728 metadata endpoint have been added with automated signed-token negative tests. This is partial phase 1 progress. Full provider interoperability, actual ChatGPT connection, HTTPS deployment, OAuth refresh handling and broader production authentication assurance are still pending.

## Independent review — 4 November 2026

B1-B4 addressed in PR #1: audited bounded leases, verified non-empty evidence retention, read-only authentication and bounded HTTP parsing, and explicit Docker remote binding opt-in. Regression tests exercise these findings, together with cursor-based messaging, scheduling, audit integrity and credential hygiene. This is partial coverage; passing CI is not a complete formal security proof.

Still pending: fine-grained per-topic grants beyond the current private/shared/system namespaces, per-agent quotas and retention, OAuth resource-server support, independent audit anchoring, distributed storage, deployment and multi-platform interoperability. Local out-of-band agent provisioning and agent-level audit isolation are implemented.

Do not mark as production-ready until the applicable phases have independent evidence. Implementation presence is not verification.


## A2A v1.0 interoperability work

An authenticated, explicitly opt-in JSON-RPC v1.0 adapter implements per-agent cards and text-only SendMessage/GetTask mapped to durable Shards tasks. This is a **partial adapter**, not a claim of full A2A compliance or compatibility with every AI platform. The A2A conformance and live multi-runtime interoperability gate remains open, along with streaming, push notification and cancellation.

