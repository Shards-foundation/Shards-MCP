"""Consistent, owner-only SQLite snapshot creation, verification and recovery rehearsal."""
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from shards_mcp.core import Gateway, GatewayError
from shards_mcp.snapshots import create_snapshot, inspect_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.db = self.dir / "live.sqlite"
        self.backups = self.dir / "backups"
        self.backups.mkdir(mode=0o700)
        self.admin_token = secrets.token_urlsafe(48)
        self.gateway = Gateway(str(self.db), self.admin_token)
        self.root = self.gateway.authenticate(self.admin_token)
        a = self.gateway.register(self.root, "snapshot-origin", "test", [],
                                  ["task:create", "message:send", "message:read"])
        b = self.gateway.register(self.root, "snapshot-worker", "test", [], ["task:read"])
        self.actor = self.gateway.authenticate(a["token"])
        self.dest = b["agent_id"]
        self.gateway.delegation_grant(self.root, a["agent_id"], self.dest)

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_consistency_and_restore_rehearsal(self):
        self.gateway.send(self.actor, self.dest, {"hello": "snapshot"}, "snapshot-msg")
        created = self.gateway.task_create(self.actor, self.dest, {"action": "health"}, "snapshot-task")
        output = self.backups / "snapshot-001.sqlite"
        result = create_snapshot(self.gateway, self.root, str(output))
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["sha256"]), 64)
        self.assertGreater(result["bytes"], 1024)
        self.assertEqual(result["records"]["messages"], 1)
        self.assertEqual(result["records"]["tasks"], 1)
        self.assertEqual(result["records"]["delegation_grants"], 1)
        if os.name == "posix":
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(inspect_snapshot(str(output))["sha256"], result["sha256"])
        self.assertEqual(self.gateway.audit_list(self.root, 1)[0]["action"], "snapshot.created")

        restored = self.dir / "restored.sqlite"
        shutil.copyfile(output, restored)
        isolated = Gateway(str(restored), self.admin_token)
        with isolated.read_tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks WHERE id=?",
                                        (created["task_id"],)).fetchone()[0], 1)
        self.assertTrue(isolated.audit_verify(isolated.authenticate(self.admin_token))["valid"])

    def test_existing_file_and_active_database_are_not_overwritten(self):
        output = self.backups / "present.sqlite"
        output.write_bytes(b"original")
        with self.assertRaises(GatewayError):
            create_snapshot(self.gateway, self.root, str(output))
        self.assertEqual(output.read_bytes(), b"original")
        with self.assertRaises(GatewayError):
            create_snapshot(self.gateway, self.root, str(self.db))

    def test_modified_snapshot_fails_audit_chain_validation(self):
        output = self.backups / "tamper.sqlite"
        create_snapshot(self.gateway, self.root, str(output))
        with sqlite3.connect(output) as db:
            db.execute("DROP TRIGGER audit_reject_update")
            db.execute("UPDATE audit SET action='forged' WHERE seq=1")
        with self.assertRaises(GatewayError):
            inspect_snapshot(str(output))

    def test_snapshot_missing_delegation_table_is_not_current_format_valid(self):
        output = self.backups / "legacy-policy.sqlite"
        create_snapshot(self.gateway, self.root, str(output))
        with sqlite3.connect(output) as db:
            db.execute("DROP TABLE delegation_grants")
        with self.assertRaises(GatewayError):
            inspect_snapshot(str(output))

    def test_admin_cli_backup_and_offline_verify_without_live_secret(self):
        output = self.backups / "cli.sqlite"
        env = {**os.environ, "SHARDS_ADMIN_TOKEN": self.admin_token, "SHARDS_DB": str(self.db)}
        cmd = [sys.executable, "-m", "shards_mcp.admin"]
        created = subprocess.run(cmd + ["backup", "--output", str(output)],
                                 capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(created.returncode, 0, created.stderr)
        report = json.loads(created.stdout)
        self.assertEqual(report["output"], str(output))
        self.assertNotIn(self.admin_token, created.stdout + created.stderr)
        offline_env = dict(env)
        offline_env.pop("SHARDS_ADMIN_TOKEN", None)
        verified = subprocess.run(cmd + ["verify-snapshot", "--input", str(output)],
                                  capture_output=True, text=True, env=offline_env, timeout=15)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["sha256"], report["sha256"])
        self.assertNotIn(self.admin_token, verified.stdout)

    def test_untrusted_snapshots_cannot_be_verified_as_valid(self):
        invalid = self.backups / "invalid.db"
        invalid.write_bytes(b"not-a-sqlite-file")
        with self.assertRaises(GatewayError):
            inspect_snapshot(str(invalid))
        with self.assertRaises(GatewayError):
            inspect_snapshot(str(self.backups / "missing.db"))


if __name__ == "__main__":
    unittest.main()
