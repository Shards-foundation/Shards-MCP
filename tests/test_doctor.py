"""End-to-end read-only MCP connection doctor and credential isolation."""
from __future__ import annotations

from http.client import BadStatusLine, IncompleteRead
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from shards_mcp.core import Gateway
from shards_mcp.doctor import DiagnosticError, diagnose, read_agent_token
from shards_mcp.server import make_handler


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.admin_secret = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(self.folder / "gateway.sqlite"), self.admin_secret)
        root = self.gateway.authenticate(self.admin_secret)
        self.agent = self.gateway.register(
            root, "diagnostic-only", "test-client", [], [],
        )
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.gateway, set())
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_port

    def test_diagnostic_runs_only_scoped_read_only_mcp_tools(self):
        before = self.gateway.audit_verify(
            self.gateway.authenticate(self.admin_secret)
        )["count"]
        report = diagnose(self.url, self.agent["token"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["protocol_version"], "2025-11-25")
        self.assertEqual(report["server_name"], "shards-mcp")
        self.assertEqual(report["agent_id"], self.agent["agent_id"])
        self.assertEqual(report["scopes"], [])
        self.assertEqual(report["tool_names"], ["agent_identity"])
        self.assertEqual(report["tool_count"], 1)
        self.assertGreaterEqual(report["round_trip_ms"], 0)
        self.assertNotIn(self.agent["token"], json.dumps(report))
        after = self.gateway.audit_verify(
            self.gateway.authenticate(self.admin_secret)
        )["count"]
        self.assertEqual(before, after, "doctor must not create audit writes")
        with self.gateway.read_tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_modern_doctor_validates_scoped_stateless_contract_without_writes(self):
        before = self.gateway.audit_verify(
            self.gateway.authenticate(self.admin_secret)
        )["count"]
        report = diagnose(self.url, self.agent["token"], protocol="modern")
        self.assertTrue(report["ok"])
        self.assertEqual(report["protocol_version"], "2026-07-28")
        self.assertEqual(report["agent_id"], self.agent["agent_id"])
        self.assertEqual(report["scopes"], [])
        self.assertEqual(report["tool_names"], ["agent_identity"])
        self.assertNotIn(self.agent["token"], json.dumps(report))
        self.assertEqual(
            before,
            self.gateway.audit_verify(
                self.gateway.authenticate(self.admin_secret)
            )["count"],
            "modern diagnostic must never append audit or task records",
        )
        with self.gateway.read_tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_modern_client_does_not_send_removed_legacy_notifications(self):
        from shards_mcp.doctor import _rpc as real_rpc
        order = []

        def record_rpc(client, identifier, method, params, timeout, **kwargs):
            order.append((method, kwargs.get("modern", False)))
            return real_rpc(client, identifier, method, params, timeout, **kwargs)

        with patch("shards_mcp.doctor._rpc", side_effect=record_rpc):
            with patch("shards_mcp.doctor._initialized",
                       side_effect=AssertionError("legacy initialized called")):
                result = diagnose(self.url, self.agent["token"], protocol="modern")
        self.assertTrue(result["ok"])
        self.assertEqual(order, [
            ("server/discover", True),
            ("tools/list", True),
            ("tools/call", True),
        ])

    def test_both_protocols_agree_and_cli_emits_secrets_free_json(self):
        env = os.environ.copy()
        env.pop("SHARDS_ADMIN_TOKEN", None)
        env.pop("SHARDS_ADMIN_TOKEN_FILE", None)
        env.pop("SHARDS_AGENT_TOKEN_FILE", None)
        env.update({"SHARDS_GATEWAY_URL": self.url,
                    "SHARDS_AGENT_TOKEN": self.agent["token"]})
        child = subprocess.run(
            [sys.executable, "-m", "shards_mcp.doctor",
             "--protocol", "both", "--json"],
            capture_output=True, text=True, env=env, timeout=25, check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        report = json.loads(child.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["protocol"], "both")
        self.assertEqual(report["agent_id"], self.agent["agent_id"])
        self.assertEqual(report["legacy"]["protocol_version"], "2025-11-25")
        self.assertEqual(report["modern"]["protocol_version"], "2026-07-28")
        self.assertEqual(report["legacy"]["tool_names"],
                         report["modern"]["tool_names"])
        self.assertEqual(report["scopes"], [])
        self.assertNotIn(self.agent["token"], child.stdout + child.stderr)
        self.assertNotIn(self.admin_secret, child.stdout + child.stderr)

    def test_modern_discovery_bad_metadata_fails_without_fallback(self):
        invalid_discoveries = [
            {"resultType": "complete", "supportedVersions": "2026-07-28",
             "ttlMs": 0, "cacheScope": "private"},
            {"resultType": "complete", "supportedVersions": ["2026-07-28"],
             "ttlMs": 1000, "cacheScope": "public"},
            {"resultType": "complete", "supportedVersions": ["2025-11-25"],
             "ttlMs": 0, "cacheScope": "private"},
            {"resultType": "complete", "supportedVersions": ["2026-07-28"],
             "ttlMs": False, "cacheScope": "private"},
        ]
        for discovery in invalid_discoveries:
            with self.subTest(discovery=discovery):
                with patch("shards_mcp.doctor._rpc", return_value=discovery) as rpc:
                    with self.assertRaises(DiagnosticError) as error:
                        diagnose(self.url, self.agent["token"], protocol="modern")
                self.assertIn("discovery", str(error.exception))
                self.assertEqual(rpc.call_count, 1)
                self.assertNotIn(self.agent["token"], str(error.exception))

    def test_mcp_handshake_emits_initialized_notification_before_tool_calls(self):
        from shards_mcp.doctor import _initialized as real_initialized
        order = []

        def record_initialised(client, timeout):
            order.append("notifications/initialized")
            return real_initialized(client, timeout)

        from shards_mcp.doctor import _rpc as real_rpc
        def record_rpc(client, identifier, method, params, timeout):
            order.append(method)
            return real_rpc(client, identifier, method, params, timeout)

        with patch("shards_mcp.doctor._rpc", side_effect=record_rpc):
            with patch("shards_mcp.doctor._initialized", side_effect=record_initialised):
                report = diagnose(self.url, self.agent["token"])
        self.assertTrue(report["ok"])
        self.assertEqual(
            order,
            ["initialize", "notifications/initialized", "tools/list", "tools/call"],
        )

    def test_separate_process_json_report_has_no_credentials(self):
        env = os.environ.copy()
        env.pop("SHARDS_ADMIN_TOKEN", None)
        env.pop("SHARDS_ADMIN_TOKEN_FILE", None)
        env.pop("SHARDS_AGENT_TOKEN_FILE", None)
        env.update({"SHARDS_GATEWAY_URL": self.url,
                    "SHARDS_AGENT_TOKEN": self.agent["token"]})
        child = subprocess.run(
            [sys.executable, "-m", "shards_mcp.doctor", "--json"],
            capture_output=True, text=True, env=env, timeout=20, check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        body = json.loads(child.stdout)
        self.assertTrue(body["ok"])
        self.assertEqual(body["agent_id"], self.agent["agent_id"])
        self.assertEqual(body["tool_names"], ["agent_identity"])
        self.assertNotIn(self.agent["token"], child.stdout + child.stderr)
        self.assertNotIn(self.admin_secret, child.stdout + child.stderr)

    def test_operator_credential_is_never_accepted_as_an_agent(self):
        with self.assertRaises(DiagnosticError) as problem:
            diagnose(self.url, self.admin_secret)
        self.assertIn("not a valid scoped agent identity", str(problem.exception))
        self.assertNotIn(self.admin_secret, str(problem.exception))

    def test_invalid_token_revocation_and_remote_plaintext_fail_closed(self):
        with self.assertRaises(DiagnosticError):
            diagnose(self.url, "x" * 48)
        root = self.gateway.authenticate(self.admin_secret)
        self.gateway.revoke(root, self.agent["agent_id"])
        with self.assertRaises(DiagnosticError):
            diagnose(self.url, self.agent["token"])
        for bad_url in (
            "http://example.com:8787",
            "http://user:secret@127.0.0.1:8787",
            "http://127.0.0.1:8787/other",
            "http://127.0.0.1:8787/?token=secret",
            "ftp://127.0.0.1",
            "https://",
        ):
            with self.subTest(url=bad_url):
                with self.assertRaises(DiagnosticError):
                    diagnose(bad_url, self.agent["token"])
        for bad_timeout in (0, 31, float("nan"), float("inf"), True):
            with self.subTest(timeout=bad_timeout):
                with self.assertRaises(DiagnosticError):
                    diagnose(self.url, self.agent["token"], timeout=bad_timeout)

    def test_untrusted_http_status_line_never_exposes_credential(self):
        # Some malformed HTTP responses raise BadStatusLine with the original
        # untrusted status text included in the exception string.
        from unittest.mock import Mock
        token = self.agent["token"]
        client = Mock()
        client.url = self.url
        client.token = token
        for failure in (
            BadStatusLine("HTTP/1.1 " + token),
            IncompleteRead(token.encode("ascii"), 1000),
        ):
            with self.subTest(error=type(failure).__name__):
                client.opener.open.side_effect = failure
                with patch("shards_mcp.doctor.AgentClient", return_value=client):
                    with self.assertRaises(DiagnosticError) as problem:
                        diagnose(self.url, token)
                self.assertNotIn(token, str(problem.exception))
                self.assertEqual(
                    str(problem.exception), "MCP transport unavailable or refused"
                )

    def test_reflected_token_anywhere_in_report_is_never_emitted(self):
        token = self.agent["token"]
        valid_identity = {
            "isError": False,
            "structuredContent": {"agent_id": self.agent["agent_id"],
                                  "role": "agent", "scopes": []},
        }
        for variant in ("server_version", "tool_name", "effective_scope"):
            with self.subTest(variant=variant):
                version = "0.1.0"
                names = ["agent_identity"]
                identity = dict(valid_identity)
                if variant == "server_version":
                    version = "0.1.0-" + token
                elif variant == "tool_name":
                    names.append("unknown_" + token)
                else:
                    identity = {
                        **valid_identity,
                        "structuredContent": {
                            **valid_identity["structuredContent"],
                            "scopes": ["scope:" + token],
                        },
                    }
                result_sequence = [
                    {"protocolVersion": "2025-11-25",
                     "serverInfo": {"name": "shards-mcp", "version": version}},
                    {"tools": [{"name": name} for name in names]},
                    identity,
                ]
                with patch("shards_mcp.doctor._rpc", side_effect=result_sequence):
                    with self.assertRaises(DiagnosticError) as problem:
                        diagnose(self.url, token)
                self.assertEqual(
                    str(problem.exception), "gateway reflected an agent credential"
                )
                self.assertNotIn(token, str(problem.exception))

    def test_untrusted_server_metadata_cannot_inject_terminal_controls(self):
        token = self.agent["token"]
        invalid_version = [
            {"protocolVersion": "2025-11-25",
             "serverInfo": {"name": "shards-mcp", "version": "0.1.0\x1b[2J"}}
        ]
        with patch("shards_mcp.doctor._rpc", side_effect=invalid_version):
            with self.assertRaises(DiagnosticError) as issue:
                diagnose(self.url, token)
        self.assertEqual(str(issue.exception), "invalid MCP server version metadata")
        self.assertNotIn("\x1b", str(issue.exception))

        invalid_agent = [
            {"protocolVersion": "2025-11-25",
             "serverInfo": {"name": "shards-mcp", "version": "0.1.0"}},
            {"tools": [{"name": "agent_identity"}]},
            {"isError": False, "structuredContent": {
                "agent_id": self.agent["agent_id"] + "\x1b[2J",
                "role": "agent", "scopes": [],
            }},
        ]
        with patch("shards_mcp.doctor._rpc", side_effect=invalid_agent):
            with patch("shards_mcp.doctor._initialized", return_value=None):
                with self.assertRaises(DiagnosticError) as issue:
                    diagnose(self.url, token)
        self.assertIn("not a valid scoped agent identity", str(issue.exception))
        self.assertNotIn("\x1b", str(issue.exception))

    def test_scoped_secret_files_are_secure_and_sources_unambiguous(self):
        secret = self.folder / "agent.token"
        secret.write_text(self.agent["token"] + "\n", encoding="ascii")
        if os.name == "posix":
            secret.chmod(0o600)
        with patch.dict(os.environ, {
            "SHARDS_AGENT_TOKEN": "",
            "SHARDS_AGENT_TOKEN_FILE": "",
        }):
            self.assertEqual(read_agent_token(str(secret)), self.agent["token"])
            with patch.dict(os.environ, {"SHARDS_AGENT_TOKEN": self.agent["token"]}):
                with self.assertRaises(DiagnosticError):
                    read_agent_token(str(secret))
            if os.name == "posix":
                secret.chmod(0o644)
                with self.assertRaises(DiagnosticError):
                    read_agent_token(str(secret))
                secret.chmod(0o600)
            alias = self.folder / "alias.token"
            try:
                alias.symlink_to(secret)
            except (OSError, NotImplementedError):
                pass
            else:
                with self.assertRaises(DiagnosticError):
                    read_agent_token(str(alias))

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"),
                         "POSIX named pipes only")
    def test_fifo_secret_path_never_blocks_before_file_type_check(self):
        pipe = self.folder / "agent.fifo"
        os.mkfifo(pipe, 0o600)
        with patch.dict(os.environ, {
            "SHARDS_AGENT_TOKEN": "",
            "SHARDS_AGENT_TOKEN_FILE": "",
        }):
            start = time.monotonic()
            with self.assertRaisesRegex(DiagnosticError, "regular file"):
                read_agent_token(str(pipe))
            self.assertLess(time.monotonic() - start, 1.0)

    def test_json_cli_errors_do_not_echo_secret_or_untrusted_url(self):
        env = os.environ.copy()
        env.pop("SHARDS_AGENT_TOKEN_FILE", None)
        env.pop("SHARDS_ADMIN_TOKEN", None)
        env.pop("SHARDS_ADMIN_TOKEN_FILE", None)
        env.update({
            "SHARDS_AGENT_TOKEN": "x" * 48,
            "SHARDS_GATEWAY_URL": self.url,
        })
        child = subprocess.run(
            [sys.executable, "-m", "shards_mcp.doctor", "--json"],
            capture_output=True, text=True, env=env, timeout=15, check=False,
        )
        self.assertEqual(child.returncode, 1)
        result = json.loads(child.stdout)
        self.assertFalse(result["ok"])
        self.assertIsInstance(result["error"], str)
        self.assertNotIn("x" * 48, child.stdout + child.stderr)


if __name__ == "__main__":
    unittest.main()
