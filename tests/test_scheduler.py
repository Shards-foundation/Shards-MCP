"""Independent supervisor cycles, admin secret-file loading and failure semantics."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

from shards_mcp.config import admin_token_from_environment
from shards_mcp.core import Gateway, GatewayError
from shards_mcp.scheduler import run_cycle


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.secret = secrets.token_urlsafe(48)
        self.secret_file = self.path / "admin_token"
        self.secret_file.write_text(self.secret + "\n")
        self.secret_file.chmod(0o600)
        self.database = self.path / "state.sqlite"
        self.gateway = Gateway(str(self.database), self.secret)
        self.root = self.gateway.authenticate(self.secret)
        worker = self.gateway.register(self.root, "scheduler-worker", "test", [],
                                       ["task:claim", "task:read", "task:update"])
        self.worker = self.gateway.authenticate(worker["token"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_supervisor_dispatches_once_then_blocks_expired_leases(self):
        task = self.gateway.schedule_create(self.root, self.worker.agent_id,
                                            {"action": "health"}, 60)
        due = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        with self.gateway.tx() as db:
            db.execute("UPDATE schedules SET next_due=? WHERE id=?",
                       (due, task["schedule_id"]))
        env_before = dict(os.environ)
        try:
            os.environ.pop("SHARDS_ADMIN_TOKEN", None)
            os.environ["SHARDS_ADMIN_TOKEN_FILE"] = str(self.secret_file)
            self.assertEqual(run_cycle(self.gateway), {"dispatched": 1, "leases_blocked": 0})
            self.assertEqual(run_cycle(self.gateway)["dispatched"], 0)
            with self.gateway.read_tx() as db:
                queued = db.execute("SELECT id FROM tasks WHERE state='queued'").fetchone()[0]
            self.gateway.task_claim(self.worker, queued, 60)
            with self.gateway.tx() as db:
                db.execute("UPDATE tasks SET lease_until=? WHERE id=?", (due, queued))
            result = run_cycle(self.gateway)
            self.assertEqual(result["leases_blocked"], 1)
            self.assertEqual(self.gateway.task_get(self.root, queued)["state"], "blocked")
            self.assertEqual(run_cycle(self.gateway)["leases_blocked"], 0)
        finally:
            os.environ.clear()
            os.environ.update(env_before)

    def test_scheduler_exits_cleanly_with_secret_file(self):
        env = {**os.environ, "SHARDS_ADMIN_TOKEN_FILE": str(self.secret_file),
               "SHARDS_DB": str(self.database)}
        env.pop("SHARDS_ADMIN_TOKEN", None)
        command = [sys.executable, "-m", "shards_mcp.scheduler", "--once"]
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=12)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"event":"scheduler_cycle"', completed.stderr)
        self.assertNotIn(self.secret, completed.stdout + completed.stderr)

    def test_secret_file_and_env_conflict_fail_closed(self):
        old = dict(os.environ)
        try:
            os.environ["SHARDS_ADMIN_TOKEN_FILE"] = str(self.secret_file)
            os.environ["SHARDS_ADMIN_TOKEN"] = self.secret
            with self.assertRaises(ValueError):
                admin_token_from_environment()
            os.environ.pop("SHARDS_ADMIN_TOKEN", None)
            self.assertEqual(admin_token_from_environment(), self.secret)
            link = self.path / "secret-symlink"
            try:
                link.symlink_to(self.secret_file)
            except OSError:
                return
            os.environ["SHARDS_ADMIN_TOKEN_FILE"] = str(link)
            with self.assertRaises(ValueError):
                admin_token_from_environment()
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
