"""Real HTTP contract for the stateless MCP 2026-07-28 tool-server subset."""
from __future__ import annotations

import base64
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from shards_mcp.core import Gateway
from shards_mcp.mcp_modern import MODERN_VERSION, LEGACY_VERSION, SUPPORTED_VERSIONS
from shards_mcp.server import make_handler


class StatelessMcpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.secret = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(Path(self.tmp.name) / "mcp.sqlite"), self.secret)
        admin = self.gateway.authenticate(self.secret)
        registered = self.gateway.register(
            admin, "modern", "http", [], ["agent:read", "task:create", "task:read"],
        )
        self.token = registered["token"]
        self.agent_id = registered["agent_id"]
        worker = self.gateway.register(admin, "worker", "http", [], ["task:claim", "task:read"])
        self.worker_id = worker["agent_id"]
        self.http = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.gateway, set())
        )
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    @staticmethod
    def packet(method, params=None, request_id=1):
        values = dict(params or {})
        values.setdefault("_meta", {
            "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
            "io.modelcontextprotocol/clientInfo": {
                "name": "shards-modern-e2e", "version": "1.0.0",
            },
            "io.modelcontextprotocol/clientCapabilities": {},
        })
        return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": values}

    def request(self, packet, *, version=MODERN_VERSION, route=None,
                name=None, extra=(), token=None):
        payload = json.dumps(packet, separators=(",", ":"))
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=6)
        try:
            conn.putrequest("POST", "/mcp")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Accept", "application/json, text/event-stream")
            conn.putheader("Authorization", "Bearer " + (token or self.token))
            conn.putheader("Content-Length", str(len(payload.encode())))
            if version is not None:
                conn.putheader("MCP-Protocol-Version", version)
            if route is not None:
                conn.putheader("Mcp-Method", route)
            if name is not None:
                conn.putheader("Mcp-Name", name)
            for key, value in extra:
                conn.putheader(key, value)
            conn.endheaders(payload.encode())
            response = conn.getresponse()
            body = response.read()
            return response.status, json.loads(body) if body else None
        finally:
            conn.close()

    def test_discover_advertises_two_wire_eras_and_static_scoped_tools(self):
        status, response = self.request(
            self.packet("server/discover"), route="server/discover"
        )
        self.assertEqual(status, 200, response)
        outcome = response["result"]
        self.assertEqual(outcome["resultType"], "complete")
        self.assertEqual(outcome["supportedVersions"], list(SUPPORTED_VERSIONS))
        self.assertEqual(outcome["capabilities"]["tools"]["listChanged"], False)
        self.assertEqual(
            outcome["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "shards-mcp"
        )

    def test_tool_listing_identity_and_security_policy_are_preserved(self):
        status, listed = self.request(self.packet("tools/list"), route="tools/list")
        self.assertEqual(status, 200)
        self.assertEqual(listed["result"]["resultType"], "complete")
        names = {item["name"] for item in listed["result"]["tools"]}
        self.assertIn("agent_identity", names)
        self.assertIn("task_create", names)
        self.assertNotIn("system_status", names)
        self.assertNotIn("task_verify", names)

        status, called = self.request(
            self.packet("tools/call", {"name": "agent_identity", "arguments": {}}),
            route="tools/call", name="agent_identity",
        )
        self.assertEqual(status, 200, called)
        self.assertEqual(called["result"]["resultType"], "complete")
        self.assertEqual(called["result"]["structuredContent"]["agent_id"], self.agent_id)
        self.assertEqual(called["result"]["structuredContent"]["role"], "agent")
        self.assertNotIn(self.token, json.dumps(called))

        denied = self.request(
            self.packet("tools/call", {"name": "system_status", "arguments": {}}),
            route="tools/call", name="system_status",
        )[1]
        self.assertTrue(denied["result"]["isError"])
        self.assertNotIn("agents", denied["result"].get("structuredContent", {}))

    def test_valid_ascii_and_canonical_base64_mcp_name_headers(self):
        encoded = "=?base64?" + base64.b64encode(b"agent_identity").decode() + "?="
        for name in ("agent_identity", encoded):
            with self.subTest(name=name):
                code, value = self.request(
                    self.packet("tools/call", {"name": "agent_identity"}),
                    route="tools/call", name=name,
                )
                self.assertEqual(code, 200, value)
                self.assertFalse(value["result"]["isError"])
        rejected = self.request(
            self.packet("tools/call", {"name": "agent_identity"}),
            route="tools/call", name="=?base64?%%%%?=",
        )
        self.assertEqual(rejected[0], 400)
        self.assertEqual(rejected[1]["error"]["code"], -32020)

    def test_header_routing_mismatch_never_performs_write(self):
        packet = self.packet("tools/call", {
            "name": "task_create",
            "arguments": {
                "assignee": self.worker_id,
                "payload": {"action": "health"},
                "idempotency_key": "modern-header-denied",
            },
        })
        variants = (
            {"route": "tools/list", "name": "task_create"},
            {"route": "tools/call", "name": "system_status"},
            {"route": "tools/call", "name": None},
            {"route": None, "name": "task_create"},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                code, value = self.request(packet, **variant)
                self.assertEqual(code, 400, value)
                self.assertEqual(value["error"]["code"], -32020)
        for extras in (
            [("Mcp-Method", "tools/call")],
            [("Mcp-Name", "task_create")],
            [("Mcp-Param-Agent", "untrusted")],
        ):
            with self.subTest(headers=extras):
                code, value = self.request(
                    packet, route="tools/call", name="task_create", extra=extras
                )
                self.assertEqual(code, 400, value)
                self.assertEqual(value["error"]["code"], -32020)
        with self.gateway.read_tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_stateless_requests_validate_metadata_per_call(self):
        no_meta = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        bad_cap = self.packet("tools/list")
        bad_cap["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"] = "all"
        for packet in (no_meta, bad_cap):
            code, data = self.request(packet, route="tools/list")
            self.assertEqual(code, 400, data)
            self.assertEqual(data["error"]["code"], -32602)
        mismatch = self.packet("tools/list")
        mismatch["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "1900-01-01"
        code, data = self.request(mismatch, route="tools/list")
        self.assertEqual(code, 400)
        self.assertEqual(data["error"]["code"], -32020)
        self.assertNotIn("data", data["error"])

    def test_modern_and_legacy_clients_share_durable_task_state(self):
        create = self.packet("tools/call", {
            "name": "task_create",
            "arguments": {
                "assignee": self.worker_id,
                "payload": {"action": "health"},
                "idempotency_key": "modern-shared-task-e2e",
            },
        })
        code, created = self.request(
            create, route="tools/call", name="task_create"
        )
        self.assertEqual(code, 200, created)
        self.assertFalse(created["result"]["isError"])
        task_id = created["result"]["structuredContent"]["task_id"]
        again = self.request(create, route="tools/call", name="task_create")[1]
        self.assertEqual(again["result"]["structuredContent"]["task_id"], task_id)
        legacy = {
            "jsonrpc": "2.0", "id": 22, "method": "tools/call",
            "params": {"name": "task_get", "arguments": {"task_id": task_id}},
        }
        code, readback = self.request(legacy, version=LEGACY_VERSION)
        self.assertEqual(code, 200, readback)
        self.assertEqual(readback["result"]["structuredContent"]["id"], task_id)
        self.assertEqual(readback["result"]["structuredContent"]["state"], "queued")
        with self.gateway.read_tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)

    def test_old_handshake_works_and_removed_modern_methods_are_absent(self):
        old = {"jsonrpc": "2.0", "id": 11, "method": "initialize",
               "params": {"protocolVersion": LEGACY_VERSION,
                          "capabilities": {},
                          "clientInfo": {"name": "old", "version": "1"}}}
        status, response = self.request(old, version=LEGACY_VERSION)
        self.assertEqual(status, 200)
        self.assertEqual(response["result"]["protocolVersion"], LEGACY_VERSION)
        self.assertNotIn("resultType", response["result"])
        for method in ("initialize", "ping", "notifications/initialized"):
            code, data = self.request(self.packet(method), route=method)
            self.assertEqual(code, 404, data)
            self.assertEqual(data["error"]["code"], -32601)

    def test_modern_version_header_is_required_to_match_body(self):
        code, data = self.request(
            self.packet("tools/list"), route="tools/list", version="1900-01-01"
        )
        self.assertEqual(code, 400)
        self.assertEqual(data["error"]["code"], -32022)
        self.assertEqual(data["error"]["data"]["requested"], "1900-01-01")
        code, data = self.request(
            self.packet("tools/list"), route="tools/list", version=None
        )
        self.assertEqual(code, 400)
        self.assertEqual(data["error"]["code"], -32020)


if __name__ == "__main__":
    unittest.main()
