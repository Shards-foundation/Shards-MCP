"""Executable regression for local documentation and deterministic demo."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script)],
            cwd=ROOT, text=True, capture_output=True, timeout=40, check=False,
        )

    def test_internal_documentation_links_and_skill_metadata(self):
        result = self._run("docs_check.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DOC PASS:", result.stdout)

    def test_demo_checks_remain_active_in_optimized_python(self):
        script = ROOT / "scripts" / "demo_local.py"
        source = script.read_text(encoding="utf-8")
        self.assertFalse(
            any(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(source))),
            "demo evidence checks must not rely on disabled Python assert statements",
        )
        completed = subprocess.run(
            [sys.executable, "-O", str(script)],
            cwd=ROOT, text=True, capture_output=True, timeout=40, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["audit_valid"])
        self.assertEqual(report["task_state"], "succeeded")

    def test_safe_demo_uses_distinct_roles_and_verified_success(self):
        result = self._run("demo_local.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["task_state"], "succeeded")
        self.assertTrue(report["audit_valid"])
        self.assertTrue(report["idempotency_deduplicated"])
        self.assertTrue(report["temporary_database"])
        self.assertFalse(report["external_actions_executed"])
        self.assertEqual(len({report["creator_id"], report["worker_id"], report["verifier_id"]}), 3)
        self.assertNotIn("token", report)


if __name__ == "__main__":
    unittest.main()

