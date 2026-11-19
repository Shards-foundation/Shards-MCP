"""Black-box interoperability: separate MCP, stdio and worker clients over HTTP.

The test never executes arbitrary commands as an agent tool and keeps credentials
out of logs. It verifies durable state across a gateway restart.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest

from shards_mcp.core import Gateway
from shards_mcp.server import BoundedHTTPServer, make_handler


class GatewayInteropE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "gateway.sqlite")
        self.secret = secrets.token_urlsafe(48)
        self.gateway = Gateway(self.path, self.secret)
        admin = self.gateway.authenticate(self.secret)
        self.creator = self.gateway.register(
            admin, "creator", "mcp-client", ["task-submission"],
            ["agent:read", "message:send", "message:read", "task:create",
             "task:read", "task:verify", "event:write", "event:read"],
        )
        self.worker = self.gateway.register(
            admin, "worker", "stdio-worker", ["echo"],
            ["agent:heartbeat", "message:read", "task:read",
             "task:claim", "task:update", "checkpoint:write"],
        )
        self.verifier = self.gateway.register(
            admin, "verifier", "independent-reviewer", ["verification"],
            ["task:verify", "task:read"],
        )
        self.observer = self.gateway.register(
            admin, "observer", "read-only-client", [],
            ["agent:heartbeat"],
        )
        self.gateway.delegation_grant(admin, self.creator["agent_id"], self.worker["agent_id"])
        self.start_server()

    def start_server(self):
        self.http = BoundedHTTPServer(
            ("127.0.0.1", 0), make_handler(self.gateway, set())
        )
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "server thread failed to stop")

    def tearDown(self):
        try:
            self.stop_server()
        finally:
            self.temp.cleanup()

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.http.server_port

    def request(self, token, method, path, data=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=8)
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-11-25",
        }
        try:
            conn.request(method, path,
                         body=json.dumps(data, separators=(",", ":")) if data is not None else None,
                         headers=headers)
            response = conn.getresponse()
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
        finally:
            conn.close()

    def rpc(self, token, method, params=None, identifier=1):
        status, value = self.request(
            token, "POST", "/mcp",
            {"jsonrpc": "2.0", "id": identifier,
             "method": method, "params": params or {}},
        )
        self.assertEqual(status, 200, value)
        self.assertEqual(value["jsonrpc"], "2.0")
        self.assertEqual(value["id"], identifier)
        return value

    def tool(self, token, name, args=None):
        response = self.rpc(token, "tools/call",
                            {"name": name, "arguments": args or {}})
        self.assertNotIn("error", response, response)
        return response["result"]

    def assert_ok(self, token, name, args=None):
        result = self.tool(token, name, args)
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]

    def test_verified_task_message_event_and_persistence_after_restart(self):
        created = self.creator["token"]
        worker = self.worker["token"]
        verifier = self.verifier["token"]
        admin = self.secret

        negotiated = self.rpc(created, "initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "e2e-mcp", "version": "1.0"},
        })
        self.assertEqual(negotiated["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(self.rpc(created, "ping")["result"], {})

        identity = self.assert_ok(created, "agent_identity")
        self.assertEqual(identity["agent_id"], self.creator["agent_id"])
        self.assertEqual(identity["role"], "agent")
        self.assertNotIn("token", identity)
        self.assertIn("task:create", identity["scopes"])

        tools = self.rpc(worker, "tools/list")["result"]["tools"]
        names = {item["name"] for item in tools}
        self.assertIn("agent_identity", names)
        self.assertNotIn("task_create", names)
        self.assertNotIn("system_status", names)

        message_args = {
            "destination": self.worker["agent_id"],
            "body": {"instruction": "worker ready"},
            "idempotency_key": "e2e-message-001",
        }
        sent = self.assert_ok(created, "message_send", message_args)
        self.assertFalse(sent["deduplicated"])
        repeated = self.assert_ok(created, "message_send", message_args)
        self.assertTrue(repeated["deduplicated"])
        self.assertEqual(sent["message_id"], repeated["message_id"])
        inbox = self.assert_ok(worker, "message_poll", {"after_seq": 0})
        self.assertEqual(len(inbox["messages"]), 1)
        self.assertEqual(inbox["messages"][0]["id"], sent["message_id"])
        self.assertEqual(self.assert_ok(created, "message_poll")["messages"], [])
        self.assertTrue(self.tool(created, "message_ack",
                                  {"message_id": sent["message_id"]})["isError"])
        self.assert_ok(worker, "message_ack", {"message_id": sent["message_id"]})
        self.assertEqual(self.assert_ok(worker, "message_poll")["messages"], [])

        event = self.assert_ok(created, "event_publish", {
            "topic": "shared.workflow",
            "body": {"phase": "created"},
            "idempotency_key": "e2e-event-001",
        })
        events = self.assert_ok(created, "event_poll", {"after_seq": 0})
        self.assertEqual(len(events["events"]), 1)
        self.assertEqual(events["events"][0]["seq"], event["event_seq"])

        task_args = {
            "assignee": self.worker["agent_id"],
            "payload": {"action": "echo", "data": {"check": "interop-e2e"}},
            "idempotency_key": "e2e-task-001",
        }
        task = self.assert_ok(created, "task_create", task_args)
        duplicate = self.assert_ok(created, "task_create", task_args)
        self.assertEqual(task["task_id"], duplicate["task_id"])
        self.assertTrue(duplicate["deduplicated"])
        self.assertTrue(self.tool(created, "task_create", {
            **task_args, "payload": {"action": "health"},
        })["isError"])
        self.assertEqual(self.assert_ok(created, "task_get",
                                      {"task_id": task["task_id"]})["state"], "queued")

        env = os.environ.copy()
        env.pop("SHARDS_ADMIN_TOKEN", None)
        env.pop("SHARDS_ADMIN_TOKEN_FILE", None)
        env.update({
            "SHARDS_GATEWAY_URL": self.base_url,
            "SHARDS_AGENT_TOKEN": worker,
        })
        process = subprocess.run(
            [sys.executable, "-m", "shards_mcp.worker", "--once"],
            env=env, capture_output=True, text=True, timeout=25, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn(worker, process.stdout + process.stderr)
        self.assertNotIn(admin, process.stdout + process.stderr)
        report = self.assert_ok(created, "task_get", {"task_id": task["task_id"]})
        self.assertEqual(report["state"], "reported")
        self.assertEqual(report["result"], {"echo": {"check": "interop-e2e"}})
        self.assertTrue(self.tool(created, "task_verify", {
            "task_id": task["task_id"], "approved": True,
            "evidence": {"review": "self-attestation denied"},
        })["isError"])
        self.assertTrue(self.tool(worker, "task_complete", {
            "task_id": task["task_id"], "success": True, "result": "again",
        })["isError"])
        approved = self.assert_ok(verifier, "task_verify", {
            "task_id": task["task_id"], "approved": True,
            "evidence": {"review": "output matched task input", "tests": 1},
        })
        self.assertEqual(approved["state"], "succeeded")
        self.assertEqual(self.assert_ok(admin, "audit_verify")["valid"], True)

        self.stop_server()
        self.gateway = Gateway(self.path, self.secret)
        self.start_server()
        persisted = self.assert_ok(created, "task_get", {"task_id": task["task_id"]})
        self.assertEqual(persisted["state"], "succeeded")
        verification = self.assert_ok(created, "verification_get",
                                      {"task_id": task["task_id"]})
        self.assertTrue(verification["verification"]["approved"])
        self.assertEqual(self.assert_ok(worker, "message_poll")["messages"], [])
        self.assertTrue(self.assert_ok(admin, "audit_verify")["valid"])

    def test_subprocess_stdio_bridge_scope_isolation_and_revocation(self):
        env = os.environ.copy()
        env.pop("SHARDS_ADMIN_TOKEN", None)
        env.pop("SHARDS_ADMIN_TOKEN_FILE", None)
        env.update({
            "SHARDS_GATEWAY_URL": self.base_url,
            "SHARDS_AGENT_TOKEN": self.observer["token"],
        })
        packets = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "other-runtime", "version": "1"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "agent_identity", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "system_status", "arguments": {}}},
        ]
        child = subprocess.run(
            [sys.executable, "-m", "shards_mcp.stdio"],
            env=env, input="".join(json.dumps(packet) + "\n" for packet in packets),
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertNotIn(self.observer["token"], child.stdout + child.stderr)
        responses = [json.loads(line) for line in child.stdout.splitlines()]
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4])
        self.assertEqual(
            {item["name"] for item in responses[1]["result"]["tools"]},
            {"agent_identity", "agent_heartbeat"},
        )
        self.assertEqual(
            responses[2]["result"]["structuredContent"]["agent_id"],
            self.observer["agent_id"],
        )
        self.assertTrue(responses[3]["result"]["isError"])
        self.gateway.revoke(self.gateway.authenticate(self.secret),
                            self.observer["agent_id"])
        status, _ = self.request(self.observer["token"], "GET", "/v1/tools")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
