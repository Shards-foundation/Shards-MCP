"""Tests for the redacted per-agent kernel bridge provisioning helper."""
from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kernel_bridge_provision.py"
TENANT = "shards-internal"
AGENT_ID = "agent-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ACTOR = "edge-agent-alice"


class KernelBridgeProvisionTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_writes_private_file_and_prints_only_redacted_verification(self):
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            result = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)

            data = json.loads(out.read_text(encoding="utf-8"))
            token = data["kernel_token"]
            secret = token.split(".", 1)[1]

            self.assertFalse(token in result.stdout, "stdout must not contain the generated bearer")
            self.assertFalse(token in result.stderr, "stderr must not contain the generated bearer")
            self.assertFalse(secret in result.stdout, "stdout must not contain the bearer secret")
            self.assertIn(f"redacted_token: {ACTOR}.****", result.stdout)
            self.assertIn("mode 0600", result.stdout)

            self.assertEqual(data["tenant"], TENANT)
            self.assertEqual(data["agent_id"], AGENT_ID)
            self.assertEqual(data["kernel_actor"], ACTOR)
            self.assertTrue(token.startswith(f"{ACTOR}."))
            self.assertGreaterEqual(len(secret), 32)
            self.assertTrue(
                data["token_sha256"] == hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "token fingerprint must match the generated bearer",
            )
            entry = data["worker_actor_map_entry"][f"{TENANT}/{AGENT_ID}"]
            self.assertEqual(entry["actor"], ACTOR)
            self.assertTrue(entry["token"] == token, "worker map token must match the generated bearer")
            self.assertEqual(data["kernel_agent_entry"]["allowed_tools"], ["github.issue.add_label"])
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)

    def test_refuses_to_overwrite_without_force_then_rotates_with_force(self):
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            first = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(first.returncode, 0, first.stderr)
            original = json.loads(out.read_text(encoding="utf-8"))["kernel_token"]

            refused = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(refused.returncode, 2)
            self.assertIn("refusing to overwrite", refused.stderr)
            self.assertTrue(
                json.loads(out.read_text(encoding="utf-8"))["kernel_token"] == original,
                "overwrite refusal must preserve the original bearer",
            )

            rotated = self._run(
                "--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR,
                "--out", str(out), "--force",
            )
            self.assertEqual(rotated.returncode, 0, rotated.stderr)
            replacement = json.loads(out.read_text(encoding="utf-8"))["kernel_token"]
            self.assertFalse(replacement == original, "force rotation must produce a new bearer")
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)

    def test_rejects_unsafe_identifiers_without_creating_a_file(self):
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "bad.json"
            for args in (
                ("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", "bad.actor"),
                ("--tenant", "bad/tenant", "--agent-id", AGENT_ID, "--actor", ACTOR),
                ("--tenant", TENANT, "--agent-id", "../escape", "--actor", ACTOR),
            ):
                result = self._run(*args, "--out", str(out))
                self.assertEqual(result.returncode, 2)
                self.assertFalse(out.exists(), "invalid input must not create a credential file")


if __name__ == "__main__":
    unittest.main()
