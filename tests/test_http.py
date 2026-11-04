import http.client
from http.server import ThreadingHTTPServer
import json
import os
import tempfile
import threading
import unittest

from shards_mcp.core import Gateway
from shards_mcp.server import make_handler


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = "b" * 48
        self.gateway = Gateway(os.path.join(self.tmp.name, "db.sqlite"), self.token)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.gateway, set()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def req(self, method, path, body=None, token=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = "Bearer " + token
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        result = conn.getresponse()
        raw = result.read()
        status = result.status
        conn.close()
        return status, json.loads(raw) if raw else None

    def rpc(self, method, params=None):
        return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

    def test_health_and_auth(self):
        self.assertEqual(self.req("GET", "/health/live")[0], 200)
        self.assertEqual(self.req("GET", "/health/ready")[0], 200)
        self.assertEqual(self.req("POST", "/mcp", self.rpc("initialize"))[0], 401)
        self.assertEqual(self.req("POST", "/mcp", self.rpc("initialize"), self.token,
                                  {"Origin": "https://evil.example"})[0], 403)
        status, body = self.req("POST", "/mcp", self.rpc("initialize"), self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(self.req("GET", "/mcp")[0], 405)

    def test_tools_round_trip(self):
        status, listed = self.req("POST", "/mcp", self.rpc("tools/list"), self.token)
        self.assertEqual(status, 200)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertIn("message_send", names)
        call = self.rpc("tools/call", {"name": "agent_register",
                   "arguments": {"name": "worker", "provider": "test", "capabilities": [],
                                 "scopes": ["agent:heartbeat"]}})
        _, response = self.req("POST", "/mcp", call, self.token)
        self.assertFalse(response["result"]["isError"])
        cred = response["result"]["structuredContent"]["token"]
        _, check = self.req("POST", "/mcp", self.rpc("tools/call",
                            {"name": "agent_heartbeat", "arguments": {}}), cred)
        self.assertFalse(check["result"]["isError"])
        _, denied = self.req("POST", "/mcp", call, cred)
        self.assertTrue(denied["result"]["isError"])


    def test_rest_bridge_and_version_guard(self):
        status, data = self.req("POST", "/mcp", self.rpc("initialize"), self.token,
                                {"MCP-Protocol-Version": "malicious-version"})
        self.assertEqual(status, 400)
        status, available = self.req("GET", "/v1/tools", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("message_send", {x["name"] for x in available["tools"]})
        status, created = self.req("POST", "/v1/tools/agent_register",
                                   {"name": "rest-agent", "provider": "test", "capabilities": [],
                                    "scopes": ["agent:heartbeat"]}, self.token)
        self.assertEqual(status, 200)
        cred = created["result"]["token"]
        status, heartbeat = self.req("POST", "/v1/tools/agent_heartbeat", {}, cred)
        self.assertEqual(status, 200)
        self.assertTrue(heartbeat["ok"])
        status, rejected = self.req("POST", "/v1/tools/agent_register",
                                    {"name": "rogue", "provider": "test", "capabilities": [],
                                     "scopes": []}, cred)
        self.assertEqual(status, 403)
        self.assertEqual(rejected["error"]["code"], "FORBIDDEN")

    def test_reference_worker_end_to_end(self):
        from shards_mcp.worker import AgentClient, process_once, safe_operation
        base = "http://127.0.0.1:%d" % self.server.server_port
        status, created = self.req("POST", "/v1/tools/agent_register",
                                   {"name": "reference-worker", "provider": "local",
                                    "capabilities": ["sha256"],
                                    "scopes": ["agent:heartbeat", "task:read", "task:claim",
                                               "task:update", "checkpoint:write"]}, self.token)
        self.assertEqual(status, 200)
        worker = created["result"]
        status, task = self.req("POST", "/v1/tools/task_create",
                                {"assignee": worker["agent_id"],
                                 "payload": {"action": "sha256", "data": "abc"},
                                 "idempotency_key": "worker-1"}, self.token)
        self.assertEqual(status, 200)
        client = AgentClient(base, worker["token"])
        self.assertEqual(process_once(client), 1)
        status, result = self.req("POST", "/v1/tools/task_get",
                                  {"task_id": task["result"]["task_id"]}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["state"], "succeeded")
        self.assertIn("sha256", result["result"]["result"])
        self.assertEqual(process_once(client), 0)
        with self.assertRaises(ValueError):
            AgentClient("http://untrusted.example", worker["token"])
        with self.assertRaises(ValueError):
            safe_operation({"action": "shell", "command": "rm -rf /"})


if __name__ == "__main__":
    unittest.main()
