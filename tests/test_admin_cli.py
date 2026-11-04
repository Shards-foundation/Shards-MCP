"""Out-of-band operator provisioning: no token material enters MCP or REST."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

from shards_mcp.core import Gateway


class AdminCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / "gateway.db"
        self.token = secrets.token_urlsafe(48)
        self.env = {**os.environ, "SHARDS_ADMIN_TOKEN": self.token, "SHARDS_DB": str(self.dbpath)}

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "shards_mcp.admin", *args],
                              capture_output=True, text=True, timeout=12, env=self.env)

    def test_register_list_revoke_without_stdout_secret(self):
        secret_path = self.root / "agent-secret"
        created = self.cli("register", "--name", "hermes", "--provider", "local",
                           "--scope", "agent:heartbeat", "--scope", "task:read",
                           "--capability", "health", "--token-file", str(secret_path))
        self.assertEqual(created.returncode, 0, created.stderr)
        result = json.loads(created.stdout)
        agent_id = result["agent_id"]
        credential = secret_path.read_text(encoding="ascii").strip()
        self.assertTrue(credential.startswith("shards_"))
        self.assertNotIn(credential, created.stdout)
        self.assertNotIn(credential, created.stderr)
        self.assertEqual(set(result["scopes"]), {"agent:heartbeat", "task:read"})
        if os.name == "posix":
            self.assertEqual(secret_path.stat().st_mode & 0o777, 0o600)
        gateway = Gateway(str(self.dbpath), self.token)
        self.assertEqual(gateway.authenticate(credential).agent_id, agent_id)
        self.assertEqual(json.loads(self.cli("list").stdout)[0]["id"], agent_id)
        rejected = self.cli("register", "--name", "duplicate", "--provider", "local",
                            "--scope", "task:read", "--token-file", str(secret_path))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(len(gateway.agents(gateway.authenticate(self.token))), 1)
        revoked = self.cli("revoke", agent_id)
        self.assertEqual(revoked.returncode, 0)
        self.assertTrue(json.loads(revoked.stdout)["revoked"])

    def test_no_secret_file_on_invalid_registration(self):
        filename = self.root / "failed-token"
        result = self.cli("register", "--name", "", "--provider", "local",
                          "--scope", "agent:heartbeat", "--token-file", str(filename))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(filename.exists())


if __name__ == "__main__":
    unittest.main()
