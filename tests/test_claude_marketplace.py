"""Static contract for the opt-in Claude marketplace distribution.

This intentionally checks packaging and least-privilege configuration, not
live endpoint health or authentication correctness.
"""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "shards-mcp"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ClaudeMarketplaceTests(unittest.TestCase):
    def test_marketplace_points_to_installed_plugin(self) -> None:
        marketplace = read_json(MARKETPLACE)
        self.assertEqual(marketplace["name"], "shards-foundation-mcp")
        self.assertEqual(marketplace["owner"]["name"], "Shards Foundation")
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "shards-mcp")
        self.assertEqual(entry["source"], "./plugins/shards-mcp")
        self.assertEqual(
            (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").resolve(),
            (PLUGIN / ".claude-plugin" / "plugin.json").resolve(),
        )
        self.assertTrue((PLUGIN / ".claude-plugin" / "plugin.json").is_file())

    def test_plugin_manifest_and_remote_transport(self) -> None:
        manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")
        self.assertEqual(manifest["name"], "shards-mcp")
        self.assertEqual(manifest["version"], "0.1.0")
        servers = read_json(PLUGIN / ".mcp.json")["mcpServers"]
        self.assertEqual(
            servers,
            {
                "shards-mcp": {
                    "type": "http",
                    "url": "https://mcp.shardsinc.co.uk/mcp",
                }
            },
        )

    def test_plugin_has_no_auto_execution_or_embedded_credentials(self) -> None:
        manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")
        for key in ("hooks", "commands", "agents", "userConfig", "mcpServers"):
            self.assertNotIn(key, manifest)
        server = next(iter(read_json(PLUGIN / ".mcp.json")["mcpServers"].values()))
        self.assertEqual(set(server), {"type", "url"})
        for directory in ("hooks", "scripts", "commands", "agents", "skills"):
            self.assertFalse((PLUGIN / directory).exists(), directory)
        self.assertEqual(
            sorted(p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*") if p.is_file()),
            [".claude-plugin/plugin.json", ".mcp.json", "README.md"],
        )


if __name__ == "__main__":
    unittest.main()
