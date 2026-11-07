"""End-to-end read-only MCP connection doctor and credential isolation."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from shards_mcp.core import Gateway
from shards_mcp.doctor import DiagnosticError, diagnose, main, read_agent_token
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
