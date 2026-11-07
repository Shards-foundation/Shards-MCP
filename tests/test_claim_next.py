"""Atomic claim-next safety: FIFO, auth, cancellation, concurrency and MCP wire eras."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import make_handler, visible_tools


class ClaimNextCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "gateway.sqlite")
        self.secret = secrets.token_urlsafe(48)
        self.g = Gateway(self.db, self.secret)
        self.root = self.g.authenticate(self.secret)
        creator = self.g.register(
            self.root, "creator-next", "tests", [],
            ["task:create", "task:read", "task:cancel"],
        )
        worker = self.g.register(
            self.root, "worker-next", "tests", [],
            ["task:read", "task:claim", "task:update", "checkpoint:write"],
        )
        other = self.g.register(
            self.root, "other-next", "tests", [],
            ["task:read", "task:claim"],
        )
        claim_only = self.g.register(
            self.root, "claim-only", "tests", [], ["task:claim"],
        )
        self.creator = self.g.authenticate(creator["token"])
        self.worker = self.g.authenticate(worker["token"])
        self.other = self.g.authenticate(other["token"])
        self.claim_only = self.g.authenticate(claim_only["token"])

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, key, assignee=None):
        return self.g.task_create(
            self.creator, assignee or self.worker.agent_id,
            {"action": "echo", "data": {"key": key}}, key,
        )["task_id"]

    def test_empty_then_fifo_and_durable_lease(self):
        audit_before = self.g.audit_verify(self.root)["count"]
        self.assertEqual(
            self.g.task_claim_next(self.worker),
            {"claimed": False, "task": None},
        )
        self.assertEqual(self.g.audit_verify(self.root)["count"], audit_before)
        first = self.create("first")
        second = self.create("second")
        third = self.create("third")
        self.assertEqual(self.g.task_claim_next(self.other)["claimed"], False)
        for n, expected in enumerate((first, second, third), start=1):
            claimed = self.g.task_claim_next(self.worker, lease_seconds=90)
            self.assertTrue(claimed["claimed"])
            task = claimed["task"]
            self.assertEqual(task["id"], expected)
            self.assertEqual(task["assignee"], self.worker.agent_id)
            self.assertEqual(task["state"], "running")
            self.assertEqual(task["attempts"], 1)
            self.assertEqual(task["input"]["data"]["key"], ("first", "second", "third")[n-1])
            self.assertIsInstance(task["lease_until"], str)
            stored = self.g.task_get(self.creator, expected)
            self.assertEqual(stored["lease_until"], task["lease_until"])
            self.assertEqual(stored["lease_started"], task["lease_started"])
        self.assertFalse(self.g.task_claim_next(self.worker)["claimed"])
        self.assertTrue(Gateway(self.db, self.secret).audit_verify(self.root)["valid"])
        with self.g.read_tx() as db:
            index_names = {row["name"] for row in db.execute("PRAGMA index_list(tasks)")}
        self.assertIn("idx_tasks_claim_next", index_names)

    def test_claim_requires_both_scopes_and_does_not_leak_input(self):
        tid = self.create("private")
        with self.assertRaises(GatewayError) as denied:
            self.g.task_claim_next(self.claim_only)
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        visible = {tool["name"] for tool in visible_tools(self.claim_only)}
        self.assertIn("task_claim", visible)
        self.assertNotIn("task_claim_next", visible)
        self.assertIn("task_claim_next", {x["name"] for x in visible_tools(self.worker)})
        self.assertEqual(self.g.task_get(self.creator, tid)["state"], "queued")
        with self.assertRaises(GatewayError):
            self.g.task_claim_next(self.other, lease_seconds=True)
        for bad in (0, 14, 3601, 3.0, "60", None):
            with self.subTest(bad=bad):
                with self.assertRaises(GatewayError):
                    self.g.task_claim_next(self.worker, lease_seconds=bad)
        self.assertEqual(self.g.task_get(self.creator, tid)["state"], "queued")

    def test_concurrent_workers_claim_each_task_exactly_once(self):
        tasks = [self.create("parallel-%02d" % n) for n in range(15)]
        gateways = [Gateway(self.db, self.secret) for _ in range(24)]
        def claim(gateway):
            return gateway.task_claim_next(self.worker)
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(claim, gateways))
        claimed = [x["task"]["id"] for x in outcomes if x["claimed"]]
        self.assertEqual(len(claimed), 15)
        self.assertEqual(set(claimed), set(tasks))
        self.assertEqual(len(claimed), len(set(claimed)))
        self.assertEqual(sum(not x["claimed"] for x in outcomes), 9)
        with self.g.read_tx() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM tasks WHERE state='running'").fetchone()[0], 15
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM tasks WHERE attempts!=1").fetchone()[0], 0
            )
        self.assertTrue(self.g.audit_verify(self.root)["valid"])

    def test_claim_cancel_race_never_double_commits(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            for i in range(10):
                task_id = self.create("cancel-race-%02d" % i)
                barrier = threading.Barrier(2)
                def claim():
                    barrier.wait(timeout=5)
                    return self.g.task_claim_next(self.worker)
                def cancel():
                    barrier.wait(timeout=5)
                    try:
                        return self.g.task_cancel(self.creator, task_id)
                    except GatewayError as error:
                        return {"error": error.code}
                claimed_f = pool.submit(claim)
                cancel_f = pool.submit(cancel)
                claim_result = claimed_f.result(timeout=12)
                cancel_result = cancel_f.result(timeout=12)
                persisted = self.g.task_get(self.creator, task_id)
                if persisted["state"] == "running":
                    self.assertTrue(claim_result["claimed"])
                    self.assertEqual(claim_result["task"]["id"], task_id)
                    self.assertEqual(cancel_result["error"], "CONFLICT")
                else:
                    self.assertEqual(persisted["state"], "canceled")
                    self.assertFalse(claim_result["claimed"])
                    self.assertEqual(cancel_result["state"], "canceled")
        self.assertTrue(self.g.audit_verify(self.root)["valid"])

    def test_empty_poll_never_reclaims_running_or_blocked_work(self):
        tid = self.create("no-reclaim")
        self.assertTrue(self.g.task_claim_next(self.worker)["claimed"])
        # A claimed task is not silently returned again, even after restart.
        restarted = Gateway(self.db, self.secret)
        self.assertFalse(restarted.task_claim_next(self.worker)["claimed"])
        with self.g.tx() as db:
            db.execute("UPDATE tasks SET state='blocked' WHERE id=?", (tid,))
        self.assertFalse(restarted.task_claim_next(self.worker)["claimed"])


class ClaimNextWireTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.secret = secrets.token_urlsafe(48)
        self.g = Gateway(str(Path(self.tmp.name) / "wire.sqlite"), self.secret)
        root = self.g.authenticate(self.secret)
        creator = self.g.register(root, "creator-http", "tests", [], ["task:create", "task:read"])
        worker = self.g.register(root, "worker-http", "tests", [], ["task:read", "task:claim"])
        restricted = self.g.register(root, "claim-only-http", "tests", [], ["task:claim"])
        self.creator = self.g.authenticate(creator["token"])
        self.worker = self.g.authenticate(worker["token"])
        self.worker_token = worker["token"]
        self.restricted_token = restricted["token"]
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.g, set()))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request(self, path, data, token=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=6)
        try:
            h = {"Content-Type": "application/json", "Authorization": "Bearer " + (token or self.worker_token)}
            h.update(headers or {})
            c.request("POST", path, body=json.dumps(data), headers=h)
            response = c.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            c.close()

    def test_rest_legacy_and_modern_share_claim_contract(self):
        a = self.g.task_create(self.creator, self.worker.agent_id, {"action": "health"}, "wire-a")
        b = self.g.task_create(self.creator, self.worker.agent_id, {"action": "echo", "data": 1}, "wire-b")
        status, rest = self.request("/v1/tools/task_claim_next", {"lease_seconds": 60})
        self.assertEqual(status, 200, rest)
        self.assertTrue(rest["ok"])
        self.assertEqual(rest["result"]["task"]["id"], a["task_id"])
        packet = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                  "params": {"name": "task_claim_next", "arguments": {"lease_seconds": 60}}}
        status, legacy = self.request("/mcp", packet, headers={"MCP-Protocol-Version": "2025-11-25"})
        self.assertEqual(status, 200, legacy)
        self.assertFalse(legacy["result"]["isError"])
        self.assertEqual(legacy["result"]["structuredContent"]["task"]["id"], b["task_id"])
        modern_packet = {
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
                "name": "task_claim_next", "arguments": {},
            },
        }
        modern_headers = {"MCP-Protocol-Version": "2026-07-28",
                          "Mcp-Method": "tools/call", "Mcp-Name": "task_claim_next"}
        status, modern = self.request("/mcp", modern_packet, headers=modern_headers)
        self.assertEqual(status, 200, modern)
        self.assertFalse(modern["result"]["isError"])
        self.assertEqual(modern["result"]["structuredContent"],
                         {"claimed": False, "task": None})
        status, denied = self.request("/v1/tools/task_claim_next", {},
                                      token=self.restricted_token)
        self.assertEqual(status, 403, denied)
        self.assertEqual(denied["error"]["code"], "FORBIDDEN")

    def test_tool_discovery_hides_claim_next_without_read_scope(self):
        status, listed = self.request("/mcp", {"jsonrpc": "2.0", "id": 7,
                                             "method": "tools/list", "params": {}},
                                      token=self.restricted_token)
        self.assertEqual(status, 200)
        names = {item["name"] for item in listed["result"]["tools"]}
        self.assertNotIn("task_claim_next", names)
        self.assertIn("task_claim", names)


if __name__ == "__main__":
    unittest.main()
