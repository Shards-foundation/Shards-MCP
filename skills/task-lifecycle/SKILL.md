---
name: task-lifecycle
description: Submit, claim, report and independently verify a bounded Shards-MCP task without blind external-effect retries.
---
# Task Lifecycle

**Trigger:** authorised task handoff or recovery demonstration. **Never use production trading/payment/deployment effects in a demo.**

1. **Inputs:** distinct creator/worker/verifier IDs and scoped tokens; assignee; JSON payload; stable idempotency key; approval evidence expectations.
2. **Create:** creator invokes `task_create(assignee, payload, idempotency_key)`. Repeat identical request to verify deduplication, never reuse key for a different task.
3. **Claim:** worker invokes `task_claim_next(lease_seconds=60)`; requires both `task:read` and `task:claim`. No task => exit without inventing work.
4. **Process:** for a demo only use `echo`/`sha256`/`health`, write `checkpoint_write`, then `task_complete(success=true,result=...)`. Result must be `reported`, **not** `succeeded`.
5. **Verify:** the creator or worker supplies results to the independent verifier through a separately authorised message or trusted out-of-band review channel; `task_get` does not allow third-party verifier reads. The verifier independently checks the evidence and invokes `task_verify(approved, evidence)`; creator/worker must not self-approve.
6. **Evidence receipt:** creator or assignee (or host operator) can call `verification_get` on the task. A third-party verifier is **not** authorised to call `verification_get` merely because it approved; capture the returned evidence via an authorised operator or signed review record.
7. **Recover:** lease expiry => operator checks external world first, then `task_reconcile` only on documented proof. Otherwise task stays blocked.
8. **Output:** IDs (not secrets), states, evidence hash, audit/result consistency, duration and decision PASS/FAIL. Stop on mismatch, duplicate effects or scope bypass.
