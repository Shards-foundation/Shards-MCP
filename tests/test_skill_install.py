"""Offline, isolated contract tests for the native Shards skill installer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import skill_install

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_preview_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = skill_install.execute(ROOT, "codex", "project", base,
                                           ["get-started", "client-integration"])
            self.assertTrue(report["ok"])
            self.assertEqual(report["action"], "PLAN")
            self.assertEqual(report["files_written"], 0)
            self.assertEqual(report["network_calls"], 0)
            self.assertFalse((base / ".agents").exists())

    def test_explicit_apply_and_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            receipt = skill_install.execute(ROOT, "cursor", "project", base,
                                            ["get-started", "client-integration"], apply=True)
            self.assertTrue(receipt["ok"])
            self.assertGreaterEqual(receipt["files_written"], 5)
            self.assertTrue((base / ".cursor/skills/get-started/SKILL.md").is_file())
            self.assertTrue((base / ".cursor/skills/client-integration/scripts/generate_config.py").is_file())
            verified = skill_install.execute(ROOT, "cursor", "project", base,
                                             ["get-started", "client-integration"], verify=True)
            self.assertTrue(verified["ok"])
            self.assertEqual(verified["errors"], [])

    def test_hash_mismatch_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skill_install.execute(ROOT, "codex", "project", base,
                                  ["get-started"], apply=True)
            skill = base / ".agents/skills/get-started/SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
            result = skill_install.execute(ROOT, "codex", "project", base,
                                           ["get-started"], verify=True)
            self.assertFalse(result["ok"])
            self.assertTrue(any("checksum mismatch" in issue for issue in result["errors"]))

    def test_never_overwrites_existing_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = skill_install.execute(ROOT, "claude", "project", base,
                                          ["get-started"], apply=True)
            self.assertTrue(first["ok"])
            skill = base / ".claude/skills/get-started/SKILL.md"
            before = hashlib.sha256(skill.read_bytes()).hexdigest()
            blocked = skill_install.execute(ROOT, "claude", "project", base,
                                            ["get-started"], apply=True)
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["files_written"], 0)
            self.assertEqual(hashlib.sha256(skill.read_bytes()).hexdigest(), before)

    def test_rejects_symlinked_target_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            (project / ".cursor").symlink_to(base)
            with self.assertRaisesRegex(ValueError, "symlink"):
                skill_install.execute(ROOT, "cursor", "project", project, ["get-started"])
            source = base / "source"
            (source / "skills/get-started/scripts").mkdir(parents=True)
            (source / "skills/catalog.json").write_text(
                '{"skills":[{"id":"get-started"}]}', encoding="utf-8")
            (source / "skills/get-started/SKILL.md").write_text(
                "---\nname: get-started\ndescription: Test\n---\n# Test\n", encoding="utf-8")
            (source / "skills/get-started/scripts/bad.py").symlink_to(source / "skills/catalog.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                skill_install.source_hashes(source, "get-started")

    def test_corrupt_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skill_install.execute(ROOT, "codex", "project", base,
                                  ["get-started"], apply=True)
            folder = base / ".agents/skills/get-started"
            manifest = folder / skill_install.MANIFEST
            for value in ("[]", '{"files":{}}', '{"schema_version":1,"skill":"get-started","files":{"../escape":"0"}}'):
                with self.subTest(value=value):
                    manifest.write_text(value, encoding="utf-8")
                    self.assertTrue(skill_install.verify_skill(folder, "get-started"))

    def test_client_path_mapping_and_user_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            for client, target in (
                ("codex", ".agents/skills"),
                ("cursor", ".cursor/skills"),
                ("claude", ".claude/skills"),
            ):
                with self.subTest(client=client):
                    self.assertEqual(skill_install.destination(client, "user", None, home),
                                     home / target)
                    self.assertFalse((home / target).exists())

    def test_cli_requires_apply_and_rejects_unknown_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            cli = ROOT / "scripts/skill_install.py"
            cmd = [sys.executable, str(cli), "--client", "codex",
                   "--project-dir", temp, "--skill", "get-started"]
            preview = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                     timeout=15, check=False)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(json.loads(preview.stdout)["action"], "PLAN")
            self.assertFalse((Path(temp) / ".agents").exists())
            invalid = subprocess.run(cmd[:-1] + ["unknown-skill"], cwd=ROOT,
                                     capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(json.loads(invalid.stdout)["action"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
