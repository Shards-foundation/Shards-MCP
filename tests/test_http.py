import secrets
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
        self.token = secrets.token_urlsafe(48)
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
        self.assertNotIn("agent_register", names)
        self.assertNotIn("agent_revoke", names)
        worker = self.gateway.register(self.gateway.authenticate(self.token), "worker", "test", [],
                                       ["agent:heartbeat"])
        cred = worker["token"]
        _, check = self.req("POST", "/mcp", self.rpc("tools/call",
                            {"name": "agent_heartbeat", "arguments": {}}), cred)
        self.assertFalse(check["result"]["isError"])
        _, denied = self.req("POST", "/mcp", self.rpc("tools/call",
                             {"name": "agent_register", "arguments": {}}), self.token)
        self.assertEqual(denied["error"]["code"], -32602)


    def test_rest_bridge_and_version_guard(self):
        # Modern clients no longer use initialize; omitting the mandatory
        # per-request metadata must fail instead of negotiating implicitly.
        status, data = self.req("POST", "/mcp", self.rpc("initialize"), self.token,
                                {"MCP-Protocol-Version": "2026-07-28"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], -32602)
        status, data = self.req("POST", "/mcp", self.rpc("initialize"), self.token,
                                {"MCP-Protocol-Version": "2025-11-25"})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["protocolVersion"], "2025-11-25")
        status, available = self.req("GET", "/v1/tools", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("message_send", {x["name"] for x in available["tools"]})
        worker = self.gateway.register(self.gateway.authenticate(self.token), "rest-agent", "test", [],
                                       ["agent:heartbeat"])
        cred = worker["token"]
        status, heartbeat = self.req("POST", "/v1/tools/agent_heartbeat", {}, cred)
        self.assertEqual(status, 200)
        self.assertTrue(heartbeat["ok"])
        status, rejected = self.req("POST", "/v1/tools/agent_register",
                                    {"name": "rogue", "provider": "test", "capabilities": [],
                                     "scopes": []}, cred)
        self.assertEqual(status, 404)
        self.assertEqual(rejected["error"]["code"], "NOT_FOUND")

    def test_reference_worker_end_to_end(self):
        from shards_mcp.worker import AgentClient, process_once, safe_operation
        base = "http://127.0.0.1:%d" % self.server.server_port
        worker = self.gateway.register(self.gateway.authenticate(self.token), "reference-worker",
                                       "local", ["sha256"], ["agent:heartbeat", "task:read",
                                       "task:claim", "task:update", "checkpoint:write"])
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
        self.assertEqual(result["result"]["state"], "reported")
        self.assertIn("sha256", result["result"]["result"])
        reviewer = self.gateway.register(self.gateway.authenticate(self.token), "independent-reviewer",
                                         "local", ["review"], ["task:verify", "task:read"])
        status, verified = self.req("POST", "/v1/tools/task_verify",
                                    {"task_id": task["result"]["task_id"], "approved": True,
                                     "evidence": {"sha256": result["result"]["result"]["sha256"]}}, reviewer["token"])
        self.assertEqual(status, 200)
        self.assertEqual(verified["result"]["state"], "succeeded")
        self.assertEqual(process_once(client), 0)
        with self.assertRaises(ValueError):
            AgentClient("http://untrusted.example", worker["token"])
        with self.assertRaises(ValueError):
            safe_operation({"action": "shell", "command": "rm -rf /"})



    def test_worker_runs_in_separate_process(self):
        import subprocess
        import sys
        worker = self.gateway.register(self.gateway.authenticate(self.token), "external-process",
                                       "local", ["echo"], ["agent:heartbeat", "task:read",
                                       "task:claim", "task:update", "checkpoint:write"])
        created = self.gateway.task_create(self.gateway.authenticate(self.token), worker["agent_id"],
                                           {"action": "echo", "data": {"value": "separate-runtime"}},
                                           "subprocess-worker")
        env = {**os.environ, "SHARDS_GATEWAY_URL": "http://127.0.0.1:%d" % self.server.server_port,
               "SHARDS_AGENT_TOKEN": worker["token"]}
        env.pop("SHARDS_ADMIN_TOKEN", None)
        child = subprocess.run([sys.executable, "-m", "shards_mcp.worker", "--once"],
                               capture_output=True, text=True, env=env, timeout=12)
        self.assertEqual(child.returncode, 0, child.stderr)
        state = self.gateway.task_get(self.gateway.authenticate(self.token), created["task_id"])
        self.assertEqual(state["state"], "reported")
        self.assertEqual(state["result"], {"echo": {"value": "separate-runtime"}})
        self.assertNotIn(worker["token"], child.stdout + child.stderr)

    def test_stdio_bridge_roundtrip(self):
        import subprocess
        import sys
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "shards-stdio-test", "version": "1.0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "system_status", "arguments": {}}},
        ]
        env = {**os.environ, "SHARDS_GATEWAY_URL": "http://127.0.0.1:%d" % self.server.server_port,
               "SHARDS_AGENT_TOKEN": self.token}
        proc = subprocess.run([sys.executable, "-m", "shards_mcp.stdio"],
                              input="".join(json.dumps(req) + "\n" for req in requests),
                              capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 3, proc.stdout)
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "shards-mcp")
        self.assertNotIn("agent_register", {entry["name"] for entry in responses[1]["result"]["tools"]})
        self.assertIn("agent_list", {entry["name"] for entry in responses[1]["result"]["tools"]})
        self.assertEqual(responses[2]["result"]["structuredContent"]["agents"], 0)


if __name__ == "__main__":
    unittest.main()
