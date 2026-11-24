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


def write_private(path: Path, data: dict, *, force: bool) -> None:
    if path.exists():
        if not force:
            raise FileExistsError(f"refusing to overwrite {path}; use --force after review")
        if path.is_dir():
            raise IsADirectoryError(f"{path} is a directory")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)


def verifier_command(path: Path) -> str:
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

    print(f"wrote: {args.out} (mode 0600)")
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
