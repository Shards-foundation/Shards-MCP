"""A2A v1.0 constrained JSON-RPC delegation: authentic agents, durable tasks and polling."""
from http.server import ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from shards_mcp.a2a import A2AAdapter
from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import make_handler


class A2ATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.admin_token = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(Path(self.tmp.name) / "a2a.sqlite"), self.admin_token)
        self.root = self.gateway.authenticate(self.admin_token)
        self.sender = self.gateway.register(self.root, "sender", "test", [],
                                            ["agent:read", "task:create", "task:read"])
        self.worker = self.gateway.register(self.root, "worker", "test", ["a2a/1.0"],
                                            ["agent:read", "task:read", "task:claim", "task:update"])
        self.reviewer = self.gateway.register(self.root, "reviewer", "test", [],
                                              ["task:verify"])
        self.outsider = self.gateway.register(self.root, "outsider", "test", [],
                                              ["agent:read", "task:read"])
        self.a2a = A2AAdapter(self.gateway, "http://127.0.0.1:8787")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0),
                                       make_handler(self.gateway, set(), a2a=self.a2a))
        self.worker_thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.worker_thread.start()
        self.path = "/a2a/agents/" + self.worker["agent_id"]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.worker_thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, method: str, path: str, token: str | None = None,
                data=None, version: str | None = "1.0"):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port, timeout=5)
        h = {"Content-Type": "application/json"}
        if version is not None:
            h["A2A-Version"] = version
        if token:
            h["Authorization"] = "Bearer " + token
        c.request(method, path, json.dumps(data) if data is not None else None, headers=h)
        res = c.getresponse()
        status = res.status
        payload = res.read()
        c.close()
        return status, json.loads(payload) if payload else None

    @staticmethod
    def rpc(method: str, params: dict, id=1):
        return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}

    @staticmethod
    def message(message_id: str, text: str):
        return {"message": {"messageId": message_id,
                            "role": "ROLE_USER", "parts": [{"text": text}]}}

    def test_agent_card_is_authenticated_and_v1_accurate(self):
        status, data = self.request("GET", self.path + "/card", self.sender["token"])
        self.assertEqual(status, 200)
        self.assertEqual(data["name"], "worker")
        self.assertEqual(data["supportedInterfaces"][0]["protocolVersion"], "1.0")
        self.assertEqual(data["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")
        self.assertEqual(data["supportedInterfaces"][0]["url"],
                         "http://127.0.0.1:8787" + self.path)
        self.assertFalse(data["capabilities"]["streaming"])
        self.assertFalse(data["capabilities"]["pushNotifications"])
        self.assertIn("bearer", data["securitySchemes"])
        self.assertNotIn("token", json.dumps(data).lower())
        self.assertEqual(self.request("GET", self.path + "/card")[0], 401)
        self.assertEqual(self.request("GET", "/a2a/agents/invalid/card", self.sender["token"])[0], 404)

    def test_send_poll_and_verified_artifact_roundtrip(self):
        sent = self.rpc("SendMessage", self.message("mid-1", "Please run a task"))
        code, initial = self.request("POST", self.path, self.sender["token"], sent)
        self.assertEqual(code, 200)
        task = initial["result"]["task"]
        task_id = task["id"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_SUBMITTED")
        self.assertEqual(task["contextId"], task_id)
        duplicate = self.request("POST", self.path, self.sender["token"], sent)[1]
        self.assertEqual(duplicate["result"]["task"]["id"], task_id)

        raw = self.gateway.task_get(self.gateway.authenticate(self.sender["token"]), task_id)
        self.assertEqual(raw["assignee"], self.worker["agent_id"])
        self.assertEqual(raw["input"]["protocol"], "a2a/1.0")
        self.assertEqual(raw["input"]["message"]["messageId"], "mid-1")

        worker_actor = self.gateway.authenticate(self.worker["token"])
        self.gateway.task_claim(worker_actor, task_id)
        self.gateway.task_complete(worker_actor, task_id, True, {"result": "done"})
        code, pending = self.request("POST", self.path, self.sender["token"],
                                     self.rpc("GetTask", {"id": task_id}, 2))
        self.assertEqual(code, 200)
        self.assertEqual(pending["result"]["status"]["state"], "TASK_STATE_WORKING")
        self.assertNotIn("artifacts", pending["result"])

        reviewer = self.gateway.authenticate(self.reviewer["token"])
        self.gateway.task_verify(reviewer, task_id, True, {"summary": "validated deterministic task result"})
        done = self.request("POST", self.path, self.sender["token"],
                            self.rpc("GetTask", {"id": task_id}, 3))[1]["result"]
        self.assertEqual(done["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(done["artifacts"][0]["parts"][0]["data"], {"result": "done"})
        no_access = self.request("POST", self.path, self.outsider["token"],
                                  self.rpc("GetTask", {"id": task_id}))
        self.assertEqual(no_access[1]["error"]["code"], -32001)

    def test_separate_process_reference_worker_completes_a2a_message(self):
        import os
        import subprocess
        import sys
        worker = self.gateway.register(self.root, "a2a-reference-process", "test",
                                       ["a2a/1.0"], ["agent:heartbeat", "task:read",
                                       "task:claim", "task:update", "checkpoint:write"])
        endpoint = "/a2a/agents/" + worker["agent_id"]
        message = self.rpc("SendMessage", self.message("process-1", "Hello from A2A"))
        status, created = self.request("POST", endpoint, self.sender["token"], message)
        self.assertEqual(status, 200)
        task_id = created["result"]["task"]["id"]

        env = {**os.environ, "SHARDS_GATEWAY_URL": "http://127.0.0.1:%d" % self.srv.server_port,
               "SHARDS_AGENT_TOKEN": worker["token"]}
        env.pop("SHARDS_ADMIN_TOKEN", None)
        child = subprocess.run([sys.executable, "-m", "shards_mcp.worker", "--once"],
                               capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertNotIn(worker["token"], child.stdout + child.stderr)
        reported = self.request("POST", endpoint, self.sender["token"],
                                self.rpc("GetTask", {"id": task_id}))[1]["result"]
        self.assertEqual(reported["status"]["state"], "TASK_STATE_WORKING")
        self.assertNotIn("artifacts", reported)

        reviewer = self.gateway.authenticate(self.reviewer["token"])
        self.gateway.task_verify(reviewer, task_id, True,
                                 {"summary": "A2A deterministic echo output matched input"})
        complete = self.request("POST", endpoint, self.sender["token"],
                                self.rpc("GetTask", {"id": task_id}))[1]["result"]
        self.assertEqual(complete["status"]["state"], "TASK_STATE_COMPLETED")
        result = complete["artifacts"][0]["parts"][0]["data"]
        self.assertEqual(result, {"text": "Hello from A2A", "worker": "deterministic-echo"})

    def test_explicit_version_and_unsupported_feature_rejection(self):
        send = self.rpc("SendMessage", self.message("mid-2", "hello"))
        self.assertEqual(self.request("POST", self.path, self.sender["token"], send,
                                      version=None)[0], 400)
        self.assertEqual(self.request("POST", self.path, self.sender["token"], send,
                                      version="0.3")[0], 400)
        for method in ("SendStreamingMessage", "CancelTask", "ListTasks"):
            result = self.request("POST", self.path, self.sender["token"],
                                  self.rpc(method, {}))[1]
            self.assertEqual(result["error"]["code"], -32601)
        self.assertEqual(self.request("POST", self.path, data=send)[0], 401)

    def test_bad_inputs_and_permissions_do_not_create_tasks(self):
        invalid = [
            {"message": {"messageId": "x", "role": "user", "parts": [{"text": "hello"}]}},
            {"message": {"messageId": "x", "role": "ROLE_USER", "parts": [{"kind": "text", "text": "hello"}]}},
            {"message": {"messageId": "x", "role": "ROLE_USER", "parts": [{"text": " " }]}},
            {"message": {"messageId": "x", "role": "ROLE_USER", "parts": [{"data": {"x": 1}}]}},
            {"message": {"messageId": "x", "role": "ROLE_USER", "taskId": "t", "parts": [{"text": "hello"}]}},
        ]
        for params in invalid:
            result = self.request("POST", self.path, self.sender["token"],
                                  self.rpc("SendMessage", params))[1]
            self.assertEqual(result["error"]["code"], -32602)
        self.assertEqual(self.request("POST", self.path, self.outsider["token"],
                                      self.rpc("SendMessage", self.message("x", "hello")))[1]
                         ["error"]["code"], -32003)
        with self.gateway.read_tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_agent_revocation_prevents_new_task_submission(self):
        self.gateway.revoke(self.root, self.worker["agent_id"])
        result = self.request("POST", self.path, self.sender["token"],
                              self.rpc("SendMessage", self.message("mid-3", "hello")))[1]
        self.assertIn("error", result)
        self.assertEqual(self.request("GET", self.path + "/card", self.sender["token"])[0], 404)


if __name__ == "__main__":
    unittest.main()
