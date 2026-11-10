#!/usr/bin/env python3
"""Explicit, no-overwrite local Agent Skills installer. No network or tool execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIRS = {"codex": (".agents", "skills"), "cursor": (".cursor", "skills"),
               "claude": (".claude", "skills")}
ALLOWED = {"scripts", "references", "assets"}
MANIFEST = ".shards-skill-manifest.json"


def load_catalog(root: Path) -> dict[str, Any]:
    data = json.loads((root / "skills/catalog.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise ValueError("Invalid skills catalog")
    return {e["id"]: e for e in data["skills"] if isinstance(e, dict)
            and isinstance(e.get("id"), str)}


def source_hashes(root: Path, name: str) -> dict[str, str]:
    if name not in load_catalog(root) or not name or len(name) > 64 or any(
            ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in name):
        raise ValueError("Unknown or invalid skill: " + name)
    src = root / "skills" / name
    if src.is_symlink() or not src.is_dir():
        raise ValueError(f"{name}: source directory missing or symlinked")
    found: dict[str, str] = {}
    total = 0
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        if item.is_symlink():
            raise ValueError(f"{name}: symlink in skill content: {rel}")
        if item.is_dir():
            continue
        if not item.is_file() or (rel.as_posix() != "SKILL.md"
                                  and (rel.parts[0] not in ALLOWED or len(rel.parts) < 2
                                       or any(p.startswith(".") for p in rel.parts))):
            raise ValueError(f"{name}: unsupported skill file: {rel}")
        size = item.stat().st_size
        total += size
        if size > 512 * 1024 or total > 2 * 1024 * 1024 or len(found) >= 100:
            raise ValueError(f"{name}: skill exceeds resource caps")
        found[rel.as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    if "SKILL.md" not in found:
        raise ValueError(f"{name}: missing SKILL.md")
    return found


def destination(client: str, scope: str, project_dir: Path | None,
                home: Path | None = None) -> Path:
    if client not in CLIENT_DIRS:
        raise ValueError("Unsupported client")
    if scope == "project":
        if not project_dir or project_dir.is_symlink() or not project_dir.is_dir():
            raise ValueError("Existing non-symlink --project-dir is required")
        base = project_dir.resolve()
    elif scope == "user":
        if project_dir is not None:
            raise ValueError("--project-dir cannot be used with user scope")
        base = (home or Path.home()).resolve()
        if not base.is_dir():
            raise ValueError("User home directory missing")
    else:
        raise ValueError("Unsupported scope")
    cursor = base
    for part in CLIENT_DIRS[client]:
        cursor = cursor / part
        if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
            raise ValueError("Refusing non-directory or symlink in destination")
    return cursor


def verify_skill(path: Path, name: str) -> list[str]:
    if path.is_symlink() or not path.is_dir():
        return [f"{name}: skill directory missing or symlinked"]
    manifest = path / MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        return [f"{name}: manifest missing or symlinked"]
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return [f"{name}: malformed manifest"]
    if not isinstance(data, dict) or data.get("skill") != name or data.get("schema_version") != 1:
        return [f"{name}: invalid manifest metadata"]
    files = data.get("files")
    if not isinstance(files, dict) or "SKILL.md" not in files:
        return [f"{name}: invalid manifest file list"]
    expected = {MANIFEST}
    errors = []
    for rel, digest in files.items():
        if not isinstance(rel, str) or not isinstance(digest, str) or len(digest) != 64:
            errors.append(f"{name}: invalid manifest entry")
            continue
        components = Path(rel).parts
        if (Path(rel).is_absolute() or "\\" in rel or any(p in {".", ".."} for p in components)
                or (rel != "SKILL.md" and (not components or components[0] not in ALLOWED))):
            errors.append(f"{name}: unsafe manifest path")
            continue
        expected.add(rel)
        file = path / rel
        if file.is_symlink() or not file.is_file():
            errors.append(f"{name}: file absent or symlinked: {rel}")
        elif hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            errors.append(f"{name}: checksum mismatch: {rel}")
    for item in path.rglob("*"):
        if item.is_symlink() or (item.is_file() and item.relative_to(path).as_posix() not in expected):
            errors.append(f"{name}: unexpected installed file or symlink")
    return sorted(set(errors))


def write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def copy_skill(source: Path, target: Path, name: str, hashes: dict[str, str]) -> None:
    target.mkdir(mode=0o755, exist_ok=False)
    try:
        # Supporting files first; write the discovery entry SKILL.md last.
        for rel in sorted(hashes, key=lambda r: (r == "SKILL.md", r)):
            current = source / rel
            if current.is_symlink():
                raise ValueError(f"{name}: source changed since planning")
            content = current.read_bytes()
            if hashlib.sha256(content).hexdigest() != hashes[rel]:
                raise ValueError(f"{name}: source changed since planning")
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_exclusive(dest, content)
        receipt = {"schema_version": 1, "skill": name,
                   "source": "Shards-foundation/Shards-MCP",
                   "files": hashes, "execution": "none", "credentials": "none"}
        write_exclusive(target / MANIFEST, (json.dumps(receipt, indent=2) + "\n").encode())
        errors = verify_skill(target, name)
        if errors:
            raise ValueError("; ".join(errors))
    except BaseException:
        shutil.rmtree(target)
        raise


def execute(root: Path, client: str, scope: str, project_dir: Path | None,
            names: list[str], *, apply: bool = False,
            verify: bool = False, home: Path | None = None) -> dict[str, Any]:
    if apply and verify:
        raise ValueError("--apply and --verify are mutually exclusive")
    if not names:
        names = ["get-started"]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate skill selection")
    target = destination(client, scope, project_dir, home)
    checked = {name: source_hashes(root, name) for name in names}
    if verify:
        failures = [e for name in names for e in verify_skill(target / name, name)]
        return {"ok": not failures, "action": "VERIFY", "errors": failures, "files_written": 0}
    conflicts = [name for name in names if (target / name).exists() or (target / name).is_symlink()]
    report: dict[str, Any] = {
        "ok": not conflicts, "action": "APPLY" if apply else "PLAN",
        "client": client, "scope": scope, "destination": str(target),
        "skills": [{"name": name, "files": checked[name]} for name in names],
        "errors": [f"{name}: already exists (no overwrite)" for name in conflicts],
        "files_written": 0, "credentials_used": False, "network_calls": 0,
    }
    if not apply or conflicts:
        return report
    target.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for name, hashes in checked.items():
            dst = target / name
            copy_skill(root / "skills" / name, dst, name, hashes)
            created.append(dst)
            report["files_written"] += len(hashes) + 1
    except (OSError, ValueError):
        for dst in reversed(created):
            shutil.rmtree(dst)
        raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="No-overwrite Shards Agent Skills copy utility")
    parser.add_argument("--client", choices=sorted(CLIENT_DIRS), required=True)
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--skill", dest="skills", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.root)
        if args.all and args.skills:
            raise ValueError("Cannot combine --all and --skill")
        names = sorted(catalog) if args.all else args.skills
        report = execute(args.root, args.client, args.scope, args.project_dir, names,
                         apply=args.apply, verify=args.verify)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"ok": False, "action": "BLOCKED",
                          "errors": [str(exc)], "files_written": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
