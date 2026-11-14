"""Security regression: task:create is not blanket authority over other agents.

This is a Python/SQLite coordination boundary, not a guarantee about the tools
that an independently integrated LLM worker may execute.
"""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import os
import unittest

from shards_mcp.a2a import A2AAdapter
from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import TOOL_LIST


class DelegationACLTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "acl.sqlite")
        self.secret = secrets.token_urlsafe(48)
        self.g = Gateway(self.path, self.secret)
        self.root = self.g.authenticate(self.secret)
        self.creator = self.g.register(self.root, "creator", "mock", [], ["task:create", "task:read"])
        self.worker = self.g.register(self.root, "worker", "mock", [], ["task:read", "task:claim", "task:update"])
        self.other = self.g.register(self.root, "other", "mock", [], ["task:read", "task:claim"])
        self.actor = self.g.authenticate(self.creator["token"])
        self.destination = self.worker["agent_id"]

    def test_default_denial_has_no_task_or_audit_side_effect(self):
        before = self.g.audit_verify(self.root)
        with self.assertRaises(GatewayError) as caught:
            self.g.task_create(self.actor, self.destination, {"action": "health"}, "blocked")
        self.assertEqual(caught.exception.code, "FORBIDDEN")
        with self.g.read_tx() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        self.assertEqual(self.g.audit_verify(self.root), before)

    def test_exact_grant_is_operator_only_and_audited(self):
        with self.assertRaises(GatewayError) as denied:
            self.g.delegation_grant(self.actor, self.creator["agent_id"], self.destination)
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        granted = self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        self.assertTrue(granted["granted"])
        self.assertFalse(granted["unchanged"])
        self.assertTrue(self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)["unchanged"])
        with self.assertRaises(GatewayError) as denied:
            self.g.delegations(self.actor)
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        self.assertEqual(len(self.g.delegations(self.root)), 1)
        self.assertEqual(self.g.audit_list(self.root, 1)[0]["action"], "delegation.grant")
        self.assertTrue(self.g.audit_verify(self.root)["valid"])

    def test_grant_is_not_wildcard_and_does_not_leak_to_other_agent(self):
        self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        self.assertEqual(self.g.task_create(self.actor, self.destination, {}, "permitted")["state"], "queued")
        with self.assertRaises(GatewayError) as error:
            self.g.task_create(self.actor, self.other["agent_id"], {}, "not-permitted")
        self.assertEqual(error.exception.code, "FORBIDDEN")
        with self.assertRaises(GatewayError) as error:
            self.g.delegation_grant(self.root, self.creator["agent_id"], "*")
        self.assertEqual(error.exception.code, "NOT_FOUND")

    def test_grant_survives_restart_and_revocation_blocks_only_new_tasks(self):
        self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        original = self.g.task_create(self.actor, self.destination, {"action": "health"}, "replay")
        reopened = Gateway(self.path, self.secret)
        self.assertEqual(len(reopened.delegations(self.root)), 1)
        self.assertTrue(reopened.delegation_revoke(self.root, self.creator["agent_id"], self.destination)["changed"])
        audit_after_first = reopened.audit_list(self.root, 5)
        self.assertEqual(sum(item["action"] == "delegation.revoke" for item in audit_after_first), 1)
        self.assertFalse(reopened.delegation_revoke(self.root, self.creator["agent_id"], self.destination)["changed"])
        self.assertEqual(reopened.audit_list(self.root, 5), audit_after_first)
        with self.assertRaises(GatewayError) as denied:
            reopened.task_create(self.actor, self.destination, {"action": "health"}, "new")
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        self.assertTrue(reopened.task_create(self.actor, self.destination,
                                            {"action": "health"}, "replay")["deduplicated"])
        with self.assertRaises(GatewayError) as collision:
            reopened.task_create(self.actor, self.destination, {"action": "different"}, "replay")
        self.assertEqual(collision.exception.code, "CONFLICT")
        self.assertEqual(reopened.task_get(self.actor, original["task_id"])["state"], "queued")
        self.assertTrue(reopened.audit_verify(self.root)["valid"])

    def test_revoke_after_claim_does_not_claim_abort_external_effects(self):
        self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        tid = self.g.task_create(self.actor, self.destination, {"action": "health"}, "inflight")["task_id"]
        worker = self.g.authenticate(self.worker["token"])
        self.assertEqual(self.g.task_claim(worker, tid)["state"], "running")
        self.g.delegation_revoke(self.root, self.creator["agent_id"], self.destination)
        self.assertEqual(self.g.task_complete(worker, tid, True, {"ok": True})["state"], "reported")

    def test_self_tasks_and_operator_only_exception(self):
        self.assertEqual(self.g.task_create(self.actor, self.creator["agent_id"], {}, "own")["state"], "queued")
        self.assertEqual(self.g.task_create(self.root, self.destination, {}, "admin")["state"], "queued")
        with self.assertRaises(GatewayError):
            self.g.delegation_grant(self.root, self.creator["agent_id"], self.creator["agent_id"])

    def test_scheduler_is_out_of_band_operator_approved_not_agent_delegation(self):
        # The administrator explicitly provisions recurring tasks. Agent tokens
        # cannot provision, disable or dispatch schedules; there is no general
        # agent-controlled bypass of the creator -> assignee allowlist.
        with self.assertRaises(GatewayError) as denied:
            self.g.schedule_create(self.actor, self.destination, {"action": "health"}, 60)
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        with self.assertRaises(GatewayError) as denied:
            self.g.schedule_tick(self.actor)
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        schedule = self.g.schedule_create(self.root, self.destination, {"action": "health"}, 60)
        with self.g.tx() as db:
            db.execute("UPDATE schedules SET next_due='2000-01-01T00:00:00+00:00' WHERE id=?",
                       (schedule["schedule_id"],))
        dispatched = self.g.schedule_tick(self.root)["dispatched"]
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(self.g.task_get(self.root, dispatched[0])["creator"], "scheduler")
        with self.assertRaises(GatewayError) as denied:
            self.g.task_create(self.actor, self.destination, {}, "still-denied")
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        self.assertTrue(self.g.audit_verify(self.root)["valid"])

    def test_revoked_agents_cannot_receive_new_grants(self):
        self.g.revoke(self.root, self.destination)
        with self.assertRaises(GatewayError) as error:
            self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        self.assertEqual(error.exception.code, "NOT_FOUND")

    def test_a2a_sendmessage_uses_same_denial_boundary(self):
        adapter = A2AAdapter(self.g, "http://127.0.0.1:8787")
        rpc = {"jsonrpc": "2.0", "id": 10, "method": "SendMessage", "params": {
            "message": {"messageId": "acl-01", "role": "ROLE_USER", "parts": [{"text": "safe test"}]}}}
        denied = adapter.process(self.actor, self.destination, rpc)
        self.assertEqual(denied["error"]["code"], -32003)
        with self.g.read_tx() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        self.g.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        self.assertEqual(adapter.process(self.actor, self.destination, rpc)["result"]["task"]["id"][:4], "tsk_")

    def test_no_mcp_tool_can_mutate_delegation_policy(self):
        exposed = {tool["name"] for tool in TOOL_LIST}
        self.assertFalse(any("delegation" in name.replace("-", "_") for name in exposed))

    def test_existing_schema_migrates_to_empty_fail_closed_grants(self):
        # Model a SQLite database written by the experimental version before
        # delegation_grants existed; startup creates an empty policy table.
        prior = self.g.task_create(self.root, self.destination, {}, "old-task")
        with self.g.tx() as db:
            db.execute("DROP TABLE delegation_grants")
        migrated = Gateway(self.path, self.secret)
        self.assertEqual(migrated.delegations(self.root), [])
        self.assertEqual(migrated.task_get(self.root, prior["task_id"])["state"], "queued")
        with self.assertRaises(GatewayError) as denied:
            migrated.task_create(self.actor, self.destination, {}, "new-agent-task")
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        migrated.delegation_grant(self.root, self.creator["agent_id"], self.destination)
        self.assertEqual(migrated.task_create(self.actor, self.destination, {}, "new-agent-task")["state"], "queued")

    def test_local_admin_cli_grant_revoke_and_list(self):
        env = {**os.environ, "SHARDS_DB": self.path, "SHARDS_ADMIN_TOKEN": self.secret}
        def invoke(*arguments):
            return subprocess.run([sys.executable, "-m", "shards_mcp.admin", *arguments],
                                  env=env, text=True, capture_output=True, timeout=15)
        failed = invoke("delegation-grant", "--creator", self.creator["agent_id"],
                        "--assignee", "*")
        self.assertNotEqual(failed.returncode, 0)
        granted = invoke("delegation-grant", "--creator", self.creator["agent_id"],
                         "--assignee", self.destination)
        self.assertEqual(granted.returncode, 0, granted.stderr)
        self.assertTrue(json.loads(granted.stdout)["granted"])
        listed = invoke("delegation-list")
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(len(json.loads(listed.stdout)), 1)
        revoked = invoke("delegation-revoke", "--creator", self.creator["agent_id"],
                         "--assignee", self.destination)
        self.assertEqual(revoked.returncode, 0, revoked.stderr)
        self.assertTrue(json.loads(revoked.stdout)["changed"])
        outputs = failed.stdout + failed.stderr + granted.stdout + granted.stderr + \
                  listed.stdout + listed.stderr + revoked.stdout + revoked.stderr
        self.assertNotIn(self.secret, outputs)


if __name__ == "__main__":
    unittest.main()
