#!/usr/bin/env python3
"""Zero-network, zero-write Shards-MCP developer/agent onboarding preflight."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[3]


def inspect(root: Path) -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {}
    checks["python_311"] = {"status": "PASS" if sys.version_info >= (3, 11) else "BLOCKED",
                           "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"}
    for name, relative in (
        ("agent_contract", "AGENTS.md"),
        ("skills_catalog", "skills/catalog.json"),
        ("quickstart", "docs/getting-started.md"),
    ):
        checks[name] = {"status": "PASS" if (root / relative).is_file() else "BLOCKED",
                        "detail": relative}
    try:
        spec = importlib.util.find_spec("shards_mcp")
        installed = spec is not None
    except (ValueError, ModuleNotFoundError):
        installed = False
    checks["package_importable"] = {"status": "PASS" if installed else "BLOCKED",
                                    "detail": "shards_mcp import discovered" if installed else "Install this checkout in a virtual environment"}
    for cmd in ("shards-mcp", "shards-mcp-doctor"):
        checks[cmd] = {"status": "PASS" if shutil.which(cmd) else "BLOCKED",
                       "detail": "command on PATH" if shutil.which(cmd) else "command unavailable"}
    # Do not expose environment values, secrets, hostnames or user-specific paths.
    blocked = [name for name, item in checks.items() if item["status"] != "PASS"]
    return {"state": "READY_LOCAL" if not blocked else "BLOCKED",
            "checks": checks, "blocked": blocked,
            "network_calls": 0, "files_written": 0,
            "scope": "developer tooling only; not a deployed MCP, OAuth or hosted service test"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Shards first-run environment report")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit 2 when prerequisites are blocked")
    args = parser.parse_args(argv)
    report = inspect(args.root.resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report["state"] + ": " + ", ".join(report["blocked"]))
    return 2 if args.strict and report["state"] != "READY_LOCAL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
