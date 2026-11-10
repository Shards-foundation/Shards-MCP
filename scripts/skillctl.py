#!/usr/bin/env python3
"""Read-only Shards Agent Skills discovery and structural validation.

Does not invoke skill scripts, make network calls or issue credentials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
CATEGORIES = {"intake", "identity", "connectivity", "execution", "engineering", "governance", "operations", "distribution"}
RISKS = {"low", "bounded", "privileged"}


def load_catalog(root: Path) -> dict[str, Any]:
    catalog = root / "skills" / "catalog.json"
    with catalog.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("skills"), list):
        raise ValueError("skills/catalog.json: unsupported catalog format")
    return value


def frontmatter(text: str) -> dict[str, str]:
    match = FRONT.match(text)
    if not match:
        raise ValueError("missing YAML frontmatter delimited by ---")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parsed = re.fullmatch(r"([a-z][a-z0-9_-]*):\s*(\S.*?)\s*", line)
        if not parsed:
            raise ValueError("only populated scalar frontmatter fields are supported")
        key, value = parsed.groups()
        if key in fields:
            raise ValueError(f"duplicate field {key}")
        fields[key] = value.strip().strip('"').strip("'")
    return fields


def safe_script(root: Path, value: str) -> bool:
    if not isinstance(value, str) or "\\" in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("..", ".") for part in path.parts):
        return False
    candidate = root.joinpath(*path.parts)
    if candidate.is_symlink() or not candidate.is_file():
        return False
    return candidate.resolve().is_relative_to(root.resolve())


def validate(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    try:
        data = load_catalog(root)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return [f"catalog unavailable: {exc}"]
    entries: list[Any] = data["skills"]
    seen: set[str] = set()
    for index, record in enumerate(entries):
        if not isinstance(record, dict):
            errors.append(f"record {index}: expected object")
            continue
        name = record.get("id")
        if not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name):
            errors.append(f"record {index}: invalid skill id")
            continue
        if name in seen:
            errors.append(f"{name}: duplicate catalog entry")
            continue
        seen.add(name)
        if not isinstance(record.get("category"), str) or record["category"] not in CATEGORIES:
            errors.append(f"{name}: invalid category")
        if not isinstance(record.get("risk"), str) or record["risk"] not in RISKS:
            errors.append(f"{name}: invalid risk class")
        triggers = record.get("triggers")
        if not isinstance(triggers, list) or not triggers or any(
            not isinstance(t, str) or not t.strip() or len(t) > 100 for t in triggers
        ):
            errors.append(f"{name}: invalid trigger list")
        scripts = record.get("scripts")
        if not isinstance(scripts, list) or any(not safe_script(root, p) for p in scripts):
            errors.append(f"{name}: missing or unsafe script reference")
        path = root / "skills" / name / "SKILL.md"
        if not path.is_file() or path.is_symlink():
            errors.append(f"{name}: missing skill instructions")
            continue
        try:
            text = path.read_text(encoding="utf-8")
            fields = frontmatter(text)
        except (ValueError, OSError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if fields.get("name") != name:
            errors.append(f"{name}: skill metadata must match directory/catalog id")
        description = fields.get("description", "")
        if not 1 <= len(description) <= 1024:
            errors.append(f"{name}: description must contain 1–1024 characters")
        if not re.search(r"(?m)^#\s+\S+", text):
            errors.append(f"{name}: missing primary heading")
        if "Output:" not in text and "**Output:**" not in text:
            errors.append(f"{name}: missing output contract")
    discovered = {p.parent.name for p in (root / "skills").glob("*/SKILL.md")}
    for extra in sorted(discovered - seen):
        errors.append(f"{extra}: skill lacks catalog entry")
    for missing in sorted(seen - discovered):
        if not any(e.startswith(f"{missing}: missing skill") for e in errors):
            errors.append(f"{missing}: skill file undiscoverable")
    if not entries:
        errors.append("catalog must contain at least one skill")
    return sorted(set(errors))


def suggest(task: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lexical hints only. Equal scores intentionally retain multiple choices."""
    query = task.lower().strip()
    words = set(re.findall(r"[a-z0-9]+", query)) - {"the", "and", "with", "for", "please", "shards", "mcp", "want", "need"}
    scored = []
    for row in entries:
        score = 0
        matched = []
        for trigger in row["triggers"]:
            phrase = trigger.lower()
            tokens = set(re.findall(r"[a-z0-9]+", phrase)) - {"mcp"}
            if phrase in query:
                new_score = len(tokens) + 3
            elif tokens and words:
                new_score = len(tokens & words)
            else:
                new_score = 0
            if new_score > 0:
                matched.append(trigger)
            score = max(score, new_score)
        if score:
            scored.append({"id": row["id"], "score": score, "matched": matched})
    return sorted(scored, key=lambda item: (-item["score"], item["id"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover, inspect and validate local Shards skills")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository checkout root")
    actions = parser.add_subparsers(dest="action", required=True)
    for command in ("list", "validate"):
        sub = actions.add_parser(command)
        sub.add_argument("--json", action="store_true")
    show = actions.add_parser("show")
    show.add_argument("name")
    rec = actions.add_parser("suggest")
    rec.add_argument("--task", required=True)
    rec.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    faults = validate(root)
    if args.action == "validate":
        if args.json:
            print(json.dumps({"ok": not faults, "errors": faults}, indent=2))
        else:
            print("SKILLS PASS" if not faults else "\n".join("SKILLS FAIL: " + p for p in faults))
        return 0 if not faults else 2
    if faults:
        print("\n".join("SKILLS FAIL: " + p for p in faults), file=sys.stderr)
        return 2
    records = load_catalog(root)["skills"]
    if args.action == "list":
        if args.json:
            print(json.dumps({"skills": records}, indent=2))
        else:
            for item in records:
                print(f"{item['id']:<22} {item['risk']:<10} {item['category']:<15} {', '.join(item['triggers'][:2])}")
        return 0
    if args.action == "show":
        if not NAME.fullmatch(args.name):
            print("Invalid skill name", file=sys.stderr)
            return 2
        if args.name not in {entry["id"] for entry in records}:
            print("Unknown skill; run 'list'", file=sys.stderr)
            return 2
        print((root / "skills" / args.name / "SKILL.md").read_text(encoding="utf-8"))
        return 0
    matches = suggest(args.task, records)
    top = matches[0]["score"] if matches else 0
    shortlisted = [row for row in matches if row["score"] == top]
    ambiguity = len(shortlisted) > 1
    if args.json:
        print(json.dumps({"matches": matches, "ambiguous": ambiguity, "selected": shortlisted[0]["id"] if len(shortlisted) == 1 else None}, indent=2))
    elif not matches:
        print("NO_MATCH: consult skills/MAP.md", file=sys.stderr)
    else:
        print(("AMBIGUOUS: " if ambiguity else "SUGGESTED: ") + ", ".join(row["id"] for row in shortlisted))
        for row in matches[:5]:
            print(f"  {row['id']}: score={row['score']} triggers={', '.join(row['matched'])}")
    return 0 if matches and not ambiguity else 2


if __name__ == "__main__":
    raise SystemExit(main())
