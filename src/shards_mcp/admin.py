"""Local-only, out-of-band agent credential provisioning.

No credential is returned through MCP or generic REST. A registered bearer
credential is written only to a new 0600 file controlled by the operator.
The bootstrap secret is supplied via SHARDS_ADMIN_TOKEN (never CLI argv).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .core import Gateway, GatewayError, SCOPES


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="shards-mcp-admin",
        description="Offline management of Shards gateway agent identities")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("register", help="Create an agent and write the token to a new protected file")
    create.add_argument("--name", required=True)
    create.add_argument("--provider", required=True)
    create.add_argument("--scope", choices=SCOPES, action="append", required=True)
    create.add_argument("--capability", action="append", default=[])
    create.add_argument("--token-file", required=True)
    revoke = sub.add_parser("revoke", help="Revoke an agent ID")
    revoke.add_argument("agent_id")
    sub.add_parser("list", help="List agent IDs and scopes without tokens")
    args = parser.parse_args()

    admin_token = os.getenv("SHARDS_ADMIN_TOKEN", "")
    if not admin_token:
        parser.error("SHARDS_ADMIN_TOKEN must be supplied through the environment or secrets manager")
    gateway = Gateway(os.getenv("SHARDS_DB", "shards.db"), admin_token)
    root = gateway.authenticate(admin_token)

    try:
        if args.action == "register":
            token_path = Path(args.token_file).expanduser()
            if token_path.is_symlink():
                raise GatewayError("token-file path must not be a symbolic link")
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(token_path), flags, 0o600)
            agent_id = None
            try:
                created = gateway.register(root, args.name, args.provider, args.capability, args.scope)
                agent_id = created["agent_id"]
                token = (created["token"] + "\n").encode("ascii")
                with os.fdopen(fd, "wb") as stream:
                    fd = -1
                    stream.write(token)
                    stream.flush()
                    os.fsync(stream.fileno())
                print(json.dumps({"agent_id": agent_id, "scopes": created["scopes"],
                                  "token_file": str(token_path)}, sort_keys=True))
            except BaseException:
                if fd != -1:
                    os.close(fd)
                if agent_id:
                    gateway.revoke(root, agent_id)
                try:
                    token_path.unlink()
                except OSError:
                    pass
                raise
        elif args.action == "revoke":
            print(json.dumps(gateway.revoke(root, args.agent_id)))
        else:
            print(json.dumps(gateway.agents(root), sort_keys=True))
    except (GatewayError, OSError, ValueError) as exc:
        print(f"shards-mcp-admin: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
