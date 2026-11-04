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

Do not mark as production-ready until the applicable phases have independent evidence. Implementation presence is not verification.
