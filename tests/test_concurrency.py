"""Multi-process-style concurrency and v0.1 schema compatibility checks.

Uses separate SQLite connections in each caller thread through Gateway.tx().
No mocks of task locks or audit persistence.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest

from shards_mcp.core import Gateway, GatewayError


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "gateway.sqlite")
        self.admin_token = secrets.token_urlsafe(48)
        self.g = Gateway(self.db, self.admin_token)
        self.root = self.g.authenticate(self.admin_token)
        scopes = ["message:send", "message:read", "task:create", "task:read",
                  "task:claim", "task:update"]
        a = self.g.register(self.root, "creator", "test", [], scopes)
        b = self.g.register(self.root, "worker", "test", [], scopes)
        self.creator = self.g.authenticate(a["token"])
        self.worker = self.g.authenticate(b["token"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_concurrent_task_claim_has_one_winner(self):
        tid = self.g.task_create(self.creator, self.worker.agent_id, {"action": "health"}, "task")["task_id"]
        # Independent Gateway objects use independent SQLite connections, as deployed workers would.
        gateways = [Gateway(self.db, self.admin_token) for _ in range(12)]
        def claim(gateway):
            try:
                return gateway.task_claim(self.worker, tid)["state"]
            except GatewayError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(claim, gateways))
        self.assertEqual(outcomes.count("running"), 1, outcomes)
        self.assertEqual(outcomes.count("CONFLICT"), 11, outcomes)
        self.assertEqual(self.g.task_get(self.creator, tid)["attempts"], 1)
        self.assertTrue(self.g.audit_verify(self.root)["valid"])

    def test_concurrent_idempotent_messages_single_write(self):
        def send(_):
            return self.g.send(self.creator, self.worker.agent_id, {"task": "same"}, "one-key")
        start = self.g.audit_verify(self.root)["count"]
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(send, range(12)))
        self.assertEqual(len({x["message_id"] for x in results}), 1)
        self.assertEqual(sum(not x["deduplicated"] for x in results), 1)
        self.assertEqual(self.g.audit_verify(self.root)["count"], start + 1)
        self.assertEqual(len(self.g.inbox(self.worker)), 1)

    def test_replay_remains_idempotent_after_destination_revoked(self):
        message = self.g.send(self.creator, self.worker.agent_id, {"notice": 1}, "delivery-key")
        task = self.g.task_create(self.creator, self.worker.agent_id, {"action": "health"}, "task-key")
        self.g.revoke(self.root, self.worker.agent_id)
        replay_message = self.g.send(self.creator, self.worker.agent_id, {"notice": 1}, "delivery-key")
        replay_task = self.g.task_create(self.creator, self.worker.agent_id, {"action": "health"}, "task-key")
        self.assertEqual(replay_message["message_id"], message["message_id"])
        self.assertTrue(replay_message["deduplicated"])
        self.assertEqual(replay_task["task_id"], task["task_id"])
        self.assertTrue(replay_task["deduplicated"])
        with self.assertRaises(GatewayError):
            self.g.send(self.creator, self.worker.agent_id, {"notice": 2}, "new-key")
        with self.assertRaises(GatewayError):
            self.g.task_create(self.creator, self.worker.agent_id, {"action": "health"}, "new-task")

    def test_distinct_concurrent_messages_preserve_audit_chain(self):
        start = self.g.audit_verify(self.root)["count"]
        def send(n):
            return self.g.send(self.creator, self.worker.agent_id, {"n": n}, f"key-{n}")
        with ThreadPoolExecutor(max_workers=16) as pool:
            sent = list(pool.map(send, range(40)))
        self.assertEqual(len({x["message_id"] for x in sent}), 40)
        self.assertEqual(self.g.audit_verify(self.root)["count"], start + 40)
        pages = self.g.message_poll(self.worker, limit=50)["messages"]
        self.assertEqual(len(pages), 40)


class MigrationTests(unittest.TestCase):
    def test_legacy_task_table_migrates_without_losing_data(self):
        with tempfile.TemporaryDirectory() as root:
            database = str(Path(root) / "legacy.sqlite")
            with sqlite3.connect(database) as db:
                db.execute("""CREATE TABLE tasks (
                  id TEXT PRIMARY KEY, creator TEXT NOT NULL, assignee TEXT NOT NULL,
                  state TEXT NOT NULL, input TEXT NOT NULL, result TEXT,
                  lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                  idem TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
                  UNIQUE(creator, idem)
                )""")
                db.execute("""INSERT INTO tasks
                    (id,creator,assignee,state,input,created,updated)
                    VALUES ('old','origin','worker','queued','{}','2026-01-01','2026-01-01')""")
            gateway = Gateway(database, secrets.token_urlsafe(48))
            with gateway.read_tx() as db:
                columns = {r["name"] for r in db.execute("PRAGMA table_info(tasks)")}
                row = db.execute("SELECT id,input,state FROM tasks WHERE id='old'").fetchone()
                versions = {r["name"] for r in db.execute("PRAGMA table_info(verifications)")}
            self.assertIn("lease_started", columns)
            self.assertEqual(dict(row), {"id": "old", "input": "{}", "state": "queued"})
            self.assertIn("evidence", versions)


if __name__ == "__main__":
    unittest.main()
