#!/usr/bin/env python3
"""Generate one per-agent Shards-Kernel bridge credential without printing it.

The operator runs this on the protected Linux host. The script writes a 0600
JSON file containing the exact Worker actor-map entry and the kernel
``<actor>.<secret>`` bearer, then prints only a redacted fingerprint and a
local verifier command. It never prints the bearer secret, never contacts the
network and never writes to the Worker, D1, Cloudflare or the kernel.

The kernel's scrypt verifier must be computed inside the kernel environment;
this script intentionally does not reimplement that KDF.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import stat
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

TENANT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
AGENT_ID = re.compile(r"^[A-Za-z0-9_-]{12,90}$")
ACTOR = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_ACTORS = 2


def build_entry(tenant: str, agent_id: str, actor: str) -> dict:
    if not TENANT.fullmatch(tenant):
        raise ValueError("tenant must match ^[A-Za-z0-9_-]{1,64}$")
    if not AGENT_ID.fullmatch(agent_id):
        raise ValueError("agent_id must match ^[A-Za-z0-9_-]{12,90}$")
    if not ACTOR.fullmatch(actor):
        raise ValueError("actor must match ^[A-Za-z0-9_-]{1,128}$ and contain no dot")
    secret = secrets.token_urlsafe(48)
    if not 32 <= len(secret) <= 512 or any(ch.isspace() or ch == "." for ch in secret):
        raise ValueError("generated secret is not a safe kernel bearer component")
    token = f"{actor}.{secret}"
    if token.count(".") != 1 or len(token) > 640:
        raise ValueError("generated token is not a safe actor-labelled kernel bearer")
    return {
        "schema": "shards.kernel-bridge.agent.v1",
        "tenant": tenant,
        "agent_id": agent_id,
        "kernel_actor": actor,
        "kernel_token": token,
        "token_sha256": sha256(token.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "worker_actor_map_entry": {f"{tenant}/{agent_id}": {"actor": actor, "token": token}},
        "kernel_agent_entry": {
            "actor": actor,
            "token_scrypt": "REPLACE_WITH_SCRYPT_VERIFIER",
            "allowed_tools": ["github.issue.add_label"],
        },
        "note": (
            "Contains a bearer secret. Keep mode 0600, never commit it, and never "
            "paste this file or kernel_token into a model chat or issue."
        ),
    }


def _validate_output_path(path: Path) -> None:
    text = str(path)
    if not text or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("output path must be non-empty and contain no control characters")


def _lstat_or_none(path: Path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _check_target(path: Path, *, force: bool) -> None:
    info = _lstat_or_none(path)
    if info is None:
        return
    display = shlex.quote(str(path))
    if stat.S_ISLNK(info.st_mode):
        raise OSError(f"refusing to write through symlink {display}")
    if stat.S_ISDIR(info.st_mode):
        raise IsADirectoryError(f"{display} is a directory")
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"refusing to replace non-regular file {display}")
    if not force:
        raise FileExistsError(f"refusing to overwrite {display}; use --force after review")


def _fsync_directory(parent: Path) -> None:
    try:
        fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def write_private(path: Path, data: dict, *, force: bool) -> None:
    """Write atomically without ever unlinking the reviewed file first.

    The new credential is written to a same-directory 0600 temporary file,
    fsynced, and only then atomically renamed over the target. A failed write
    leaves the previous file byte-identical. Symlinks, including dangling
    symlinks, are rejected before any write.
    """
    _validate_output_path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir():
        raise NotADirectoryError(f"{shlex.quote(str(parent))} is not a directory")
    _check_target(path, force=force)

    temp_path = None
    fd = None
    try:
        for _ in range(32):
            candidate = parent / (".kernel-bridge-credential-" + secrets.token_hex(16) + ".tmp")
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                fd = os.open(candidate, flags, 0o600)
                temp_path = candidate
                break
            except FileExistsError:
                continue
        if fd is None or temp_path is None:
            raise OSError("could not create a unique temporary credential file")

        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = None
        with handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        # Revalidate immediately before the atomic operation. A symlink that
        # appeared after the first check is rejected rather than replaced.
        _check_target(path, force=force)
        if force:
            os.replace(temp_path, path)
            temp_path = None
        else:
            # os.replace always overwrites, so a concurrent file could be
            # clobbered after the check. A hard link is an atomic
            # create-if-absent and fails closed if the target now exists.
            try:
                os.link(temp_path, path, follow_symlinks=False)
            except FileExistsError:
                raise FileExistsError(
                    f"refusing to overwrite {shlex.quote(str(path))}; use --force after review"
                ) from None
            os.unlink(temp_path)
            temp_path = None
        _fsync_directory(parent)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def verifier_command(path: Path) -> str:
    _validate_output_path(path)
    code = (
        "import json,os;from pathlib import Path;"
        "from shards_kernel.integrations.auth import agent_token_kdf,resolve_agent_pepper;"
        f"d=json.loads(Path({json.dumps(str(path))}).read_text());"
        "print(agent_token_kdf(d['kernel_token'],"
        "resolve_agent_pepper(os.environ['SHARDS_KERNEL_AGENT_AUTH_PEPPER'])))"
    )
    return "python -c " + shlex.quote(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="exact D1 tenant id, e.g. shards-internal")
    parser.add_argument("--agent-id", required=True, help="exact enrolled D1 agent id")
    parser.add_argument("--actor", required=True, help="kernel actor label; no dot")
    parser.add_argument("--out", required=True, type=Path, help="0600 output file")
    parser.add_argument("--force", action="store_true", help="replace an existing reviewed file")
    args = parser.parse_args(argv)
    try:
        data = build_entry(args.tenant, args.agent_id, args.actor)
        write_private(args.out, data, force=args.force)
    except Exception as exc:  # noqa: BLE001 - operator-facing bounded error
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"wrote: {shlex.quote(str(args.out))} (mode 0600)")
    print(f"tenant: {args.tenant}")
    print(f"agent_id: {args.agent_id}")
    print(f"kernel_actor: {args.actor}")
    print(f"token_sha256: {data['token_sha256']}")
    print(f"redacted_token: {args.actor}.****")
    print(f"pilot_cap: {MAX_ACTORS} exact actor mappings; no wildcard")
    print("next: copy only worker_actor_map_entry into the KERNEL_ACTOR_MAP Worker secret.")
    print("      run the verifier command below in the kernel venv and place the verifier")
    print("      in the signed kernel config; never print or paste kernel_token.")
    print(f"verifier_command: {verifier_command(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
