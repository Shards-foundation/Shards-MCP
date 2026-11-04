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


if __name__ == "__main__":
    unittest.main()
