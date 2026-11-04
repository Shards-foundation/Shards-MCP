"""Local-only, consistent SQLite snapshots and offline verification.

A snapshot is state recovery, NOT rollback of external agent side-effects.
Never expose snapshot/restore as MCP, REST, or A2A tools.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

from .core import Gateway, GatewayError, Principal, canonical


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_snapshot(path: str) -> dict[str, Any]:
    """Verify consistency, referential integrity and the internal audit chain.

    A compromised database owner can reconstruct the internal hash chain. This
    check cannot replace an independent immutable external audit anchor.
    """
    target = Path(path).expanduser()
    if not target.is_file() or target.is_symlink():
        raise GatewayError("snapshot must be an existing regular file")
    # Percent-encode URL special characters to enforce immutable mode=ro.
    uri = "file:" + quote(str(target.resolve()), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            integrity = db.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise GatewayError("snapshot SQLite integrity check failed", "CONFLICT")
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise GatewayError("snapshot has foreign key violations", "CONFLICT")
            previous = "0" * 64
            count = 0
            for row in db.execute("SELECT * FROM audit ORDER BY seq"):
                record = {"at": row["at"], "actor": row["actor"], "action": row["action"],
                          "subject": row["subject"], "details": json.loads(row["details"])}
                expected = hashlib.sha256((previous + canonical(record)).encode()).hexdigest()
                if row["previous_hash"] != previous or row["entry_hash"] != expected:
                    raise GatewayError("snapshot audit hash chain mismatch", "CONFLICT")
                previous = expected
                count += 1
            required = ("agents", "messages", "tasks", "checkpoints", "events",
                        "schedules", "verifications")
            totals = {table: int(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
                      for table in required}
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise GatewayError("snapshot verification failed", "CONFLICT") from exc
    return {
        "valid": True, "sha256": _digest(target), "bytes": target.stat().st_size,
        "audit_entries": count, "audit_head": previous, "records": totals,
    }


def create_snapshot(gateway: Gateway, principal: Principal, output: str) -> dict[str, Any]:
    """Exclusively create a 0600 snapshot using SQLite's live backup API."""
    principal.require("*")
    path = Path(output).expanduser().absolute()
    if path.resolve() == Path(gateway.path):
        raise GatewayError("snapshot target cannot be active database")
    if not path.parent.is_dir():
        raise GatewayError("snapshot parent directory must already exist")
    # Avoid writing secrets into attacker-writable directories (including /tmp).
    if os.name == "posix" and path.parent.stat().st_mode & 0o022:
        raise GatewayError("snapshot destination directory must be owner-only")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise GatewayError("cannot create exclusive snapshot file", "CONFLICT") from exc
    os.close(fd)
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
        with gateway.read_tx() as source, sqlite3.connect(str(path), timeout=10) as destination:
            source.backup(destination, pages=64, sleep=0.05)
        result = inspect_snapshot(str(path))
        # Record a successful snapshot event, but do not persist the private
        # absolute path or claim the audit entry itself was included in backup.
        with gateway.tx() as db:
            gateway.audit(db, principal.agent_id, "snapshot.created",
                          result["sha256"], {"size_bytes": result["bytes"],
                                             "audit_head": result["audit_head"]})
        return {**result, "output": str(path)}
    except BaseException:
        # An incomplete snapshot must never masquerade as a valid recovery point.
        try:
            path.unlink()
        except OSError:
            pass
        raise
