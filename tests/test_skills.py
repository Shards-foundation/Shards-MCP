"""No-network, no-write regression tests for skill catalog and release gates."""
from __future__ import annotations

import json
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
                {"id": "missing", "category": "intake", "risk": "low", "triggers": ["first run"], "scripts": []},
                {"id": "missing", "category": "intake", "risk": "low", "triggers": ["first run"], "scripts": []},
            ]}
            (root / "skills" / "catalog.json").write_text(json.dumps(sample), encoding="utf-8")
            problems = skillctl.validate(root)
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
