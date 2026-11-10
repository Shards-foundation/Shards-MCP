"""Regression tests for the non-destructive, opt-in MCP local installer."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shards_mcp.connect import DEFAULT_URL, install_cursor, main


class InstallerTests(unittest.TestCase):
    def test_merge_preserves_unrelated_servers(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = Path(root) / "mcp.json"
            original = {"mcpServers": {"other": {"command": "python", "args": ["x.py"]}}, "features": {"x": True}}
            cfg.write_text(json.dumps(original), encoding="utf-8")
            changed = install_cursor(cfg)
            self.assertEqual(changed, str(cfg))
            value = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(value["mcpServers"]["other"], original["mcpServers"]["other"])
            self.assertEqual(value["features"], {"x": True})
            self.assertEqual(value["mcpServers"]["shards-mcp"]["url"], DEFAULT_URL)
            self.assertTrue(Path(root, "mcp.json.bak").exists())
            self.assertEqual(install_cursor(cfg), "already configured")

    def test_new_config_has_no_embedded_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = Path(root) / ".cursor" / "mcp.json"
            install_cursor(cfg)
            body = cfg.read_text(encoding="utf-8")
            self.assertNotIn("Bearer", body)
            self.assertNotIn("token", body.lower())
            self.assertIn(DEFAULT_URL, body)
            if __import__("os").name == "posix":
                self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)

    def test_refuse_overwrite_different_server(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = Path(root) / "mcp.json"
            data = {"mcpServers": {"shards-mcp": {"url": "https://other.example/mcp"}}}
            cfg.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different"):
                install_cursor(cfg)
            self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), data)

    def test_refuse_invalid_json(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = Path(root) / "mcp.json"
            cfg.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot be parsed"):
                install_cursor(cfg)
            self.assertFalse(Path(root, "mcp.json.bak").exists())

    def test_refuse_existing_backup(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = Path(root) / "mcp.json"
            cfg.write_text("{}", encoding="utf-8")
            Path(root, "mcp.json.bak").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Backup already exists"):
                install_cursor(cfg)
            self.assertEqual(cfg.read_text(encoding="utf-8"), "{}")

    def test_symlink_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "target.json"
            target.write_text("{}", encoding="utf-8")
            cfg = Path(root) / "mcp.json"
            try:
                cfg.symlink_to(target)
            except (NotImplementedError, OSError):
                self.skipTest("Symlinks unsupported")
            with self.assertRaisesRegex(ValueError, "symlink"):
                install_cursor(cfg)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("pathlib.Path.home", return_value=Path(root)):
                code = main(["--client", "cursor-app"])
            self.assertEqual(code, 0)
            self.assertFalse((Path(root) / ".cursor" / "mcp.json").exists())

    def test_project_install_after_explicit_approval(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("pathlib.Path.cwd", return_value=Path(root)):
                code = main(["--client", "cursor-cli", "--scope", "project", "--install"])
            self.assertEqual(code, 0)
            self.assertTrue((Path(root) / ".cursor" / "mcp.json").exists())

    def test_invalid_endpoint_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--client", "cursor-cli", "--endpoint", "http://notsecure.example/mcp"])


if __name__ == "__main__":
    unittest.main()
