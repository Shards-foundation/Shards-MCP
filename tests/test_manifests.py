"""Portable Agent Plugins 1.0.0 manifest smoke tests, no external network."""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PortableManifestTests(unittest.TestCase):
    def test_manifest_schema_and_transport(self):
        plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        mcp = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["$schema"],
                         "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(mcp["$schema"],
                         "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
        self.assertTrue(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", plugin["name"]))
        self.assertEqual(plugin["name"], "shards-mcp")
        self.assertEqual(plugin["version"], "0.1.0")
        self.assertEqual(set(mcp), {"$schema", "mcpServers"})
        entry = mcp["mcpServers"]["shards-gateway"]
        self.assertEqual(entry, {"type": "stdio", "command": "shards-mcp-stdio"})
        self.assertNotIn("token", json.dumps(plugin).lower() + json.dumps(mcp).lower())


if __name__ == "__main__":
    unittest.main()
