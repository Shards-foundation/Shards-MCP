"""No-network, no-write regression tests for skill catalog and release gates."""
from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import skillctl, skill_evidence


ROOT = Path(__file__).resolve().parents[1]


class SkillsContractTests(unittest.TestCase):
    def test_repository_catalog_is_complete(self):
        self.assertEqual(skillctl.validate(ROOT), [])
        catalog = skillctl.load_catalog(ROOT)
        ids = {entry["id"] for entry in catalog["skills"]}
        self.assertGreaterEqual(len(ids), 11)
        self.assertIn("get-started", ids)
        self.assertIn("skill-authoring", ids)

    def test_suggest_get_started(self):
        entries = skillctl.load_catalog(ROOT)["skills"]
        options = skillctl.suggest("new agent first run onboarding", entries)
        self.assertEqual(options[0]["id"], "get-started")
        self.assertGreater(options[0]["score"], 0)

    def test_missing_skill_and_duplicate_catalog_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="shards-skills-test-") as directory:
            root = Path(directory)
            (root / "skills").mkdir()
            sample = {"schema_version": 1, "skills": [
                {"id": "missing", "category": [], "risk": {}, "triggers": ["first run"], "scripts": []},
                {"id": "missing", "category": "intake", "risk": "low", "triggers": ["first run"], "scripts": []},
            ]}
            (root / "skills" / "catalog.json").write_text(json.dumps(sample), encoding="utf-8")
            problems = skillctl.validate(root)
            self.assertTrue(any("invalid category" in p for p in problems))
            self.assertTrue(any("invalid risk" in p for p in problems))
            self.assertTrue(any("duplicate" in p for p in problems))
            self.assertTrue(any("missing skill" in p for p in problems))

    def test_path_traversal_is_not_a_valid_script(self):
        with tempfile.TemporaryDirectory(prefix="shards-skills-test-") as directory:
            root = Path(directory)
            self.assertFalse(skillctl.safe_script(root, "../private/token"))
            self.assertFalse(skillctl.safe_script(root, "/etc/passwd"))
            self.assertFalse(skillctl.safe_script(root, "skills\\evil.py"))

    def test_release_receipt_fails_closed_by_default(self):
        template = json.loads((ROOT / "skills/release-readiness/assets/evidence-template.json").read_text())
        result = skill_evidence.assess(template, "hosted")
        self.assertEqual(result["verdict"], "NO_GO")
        self.assertIn("oauth_e2e: NOT_VERIFIED", result["reasons"])

    def test_self_attested_pass_only_eligible_for_human_review(self):
        data = {"revision": "a" * 40, "envelope": "package", "gates": {
            gate: {"status": "PASS", "evidence": ["ci://example/nonproduction-fixture"]}
            for gate in skill_evidence.PACKAGE
        }}
        self.assertEqual(skill_evidence.assess(data, "package")["verdict"],
                         "ELIGIBLE_FOR_INDEPENDENT_REVIEW")
        data["gates"]["protocol_e2e"]["evidence"] = []
        self.assertEqual(skill_evidence.assess(data, "package")["verdict"], "NO_GO")

    def test_native_client_config_generator(self):
        # Import by file path because Agent Skills directories use hyphens.
        import importlib.util
        path = ROOT / "skills/client-integration/scripts/generate_config.py"
        spec = importlib.util.spec_from_file_location("shards_client_config", path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        spec.loader.exec_module(module)
        endpoint = module.DEFAULT_ENDPOINT
        config = module.configuration("cursor-app", endpoint)
        self.assertEqual(config["config"]["mcpServers"]["shards"]["url"], endpoint)
        parsed = urlsplit(config["install_url"])
        self.assertEqual(parsed.scheme, "cursor")
        payload = parse_qs(parsed.query)["config"][0]
        self.assertEqual(json.loads(base64.b64decode(payload))["url"], endpoint)
        self.assertTrue(module.configuration("codex-cli", endpoint)["commands"][0].startswith("codex mcp add"))
        for bad in ["http://evil.example/mcp", "https://a.example/mcp?token=x", "https://user:secret@example.com/mcp", "https://a.example/other", "https://a.example:0/mcp"]:
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    module.validate_endpoint(bad)
        self.assertEqual(module.validate_endpoint("http://127.0.0.1:8787/mcp", allow_loopback=True),
                         "http://127.0.0.1:8787/mcp")

    def test_malformed_gate_status_fails_closed_without_typeerror(self):
        data = {"revision": "b" * 40, "envelope": "package", "gates": {
            gate: {"status": "PASS", "evidence": ["ci://nonproduction-test"]}
            for gate in skill_evidence.PACKAGE
        }}
        for wrong_type in ([], {}, 12, None, True):
            with self.subTest(status=wrong_type):
                data["gates"]["unit_tests"]["status"] = wrong_type
                outcome = skill_evidence.assess(data, "package")
                self.assertEqual(outcome["verdict"], "NO_GO")
                self.assertTrue(any("unit_tests: invalid" in x for x in outcome["reasons"]))

    def test_duplicate_json_receipt_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
            json.loads('{"status":"PASS","status":"FAIL"}', object_pairs_hook=skill_evidence.no_duplicates)

    def test_get_started_preflight_has_no_live_actions(self):
        output = subprocess.run(
            [sys.executable, str(ROOT / "skills/get-started/scripts/preflight.py"), "--json"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(output.returncode, 0, output.stderr)
        receipt = json.loads(output.stdout)
        self.assertIn(receipt["state"], {"READY_LOCAL", "BLOCKED"})
        self.assertEqual(receipt["network_calls"], 0)
        self.assertEqual(receipt["files_written"], 0)


if __name__ == "__main__":
    unittest.main()
