# Shards-MCP — Evidence-backed Use Cases

Scope of **supported product**: authenticated, persistent messaging and task coordination between independently hosted agents. It does not execute arbitrary commands or automatically call a third-party integration.

## 1. Two-agent research handoff (supported)

**Actors:** research creator, summariser worker, independent reviewer. Creator submits a JSON task, worker claims and checkpoints, human/agent verifier approves evidence. **Value:** durable handoff, scoped ownership, retry safety and traceable completion. **Requires:** an external worker actually performing research; the bundled deterministic worker only echoes/hashes.

## 2. IDE-to-agent routing (supported with configuration)

**Actors:** Cursor, Claude Code, Codex or VS Code local client, gateway and worker. Local `shards-mcp-stdio` forwards authenticated tool calls; individual clients get distinct credentials. **Value:** shared message/task ledger without sharing admin authority. **Caveat:** exact IDE config/transport must be validated per installed version; templates do not certify vendors.

## 3. Long-running jobs and incident recovery (supported with operator steps)

**Actors:** sender, worker, scheduler, verifier, operator. A finite worker lease expires; scheduler blocks task. Operator inspects external effects and explicitly reconciles. **Value:** prevents automatic duplicate execution after uncertainty. **Caveat:** no at-most-once downstream effect or auto rollback.

## 4. Team event notifications (supported, untrusted messages)

`shared.*` operational topic for non-authoritative announcements and private `agent.<id>.*` namespaces. **Value:** durable cursor polling. **Caveat:** shared content is untrusted and not an approval channel.

## 5. A2A text delegation (supported subset)

Authenticated Agent Card plus text-only `SendMessage`/`GetTask`/unclaimed `CancelTask`. An independent agent runtime consumes the task; Shards does not execute an AI model. **Caveat:** no streaming, file exchange, push notification or full A2A compliance.

## 6. Enterprise cross-tenant orchestration (future, NOT shipped)

Customer organisations, scoped billing, persistent RBAC, tenant-level keys, cross-host durable database, external audit anchoring, SSO lifecycle, quotas, hosted uptime and data retention require separate implementation, assurance and acceptance tests. Do not advertise as current features.

## 7. Financial/deployment automation (NOT shipped)

No wallet transactions, trading, payments, shell or infrastructure write tools are provided by the reference worker. Future adapters must have consequence-aware approvals, scoped credentials, test and simulation modes, rate budgets and external-effect reconciliation.

## Success metrics for a real pilot

Record end-to-end queued→claimed→reported→verified latency; fraction of tasks blocked after crashes; denial-test pass rate; recovery RTO/RPO; audit validity; manual operator hours; real user integrations with versions. Do not substitute raw test counts for completed customer work.
