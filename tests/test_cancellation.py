"""Fail-closed queued-task cancellation across clients and worker claim races.

Cancellation is not an execution kill-switch. A claimed task is deliberately
not cancellable because worker side effects may already have occurred.
"""
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

from shards_mcp.a2a import A2AAdapter
from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import TOOL_LIST, make_handler


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "cancel.sqlite")
        self.secret = secrets.token_urlsafe(48)
        self.gateway = Gateway(self.path, self.secret)
        self.root = self.gateway.authenticate(self.secret)
        self.creator_entry = self.gateway.register(
            self.root, "creator", "test", [],
            ["task:create", "task:read", "task:cancel"],
        )
        self.worker_entry = self.gateway.register(
            self.root, "worker", "test", [],
            ["task:read", "task:claim", "task:update"],
        )
        self.other_entry = self.gateway.register(
            self.root, "other", "test", [],
            ["task:create", "task:read", "task:cancel"],
        )
        self.creator = self.gateway.authenticate(self.creator_entry["token"])
        self.worker = self.gateway.authenticate(self.worker_entry["token"])
        self.other = self.gateway.authenticate(self.other_entry["token"])

    def tearDown(self):
        self.temp.cleanup()

    def new_task(self, key):
        return self.gateway.task_create(
            self.creator, self.worker.agent_id, {"action": "health"}, key
        )["task_id"]

    def test_cancel_is_durable_idempotent_and_not_claimable(self):
        task_id = self.new_task("cancel-one")
        audit_before = self.gateway.audit_verify(self.root)["count"]
        first = self.gateway.task_cancel(self.creator, task_id)
        self.assertEqual(first, {
            "task_id": task_id, "state": "canceled", "already_canceled": False,
        })
        self.assertEqual(
            self.gateway.task_cancel(self.creator, task_id)["already_canceled"], True
        )
        self.assertEqual(
            self.gateway.audit_verify(self.root)["count"], audit_before + 1,
            "retries must not add duplicate cancellation audit events",
        )
        self.assertEqual(
            self.gateway.task_create(
                self.creator, self.worker.agent_id, {"action": "health"}, "cancel-one"
            )["state"], "canceled",
        )
        with self.assertRaises(GatewayError) as claimed:
            self.gateway.task_claim(self.worker, task_id)
        self.assertEqual(claimed.exception.code, "CONFLICT")
        self.assertFalse(self.gateway.task_inbox(self.worker, state="queued"))
        self.assertEqual(
            [x["id"] for x in self.gateway.task_inbox(self.worker, state="canceled")],
            [task_id],
        )
        reopened = Gateway(self.path, self.secret)
        self.assertEqual(
            reopened.task_get(self.creator, task_id)["state"], "canceled"
        )
        self.assertTrue(reopened.audit_verify(self.root)["valid"])

    def test_cancellation_requires_creator_or_operator_and_explicit_scope(self):
        tid = self.new_task("rights")
        with self.assertRaises(GatewayError) as denied:
            self.gateway.task_cancel(self.other, tid)
        self.assertEqual(denied.exception.code, "NOT_FOUND")
        with self.assertRaises(GatewayError) as denied:
            self.gateway.task_cancel(self.worker, tid)
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        with self.assertRaises(GatewayError):
            self.gateway.task_cancel(self.creator, "tsk_does-not-exist")
        self.assertEqual(
            self.gateway.task_cancel(self.root, tid)["state"], "canceled"
        )

    def test_claimed_reported_failed_and_succeeded_tasks_cannot_be_cancelled(self):
        running = self.new_task("claimed")
        self.gateway.task_claim(self.worker, running)
        with self.assertRaises(GatewayError) as denied:
            self.gateway.task_cancel(self.creator, running)
        self.assertEqual(denied.exception.code, "CONFLICT")
        self.assertEqual(
            self.gateway.task_complete(self.worker, running, True, {"done": True})["state"],
            "reported",
        )
        with self.assertRaises(GatewayError):
            self.gateway.task_cancel(self.root, running)
        failed = self.new_task("failed")
        self.gateway.task_claim(self.worker, failed)
        self.gateway.task_complete(self.worker, failed, False, {"error": "expected"})
        with self.assertRaises(GatewayError):
            self.gateway.task_cancel(self.creator, failed)
        self.assertEqual(self.gateway.task_get(self.creator, failed)["state"], "failed")

        reviewer = self.gateway.register(
            self.root, "reviewer", "test", [], ["task:verify"]
        )
        self.gateway.task_verify(
            self.gateway.authenticate(reviewer["token"]), running, True,
            {"case": "independent validation passed"},
        )
        with self.assertRaises(GatewayError):
            self.gateway.task_cancel(self.creator, running)
        self.assertEqual(self.gateway.task_get(self.root, running)["state"], "succeeded")

    def test_racing_claim_and_cancel_admit_exactly_one_winner(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            for index in range(16):
                tid = self.new_task("race-%d" % index)
                barrier = threading.Barrier(2)
                def cancel():
                    barrier.wait(timeout=5)
                    try:
                        return ("cancel", self.gateway.task_cancel(self.creator, tid)["state"])
                    except GatewayError as error:
                        return ("cancel", error.code)
                def claim():
                    barrier.wait(timeout=5)
                    try:
                        return ("claim", self.gateway.task_claim(self.worker, tid)["state"])
                    except GatewayError as error:
                        return ("claim", error.code)
                left = pool.submit(cancel)
                right = pool.submit(claim)
                outcomes = dict([left.result(timeout=12), right.result(timeout=12)])
                state = self.gateway.task_get(self.root, tid)["state"]
                self.assertIn(state, ("running", "canceled"))
                if state == "running":
                    self.assertEqual(outcomes, {"cancel": "CONFLICT", "claim": "running"})
                else:
                    self.assertEqual(outcomes, {"cancel": "canceled", "claim": "CONFLICT"})
        self.assertTrue(self.gateway.audit_verify(self.root)["valid"])
        with self.gateway.read_tx() as db:
            duplicated = db.execute("""
                SELECT subject FROM audit
                 WHERE action IN ('task.claim','task.cancel')
                 GROUP BY subject HAVING COUNT(*) > 1
            """).fetchall()
        self.assertEqual(duplicated, [], "task must never be both claimed and cancelled")


class CancellationHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(Path(self.temp.name) / "http.sqlite"), self.secret)
        root = self.gateway.authenticate(self.secret)
        self.sender = self.gateway.register(
            root, "sender", "test", [], ["task:create", "task:read", "task:cancel"],
        )
        self.worker = self.gateway.register(
            root, "worker", "test", [], ["task:read", "task:claim"],
        )
        self.a2a = A2AAdapter(self.gateway, "http://127.0.0.1:8787")
        self.http = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.gateway, set(), a2a=self.a2a)
        )
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.path = "/a2a/agents/" + self.worker["agent_id"]

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, token, path, payload):
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.http.server_port, timeout=6
        )
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                   "A2A-Version": "1.0"}
        try:
            conn.request("POST", path, body=json.dumps(payload), headers=headers)
            res = conn.getresponse()
            raw = res.read()
            return res.status, json.loads(raw) if raw else None
        finally:
            conn.close()

    def rpc(self, method, params=None):
        return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

    def test_a2a_cancelled_task_and_standard_conflict_error(self):
        send = self.rpc("SendMessage", {"message": {
            "messageId": "cancel-a2a-1", "role": "ROLE_USER",
            "parts": [{"text": "do not run this"}],
        }})
        status, initial = self.request(self.sender["token"], self.path, send)
        self.assertEqual(status, 200)
        task_id = initial["result"]["task"]["id"]
        status, cancelled = self.request(
            self.sender["token"], self.path, self.rpc("CancelTask", {"id": task_id})
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            cancelled["result"]["status"]["state"], "TASK_STATE_CANCELED"
        )
        polled = self.request(
            self.sender["token"], self.path, self.rpc("GetTask", {"id": task_id})
        )[1]
        self.assertEqual(polled["result"]["status"]["state"], "TASK_STATE_CANCELED")
        repeat = self.request(
            self.sender["token"], self.path, self.rpc("CancelTask", {"id": task_id})
        )[1]
        self.assertEqual(repeat["error"]["code"], -32002)
        self.assertEqual(
            self.gateway.task_inbox(
                self.gateway.authenticate(self.worker["token"]), state="queued"
            ), []
        )

    def test_a2a_rejects_wrong_agent_target_and_claimed_task(self):
        created = self.gateway.task_create(
            self.gateway.authenticate(self.sender["token"]),
            self.worker["agent_id"], {"action": "health"}, "claimed-a2a"
        )["task_id"]
        self.gateway.task_claim(self.gateway.authenticate(self.worker["token"]), created)
        resp = self.request(
            self.sender["token"], self.path, self.rpc("CancelTask", {"id": created})
        )[1]
        self.assertEqual(resp["error"]["code"], -32002)
        self.assertEqual(
            self.gateway.task_get(self.gateway.authenticate(self.sender["token"]), created)["state"],
            "running"
        )
        wrong = self.request(
            self.sender["token"], "/a2a/agents/" + self.sender["agent_id"],
            self.rpc("CancelTask", {"id": created})
        )[1]
        self.assertEqual(wrong["error"]["code"], -32001)

    def test_mcp_and_rest_cancel_tool_scoped_exposure(self):
        listed = self.request(self.sender["token"], "/mcp", self.rpc("tools/list"))[1]
        tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
        self.assertIn("task_cancel", tools)
        self.assertTrue(tools["task_cancel"]["annotations"]["destructiveHint"])
        self.assertNotIn(
            "task_cancel", {t["name"] for t in
                            self.request(self.worker["token"], "/mcp",
                                         self.rpc("tools/list"))[1]["result"]["tools"]}
        )
        task = self.gateway.task_create(
            self.gateway.authenticate(self.sender["token"]),
            self.worker["agent_id"], {"action": "health"}, "mcp-cancel"
        )["task_id"]
        params = {"name": "task_cancel", "arguments": {"task_id": task}}
        rpc_result = self.request(
            self.sender["token"], "/mcp", self.rpc("tools/call", params)
        )[1]
        self.assertFalse(rpc_result["result"]["isError"])
        self.assertEqual(
            rpc_result["result"]["structuredContent"]["state"], "canceled"
        )
        rest = self.request(
            self.sender["token"], "/v1/tools/task_cancel", {"task_id": task}
        )[1]
        self.assertTrue(rest["ok"])
        self.assertTrue(rest["result"]["already_canceled"])
        attempted = self.request(
            self.worker["token"], "/mcp", self.rpc("tools/call", params)
        )[1]
        self.assertTrue(attempted["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
