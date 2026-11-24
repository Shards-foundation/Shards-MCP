"""Tests for the redacted per-agent kernel bridge provisioning helper."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kernel_bridge_provision.py"
TENANT = "shards-internal"
AGENT_ID = "agent-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ACTOR = "edge-agent-alice"


def _load_script():
    spec = importlib.util.spec_from_file_location("kernel_bridge_provision_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def _names(self, directory: Path) -> list[str]:
        return sorted(path.name for path in directory.iterdir())

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
            self.assertEqual(self._names(Path(location)), [out.name], "no temporary credential file may remain")

    def test_refuses_to_overwrite_without_force_then_rotates_with_force(self):
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            first = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(first.returncode, 0, first.stderr)
            original = json.loads(out.read_text(encoding="utf-8"))["kernel_token"]
            original_bytes = out.read_bytes()
            self.assertEqual(self._names(Path(location)), [out.name])

            refused = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(refused.returncode, 2)
            self.assertIn("refusing to overwrite", refused.stderr)
            self.assertTrue(
                json.loads(out.read_text(encoding="utf-8"))["kernel_token"] == original,
                "overwrite refusal must preserve the original bearer",
            )
            self.assertEqual(out.read_bytes(), original_bytes, "stale-file refusal must preserve exact bytes")

            rotated = self._run(
                "--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR,
                "--out", str(out), "--force",
            )
            self.assertEqual(rotated.returncode, 0, rotated.stderr)
            replacement = json.loads(out.read_text(encoding="utf-8"))["kernel_token"]
            self.assertFalse(replacement == original, "force rotation must produce a new bearer")
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            self.assertEqual(self._names(Path(location)), [out.name], "rotation must not leave a temporary secret")

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

    def test_failed_json_write_preserves_existing_bytes_and_removes_temp(self):
        module = _load_script()
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            original = b'{"reviewed": true}\n'
            out.write_bytes(original)
            out.chmod(0o600)
            with self.assertRaises(TypeError):
                module.write_private(out, {"not_json": object()}, force=True)
            self.assertEqual(out.read_bytes(), original, "failed write must preserve the reviewed credential")
            self.assertEqual(self._names(Path(location)), [out.name], "failed write must not leak a temporary secret")

    def test_replace_failure_preserves_existing_bytes_and_removes_temp(self):
        module = _load_script()
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            original = b'{"reviewed": true}\n'
            out.write_bytes(original)
            out.chmod(0o600)
            with mock.patch.object(module.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    module.write_private(out, {"new": "credential"}, force=True)
            self.assertEqual(out.read_bytes(), original, "replace failure must preserve the reviewed credential")
            self.assertEqual(self._names(Path(location)), [out.name], "replace failure must not leak a temporary secret")

    def test_fsync_failure_preserves_existing_bytes_and_removes_temp(self):
        module = _load_script()
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            original = b'{"reviewed": true}\n'
            out.write_bytes(original)
            out.chmod(0o600)
            with mock.patch.object(module.os, "fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    module.write_private(out, {"new": "credential"}, force=True)
            self.assertEqual(out.read_bytes(), original, "fsync failure must preserve the reviewed credential")
            self.assertEqual(self._names(Path(location)), [out.name], "fsync failure must not leak a temporary secret")

    def test_failed_new_write_leaves_no_target_or_temp(self):
        module = _load_script()
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice.json"
            with mock.patch.object(module.os, "fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    module.write_private(out, {"new": "credential"}, force=False)
            self.assertFalse(out.exists(), "failed new write must not leave a partial credential")
            self.assertEqual(self._names(Path(location)), [], "failed new write must not leak a temporary secret")

    def test_rejects_symlink_target_and_dangling_symlink(self):
        module = _load_script()
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            target = Path(location) / "real.json"
            original = b'{"target": true}\n'
            target.write_bytes(original)
            target.chmod(0o600)
            link = Path(location) / "alice.json"
            link.symlink_to(target)
            with self.assertRaises(OSError) as caught:
                module.write_private(link, {"new": "credential"}, force=True)
            self.assertIn("symlink", str(caught.exception))
            self.assertTrue(link.is_symlink(), "the symlink must not be replaced or followed")
            self.assertEqual(target.read_bytes(), original, "the symlink target must be untouched")
            self.assertEqual(self._names(Path(location)), ["alice.json", "real.json"])

            dangling = Path(location) / "dangling.json"
            dangling.symlink_to(Path(location) / "missing.json")
            with self.assertRaises(OSError) as caught:
                module.write_private(dangling, {"new": "credential"}, force=True)
            self.assertIn("symlink", str(caught.exception))
            self.assertTrue(dangling.is_symlink(), "a dangling symlink must be rejected, not replaced")
            self.assertFalse((Path(location) / "missing.json").exists(), "no file may be created at the symlink target")
            self.assertEqual(self._names(Path(location)), ["alice.json", "dangling.json", "real.json"])

    def test_rejects_control_character_output_path_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "bad\x1bname.json"
            result = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(result.returncode, 2)
            self.assertIn("control characters", result.stderr)
            self.assertNotIn("\x1b", result.stderr, "the raw control sequence must not be printed")
            self.assertNotIn("bad", result.stderr, "the raw path must not be printed")
            self.assertFalse(out.exists(), "a control-character path must not create a file")

    def test_wrote_line_quotes_space_and_verifier_command_parses(self):
        with tempfile.TemporaryDirectory(prefix="kernel-bridge-provision-") as location:
            out = Path(location) / "alice key.json"
            result = self._run("--tenant", TENANT, "--agent-id", AGENT_ID, "--actor", ACTOR, "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"wrote: {shlex.quote(str(out))} (mode 0600)", result.stdout)
            command = next(
                line[len("verifier_command: "):]
                for line in result.stdout.splitlines()
                if line.startswith("verifier_command: ")
            )
            parts = shlex.split(command)
            self.assertEqual(len(parts), 3, "the verifier command must remain a single shell command")
            self.assertEqual(parts[:2], ["python", "-c"])
            self.assertIn(str(out), parts[2], "the verifier command must retain the exact output path")
            self.assertEqual(self._names(Path(location)), [out.name])


if __name__ == "__main__":
    unittest.main()
