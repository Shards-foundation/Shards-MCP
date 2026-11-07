#!/usr/bin/env python3
"""Fail-closed local documentation integrity checks. Only stdlib required."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


REPO = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\n]+)\)")
IGNORED = {".git", ".venv", "node_modules", "dist", "build", "__pycache__"}


def markdown_files(root: Path):
    for candidate in sorted(root.rglob("*.md")):
        if not any(part in IGNORED for part in candidate.relative_to(root).parts):
            yield candidate


def validate(root: Path = REPO) -> list[str]:
    problems: list[str] = []
    paths = list(markdown_files(root))
    for page in paths:
        content = page.read_text(encoding="utf-8")
        if not re.search(r"(?m)^#\s+\S+", content):
            problems.append(f"{page.relative_to(root)}: missing primary heading")
        for raw in LINK.findall(content):
            target = raw.strip().split(" ", 1)[0].strip("<>")
            if not target or target.startswith("#") or target.startswith("//"):
                continue
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            destination = (page.parent / unquote(parsed.path)).resolve()
            try:
                destination.relative_to(root.resolve())
            except ValueError:
                problems.append(f"{page.relative_to(root)}: link leaves repository: {raw}")
                continue
            if not destination.exists():
                problems.append(f"{page.relative_to(root)}: broken relative link: {raw}")
    required = [
        "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE",
        "docs/README.md", "docs/faq.md", "docs/specification.md", "docs/cookbook.md",
        "docs/demo.md", "docs/getting-started.md", "docs/agent-onboarding.md",
        "docs/compliance/controls.md", "docs/compliance/publication-gates.md",
        "docs/legal/privacy.md", "docs/legal/terms.md", "skills/README.md",
    ]
    for name in required:
        if not (root / name).exists():
            problems.append(f"required documentation missing: {name}")
    for name in ("docs/legal/privacy.md", "docs/legal/terms.md", "docs/legal/dpa.md", "docs/legal/cookies.md"):
        file = root / name
        if file.exists():
            opening = "\n".join(file.read_text(encoding="utf-8").splitlines()[:8])
            if not re.search(r"(?i)\bstatus:\s*DRAFT\b", opening):
                problems.append(f"{name}: missing explicit Status: DRAFT legal approval warning")
    license_file = root / "LICENSE"
    if license_file.exists():
        license_text = license_file.read_text(encoding="utf-8")
        for required_notice in (
            "MIT License",
            "Copyright (c)",
            "Permission is hereby granted",
            "The above copyright notice",
            'THE SOFTWARE IS PROVIDED "AS IS"',
            "WITHOUT WARRANTY",
            "AUTHORS OR COPYRIGHT HOLDERS",
        ):
            if required_notice not in license_text:
                problems.append(f"LICENSE: missing canonical MIT clause: {required_notice}")
    for skill in (root / "skills").glob("*/SKILL.md"):
        data = skill.read_text(encoding="utf-8")
        if not data.startswith("---\n") or "description:" not in data or "name:" not in data:
            problems.append(f"{skill.relative_to(root)}: invalid skill frontmatter")
        if "Output:" not in data and "**Output:**" not in data:
            problems.append(f"{skill.relative_to(root)}: missing execution output contract")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Markdown references and documented release controls")
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args()
    failures = validate(args.root.resolve())
    for failure in failures:
        print("DOC FAIL: " + failure, file=sys.stderr)
    if failures:
        return 1
    print(f"DOC PASS: {sum(1 for _ in markdown_files(args.root.resolve()))} Markdown files checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

