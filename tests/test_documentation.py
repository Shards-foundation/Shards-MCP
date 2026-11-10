"""Executable regression for local documentation and deterministic demo."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import demo_local, docs_check, skill_install
from shards_mcp.core import Gateway


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

    def test_native_installed_skills_are_excluded_from_source_doc_validation(self):
        with tempfile.TemporaryDirectory(prefix="shards-doc-scan-") as location:
            root = Path(location)
            (root / "README.md").write_text("# Source documentation\n", encoding="utf-8")
            for client in ("codex", "cursor", "claude"):
                result = skill_install.execute(ROOT, client, "project", root,
                                               ["get-started"], apply=True)
                self.assertTrue(result["ok"])
            scanned = {page.relative_to(root).as_posix()
                       for page in docs_check.markdown_files(root)}
            self.assertEqual(scanned, {"README.md"})

    def test_skill_frontmatter_requires_closing_fence_and_populated_metadata(self):
        good = "---\nname: task-lifecycle\ndescription: Run bounded task steps.\n---\n# Task\n"
        self.assertTrue(docs_check.skill_frontmatter_valid(good))
        for bad in (
            good.replace("\n---\n# Task", "\n# Task"),
            "---\nname: task-lifecycle\ndescription:\n---\n# Task\n",
            "---\nname:\ndescription: Run bounded task steps.\n---\n# Task\n",
            "---\nname: task-lifecycle\n---\n# Task\n## description: later\n",
            "---\nname: task-lifecycle\nname: repeated\ndescription: Run.\n---\n",
        ):
            with self.subTest(header=bad):
                self.assertFalse(docs_check.skill_frontmatter_valid(bad))

    def test_demo_rejects_tampered_stored_result(self):
        original_complete = Gateway.task_complete

        def tamper_stored_result(gateway, actor, task_id, success, result):
            report = original_complete(gateway, actor, task_id, success, result)
            with gateway.tx() as db:
                db.execute(
                    "UPDATE tasks SET result=? WHERE id=?",
                    (json.dumps({"echo": "tampered-output"}), task_id),
                )
            return report

        with patch.object(Gateway, "task_complete", tamper_stored_result):
            with self.assertRaisesRegex(RuntimeError, "persisted result differs"):
                demo_local.main()

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

