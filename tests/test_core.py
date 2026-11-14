import secrets
import hashlib
import os
import sqlite3
import tempfile
import unittest

from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import dispatch, validate_args


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = secrets.token_urlsafe(48)
        self.dbpath = os.path.join(self.temp.name, "state.db")
        self.g = Gateway(self.dbpath, self.secret)
        self.root = self.g.authenticate(self.secret)
        scope = ["agent:read", "agent:heartbeat", "message:send", "message:read",
                 "task:create", "task:read", "task:claim", "task:update", "checkpoint:write",
                 "event:write", "event:read"]
        a = self.g.register(self.root, "agent-a", "test", ["messaging"], scope)
        b = self.g.register(self.root, "agent-b", "test", ["worker"], scope)
        self.aid, self.bid = a["agent_id"], b["agent_id"]
        self.g.delegation_grant(self.root, self.aid, self.bid)
        self.g.controller_set(self.root, self.aid, "origin-team")
        self.g.controller_set(self.root, self.bid, "worker-team")
        self.a = self.g.authenticate(a["token"])
        self.b = self.g.authenticate(b["token"])

    def tearDown(self):
        self.temp.cleanup()

    def test_reject_weak_bootstrap_secret(self):
        with self.assertRaises(ValueError):
            Gateway(self.dbpath, "x" * 48)

    def test_credentials_and_scopes(self):
        with self.assertRaises(GatewayError):
            self.g.authenticate("bad-token")
        with self.assertRaises(GatewayError):
            self.g.register(self.a, "attacker", "test", [], [])
        with self.assertRaises(GatewayError):
            self.g.register(self.root, "bad", "test", [], ["*"])
        self.g.revoke(self.root, self.aid)
        with self.assertRaises(GatewayError):
            self.g.authenticate("bad-token")
        with self.assertRaises(GatewayError):
            self.g.heartbeat(self.a)

    def test_agents_do_not_expose_secrets(self):
        agents = self.g.agents(self.a)
        self.assertEqual(len(agents), 2)
        self.assertNotIn("token_hash", agents[0])
        self.assertNotIn("token", agents[0])

    def test_message_deduplication_and_access(self):
        first = self.g.send(self.a, self.bid, {"hello": "world"}, "m1")
        second = self.g.send(self.a, self.bid, {"hello": "world"}, "m1")
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertTrue(second["deduplicated"])
        with self.assertRaises(GatewayError):
            self.g.send(self.a, self.bid, {"hello": "changed"}, "m1")
        self.assertEqual(self.g.inbox(self.b)[0]["body"], {"hello": "world"})
        self.assertEqual(self.g.inbox(self.a), [])

    def test_task_workflow_checkpoint_restart(self):
        created = self.g.task_create(self.a, self.bid, {"repair": "PR-77"}, "t1")
        tid = created["task_id"]
        self.assertTrue(self.g.task_create(self.a, self.bid, {"repair": "PR-77"}, "t1")["deduplicated"])
        with self.assertRaises(GatewayError):
            self.g.task_create(self.a, self.bid, {"repair": "other"}, "t1")
        with self.assertRaises(GatewayError):
            self.g.task_claim(self.a, tid)
        self.g.task_claim(self.b, tid)
        cp = self.g.checkpoint(self.b, tid, {"stage": 1})
        self.assertEqual(cp["version"], 1)
        reopened = Gateway(self.dbpath, self.secret)
        self.assertEqual(reopened.checkpoint_get(self.a, tid)["checkpoint"]["body"], {"stage": 1})
        reopened.task_renew(self.b, tid)
        self.assertEqual(reopened.task_complete(self.b, tid, True, {"ok": True})["state"], "reported")
        self.assertEqual(reopened.task_get(self.a, tid)["result"], {"ok": True})
        reviewer = reopened.register(self.root, "workflow-reviewer", "test", [], ["task:verify"])
        reopened.controller_set(self.root, reviewer["agent_id"], "review-team")
        reopened.verifier_assign(self.root, tid, reviewer["agent_id"])
        self.assertEqual(reopened.task_verify(reopened.authenticate(reviewer["token"]), tid,
                                                True, {"checks": ["sha256"]})["state"], "succeeded")
        with self.assertRaises(GatewayError):
            reopened.task_complete(self.b, tid, True, {"ok": True})

    def test_expiry_blocks_unsafe_retry(self):
        tid = self.g.task_create(self.a, self.bid, {}, "t2")["task_id"]
        self.g.task_claim(self.b, tid)
        with self.g.tx() as db:
            db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?", (tid,))
        self.assertIn(tid, self.g.expired(self.root))
        with self.assertRaises(GatewayError):
            self.g.task_claim(self.b, tid)
        with self.assertRaises(GatewayError):
            self.g.reconcile(self.root, tid, False, "not actually checked")
        self.g.reconcile(self.root, tid, True, "Verified downstream effects absent")
        self.assertEqual(self.g.task_claim(self.b, tid)["state"], "running")

    def test_audit_verification_and_tamper_detection(self):
        self.assertTrue(self.g.audit_verify(self.root)["valid"])
        self.g.send(self.a, self.bid, {"x": 1}, "m2")
        self.assertTrue(self.g.audit_verify(self.root)["valid"])
        with self.g.tx() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE audit SET action='forged' WHERE seq=1")
        # Simulate a compromised database owner, who can drop protective triggers.
        # The independent hash verification must still detect an altered record.
        with self.g.tx() as db:
            db.execute("DROP TRIGGER audit_reject_update")
            db.execute("UPDATE audit SET action='forged' WHERE seq=1")
        self.assertFalse(self.g.audit_verify(self.root)["valid"])

    def test_schedule_tick(self):
        sch = self.g.schedule_create(self.root, self.bid, {"job": "check"}, 60)
        self.assertTrue(sch["schedule_id"])
        self.assertFalse(self.g.schedule_tick(self.root)["dispatched"])
        with self.g.tx() as db:
            db.execute("UPDATE schedules SET next_due='2000-01-01T00:00:00+00:00'")
        first = self.g.schedule_tick(self.root)["dispatched"]
        self.assertEqual(len(first), 1)
        self.assertEqual(self.g.task_get(self.root, first[0])["state"], "queued")
        self.assertFalse(self.g.schedule_tick(self.root)["dispatched"])

    def test_schema_enforcement(self):
        for name, args in [("task_claim", {"task_id": "x", "lease_seconds": True}),
                           ("message_send", {"destination": "x", "body": {}, "idempotency_key": "x", "scope": "*"}),
                           ("task_complete", {"task_id": "x", "success": "true", "result": {}})]:
            with self.assertRaises(GatewayError):
                validate_args(name, args)
        status = dispatch(self.g, self.root, "system_status", {})
        self.assertEqual(status["agents"], 2)

    def test_payload_limits(self):
        with self.assertRaises(GatewayError):
            self.g.send(self.a, self.bid, {"oversize": "a" * 150000}, "big")


    def test_recipient_ack_and_assignee_queue(self):
        sent = self.g.send(self.a, self.bid, {"hello": "worker"}, "ack-key")
        with self.assertRaises(GatewayError):
            self.g.message_ack(self.a, sent["message_id"])
        first = self.g.message_ack(self.b, sent["message_id"])
        self.assertTrue(first["acknowledged_at"])
        self.assertEqual(first, self.g.message_ack(self.b, sent["message_id"]))
        self.assertEqual(self.g.inbox(self.b)[0]["read_at"], first["acknowledged_at"])
        tid = self.g.task_create(self.a, self.bid, {"job": "demo"}, "queue-key")["task_id"]
        self.assertEqual([x["id"] for x in self.g.task_inbox(self.b)], [tid])
        self.assertEqual(self.g.task_inbox(self.a), [])
        self.g.task_claim(self.b, tid)
        self.assertFalse(self.g.task_inbox(self.b))
        self.assertEqual(self.g.task_inbox(self.b, "running")[0]["id"], tid)

    def test_durable_event_stream_and_cursor(self):
        emitted = self.g.event_publish(self.a, "shared.task.progress", {"percent": 25}, "ev1", "trace-1")
        self.assertFalse(emitted["deduplicated"])
        again = self.g.event_publish(self.a, "shared.task.progress", {"percent": 25}, "ev1", "trace-1")
        self.assertEqual(again["event_seq"], emitted["event_seq"])
        with self.assertRaises(GatewayError):
            self.g.event_publish(self.a, "shared.task.progress", {"percent": 26}, "ev1", "trace-1")
        found = self.g.event_poll(self.b, after_seq=0, topic="shared.task.progress")
        self.assertEqual(len(found["events"]), 1)
        self.assertEqual(found["events"][0]["body"], {"percent": 25})
        self.assertEqual(found["next_cursor"], emitted["event_seq"])
        self.assertEqual(self.g.event_poll(self.b, after_seq=found["next_cursor"])["events"], [])
        reopened = Gateway(self.dbpath, self.secret)
        self.assertEqual(len(reopened.event_poll(self.b)["events"]), 1)
        with self.assertRaises(GatewayError):
            self.g.event_poll(self.b, after_seq=-1)


    def test_system_sanity_and_heartbeat_state(self):
        fresh = next(x for x in self.g.agents(self.a) if x["id"] == self.aid)
        self.assertEqual(fresh["heartbeat_state"], "unobserved")
        self.g.heartbeat(self.a)
        seen = next(x for x in self.g.agents(self.a) if x["id"] == self.aid)
        self.assertEqual(seen["heartbeat_state"], "recent")
        self.assertTrue(self.g.sanity_check(self.root)["healthy"])
        with self.assertRaises(GatewayError):
            self.g.sanity_check(self.a)


    def test_independent_verification_gate(self):
        tid = self.g.task_create(self.a, self.bid, {"action": "health"}, "verify-1")["task_id"]
        self.g.task_claim(self.b, tid)
        self.assertEqual(self.g.task_complete(self.b, tid, True, {"status": "ok"})["state"], "reported")
        with self.assertRaises(GatewayError):
            self.g.task_verify(self.b, tid, True, {"proof": "self-attested"})
        with self.assertRaises(GatewayError):
            self.g.task_verify(self.a, tid, True, {"proof": "not an authorised reviewer"})
        reviewer = self.g.register(self.root, "reviewer", "test", ["verification"], ["task:verify", "task:read"])
        reviewer_id = self.g.authenticate(reviewer["token"])
        self.g.controller_set(self.root, reviewer_id.agent_id, "review-team")
        self.g.verifier_assign(self.root, tid, reviewer_id.agent_id)
        self.assertEqual(self.g.task_verify(reviewer_id, tid, True, {"proof": "verified hash"})["state"], "succeeded")
        with self.assertRaises(GatewayError):
            self.g.task_verify(self.root, tid, True, {"proof": "duplicate attestation"})
        other = self.g.task_create(self.a, self.bid, {"action": "health"}, "verify-2")["task_id"]
        self.g.task_claim(self.b, other)
        self.g.task_complete(self.b, other, True, {"status": "bad"})
        self.g.verifier_assign(self.root, other, reviewer_id.agent_id)
        self.assertEqual(self.g.task_verify(reviewer_id, other, False, {"proof": "failed evaluation"})["state"], "failed")


if __name__ == "__main__":
    unittest.main()
