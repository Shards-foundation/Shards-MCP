#!/usr/bin/env python3
"""Fail-closed syntactic evidence assessment; never certifies production readiness.

An eligible receipt means only that all declared gates have cited evidence.
Actual proof, issuer controls and approvals MUST be independently verified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


PACKAGE = (
    "source_revision", "unit_tests", "protocol_e2e", "dependency_review",
    "artifact_integrity", "independent_review", "operator_approval",
)
HOSTED = PACKAGE + (
    "dns_tls", "oauth_e2e", "scope_denial", "tenant_isolation",
    "backup_restore", "audit_integrity", "observability", "incident_runbook",
)
VALID = {"PASS", "FAIL", "BLOCKED", "NOT_VERIFIED"}
SHA = re.compile(r"[0-9a-f]{40}\Z")


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def assess(data: Any, envelope: str) -> dict[str, Any]:
    required = PACKAGE if envelope == "package" else HOSTED
    reasons: list[str] = []
    if not isinstance(data, dict):
        return {"verdict": "NO_GO", "reasons": ["Receipt must be a JSON object"],
                "assurance": "Syntactic gate only; no evidence was verified independently"}
    revision = data.get("revision")
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        reasons.append("revision: require an exact 40-character commit SHA")
    if data.get("envelope") != envelope:
        reasons.append("envelope: input does not match requested assessment")
    gates = data.get("gates")
    if not isinstance(gates, dict):
        reasons.append("gates: missing object")
        gates = {}
    for key in required:
        item = gates.get(key)
        if not isinstance(item, dict):
            reasons.append(f"{key}: missing gate")
            continue
        status = item.get("status")
        if not isinstance(status, str) or status not in VALID:
            reasons.append(f"{key}: invalid/missing status")
        elif status != "PASS":
            reasons.append(f"{key}: {status}")
        evidence = item.get("evidence")
        if status == "PASS" and (
            not isinstance(evidence, list) or not evidence
            or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in evidence)
        ):
            reasons.append(f"{key}: PASS requires non-empty evidence references")
    return {
        "envelope": envelope, "revision": revision,
        "verdict": "NO_GO" if reasons else "ELIGIBLE_FOR_INDEPENDENT_REVIEW",
        "reasons": reasons,
        "gates_checked": list(required),
        "assurance": "Syntactic self-attestation only. Evidence links, side effects, identities and approvals NOT independently verified.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess release evidence receipts without external effects")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--envelope", choices=("package", "hosted"), required=True)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"verdict": "NO_GO", "reasons": [f"invalid receipt: {exc}"]}))
        return 2
    result = assess(data, args.envelope)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "ELIGIBLE_FOR_INDEPENDENT_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
