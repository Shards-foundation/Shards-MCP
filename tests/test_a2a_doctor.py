"""Read-only A2A 1.0 connection doctor against the real loopback Shards gateway."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from shards_mcp.a2a import A2AAdapter
from shards_mcp.a2a_doctor import DiagnosticError, diagnose
from shards_mcp.core import Gateway
from shards_mcp.server import make_handler


class A2ADoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.admin_token = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(Path(self.temp.name) / "doctor.sqlite"), self.admin_token)
        root = self.gateway.authenticate(self.admin_token)
        self.reader = self.gateway.register(root, "doctor-reader", "test", [],
                                            ["agent:read", "task:read"])
        self.card_only = self.gateway.register(root, "card-only", "test", [],
                                               ["agent:read"])
        self.task_only = self.gateway.register(root, "task-only", "test", [],
                                               ["task:read"])
        self.target = self.gateway.register(root, "worker", "test", ["a2a/1.0"],
                                            ["agent:read", "task:read"])
        self.adapter = A2AAdapter(self.gateway, "http://127.0.0.1:8787")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                          make_handler(self.gateway, set(), a2a=self.adapter))
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        self.adapter.base_url = self.url
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def test_real_http_card_and_gettask_probe_never_create_task(self):
        with self.gateway.read_tx() as db:
            before = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        result = diagnose(self.url, self.reader["token"], self.target["agent_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["protocol_version"], "1.0")
        self.assertEqual(result["target_agent"], self.target["agent_id"])
        self.assertEqual(result["methods_exercised"], ["GetTask"])
        self.assertEqual(result["get_task_probe"], "not-found-as-expected")
        self.assertFalse(result["full_a2a_conformance"])
        self.assertNotIn(self.reader["token"], json.dumps(result))
        with self.gateway.read_tx() as db:
            after = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(after, before)

    def test_separate_process_cli_json_is_secret_free(self):
        env = os.environ.copy()
        env.pop("SHARDS_ADMIN_TOKEN", None)
        env.pop("SHARDS_AGENT_TOKEN_FILE", None)
        env.update({"SHARDS_GATEWAY_URL": self.url,
                    "SHARDS_AGENT_TOKEN": self.reader["token"]})
        run = subprocess.run(
            [sys.executable, "-m", "shards_mcp.a2a_doctor", "--json",
             "--target-agent", self.target["agent_id"]],
            capture_output=True, text=True, env=env, timeout=20,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["ok"])
        self.assertNotIn(self.reader["token"], run.stdout + run.stderr)
        self.assertNotIn(self.admin_token, run.stdout + run.stderr)

    def test_missing_scopes_and_revocation_fail_closed(self):
        with self.assertRaises(DiagnosticError):
            diagnose(self.url, self.card_only["token"], self.target["agent_id"])
        with self.assertRaises(DiagnosticError):
            diagnose(self.url, self.task_only["token"], self.target["agent_id"])
        self.gateway.revoke(self.gateway.authenticate(self.admin_token),
                            self.reader["agent_id"])
        with self.assertRaises(DiagnosticError):
            diagnose(self.url, self.reader["token"], self.target["agent_id"])

    def test_invalid_target_origin_and_timeout_rejected_before_network(self):
        token = self.reader["token"]
        for target in ("", "../worker", "agt_wrong", "agt_" + "G" * 24):
            with self.subTest(target=target):
                with self.assertRaises(DiagnosticError):
                    diagnose(self.url, token, target)
        for origin in ("http://example.org", "http://user:pass@localhost",
                       "http://127.0.0.1/other", "file:///etc/passwd"):
            with self.subTest(origin=origin):
                with self.assertRaises(DiagnosticError):
                    diagnose(origin, token, self.target["agent_id"])
        for timeout in (True, 0, 31, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(DiagnosticError):
                    diagnose(self.url, token, self.target["agent_id"], timeout=timeout)

    def test_agent_card_interface_and_security_mismatch_rejected(self):
        from shards_mcp.a2a_doctor import _read_json as real_read
        variations = (
            ("url", "https://untrusted.invalid/agent"),
            ("protocolVersion", "0.3"),
            ("protocolBinding", "UNSUPPORTED"),
        )
        for field, value in variations:
            with self.subTest(field=field):
                def changed(client, request, timeout):
                    data = real_read(client, request, timeout)
                    if request.get_method() == "GET":
                        data["supportedInterfaces"][0][field] = value
                    return data
                with patch("shards_mcp.a2a_doctor._read_json", side_effect=changed):
                    with self.assertRaisesRegex(DiagnosticError, "Agent Card"):
                        diagnose(self.url, self.reader["token"], self.target["agent_id"])
        def no_bearer(client, request, timeout):
            data = real_read(client, request, timeout)
            if request.get_method() == "GET":
                data["securitySchemes"] = {}
            return data
        with patch("shards_mcp.a2a_doctor._read_json", side_effect=no_bearer):
            with self.assertRaisesRegex(DiagnosticError, "bearer authentication"):
                diagnose(self.url, self.reader["token"], self.target["agent_id"])

    def test_gettask_envelope_and_permission_validation(self):
        from shards_mcp.a2a_doctor import _read_json as real_read
        variants = [
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32001}},
            {"jsonrpc": "2.0", "id": 1, "result": {"id": "unexpected"}},
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32003}},
        ]
        for invalid in variants:
            with self.subTest(reply=invalid):
                def changed(client, request, timeout):
                    if request.get_method() == "POST":
                        return invalid
                    return real_read(client, request, timeout)
                with patch("shards_mcp.a2a_doctor._read_json", side_effect=changed):
                    with self.assertRaises(DiagnosticError):
                        diagnose(self.url, self.reader["token"], self.target["agent_id"])

    def test_admin_token_not_used_for_agent_diagnostic(self):
        with patch.dict(os.environ, {"SHARDS_ADMIN_TOKEN": self.admin_token}):
            with self.assertRaises(DiagnosticError):
                diagnose(self.url, self.admin_token, self.target["agent_id"])


if __name__ == "__main__":
    unittest.main()
