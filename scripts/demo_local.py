#!/usr/bin/env python3
"""Deterministic local Shards-MCP demo. No network, external tools or secrets emitted."""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import tempfile

from shards_mcp.core import Gateway
from shards_mcp.worker import safe_operation


def require(condition: bool, message: str) -> None:
    """Fail closed even under python -O / PYTHONOPTIMIZE."""
    if not condition:
        raise RuntimeError("DEMO FAIL: " + message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="shards-mcp-demo-") as folder:
        secret = secrets.token_urlsafe(48)
        gateway = Gateway(str(Path(folder) / "state.sqlite"), secret)
        admin = gateway.authenticate(secret)
        roles = [
            ("creator", ["task:create", "task:read"]),
            ("worker", ["task:read", "task:claim", "task:update", "checkpoint:write"]),
            ("verifier", ["task:verify", "task:read"]),
        ]
        identities = {
            role: gateway.register(admin, role, "local-demo", [], scopes)
            for role, scopes in roles
        }
        actors = {
            role: gateway.authenticate(data["token"])
            for role, data in identities.items()
        }
        creator, worker, verifier = (actors[k] for k in ("creator", "worker", "verifier"))
        require(len({creator.agent_id, worker.agent_id, verifier.agent_id}) == 3, "roles not distinct")
        input_data = {"action": "echo", "data": "shards-mcp-safe-demo"}
        created = gateway.task_create(creator, worker.agent_id, input_data, "demo-echo-001")
        repeated = gateway.task_create(creator, worker.agent_id, input_data, "demo-echo-001")
        require(repeated["deduplicated"] is True, "idempotency deduplication failed")
        task_id = created["task_id"]
        claimed = gateway.task_claim_next(worker, lease_seconds=60)
        require(claimed["claimed"] is True and claimed["task"]["id"] == task_id, "worker did not claim assigned task")
        gateway.checkpoint(worker, task_id, {"stage": "safe-operation-started"})
        result = safe_operation(claimed["task"]["input"])
        require(result == {"echo": "shards-mcp-safe-demo"}, "unexpected deterministic worker output")
        reported = gateway.task_complete(worker, task_id, True, result)
        require(reported["state"] == "reported", "worker report bypassed verifier")
        persisted = gateway.task_get(creator, task_id)
        require(persisted["state"] == "reported", "creator saw incorrect reported state")
        require(persisted["result"] == {"echo": "shards-mcp-safe-demo"}, "persisted result differs from expected output")
        verified = gateway.task_verify(
            verifier, task_id, approved=True,
            evidence={"assertion": "persisted-echo-output-matched-expected-value", "expected": persisted["result"]},
        )
        require(verified["state"] == "succeeded", "verification failed")
        final = gateway.task_get(creator, task_id)
        audit = gateway.audit_verify(admin)
        require(audit["valid"] is True, "audit integrity failed")
        require(final["state"] == "succeeded", "final task state invalid")
        require(final["result"] == {"echo": "shards-mcp-safe-demo"}, "verified task output changed")
        report = {
            "ok": True,
            "task_state": final["state"],
            "creator_id": creator.agent_id,
            "worker_id": worker.agent_id,
            "verifier_id": verifier.agent_id,
            "idempotency_deduplicated": repeated["deduplicated"],
            "audit_valid": audit["valid"],
            "audit_entries": audit["count"],
            "temporary_database": True,
            "external_actions_executed": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

