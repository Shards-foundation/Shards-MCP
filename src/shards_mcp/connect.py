"""Explicit local installer for the public Shards MCP edge endpoint.

No dependency on an OAuth client or LLM application internals. Uses the MCP
client's native config/CLI, never handles secrets, and fails without --install.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request

DEFAULT_URL = "https://mcp.shardsinc.co.uk/mcp"


def install_cursor(path: Path, *, url: str = DEFAULT_URL) -> str:
    """Merge one MCP entry; don't overwrite unrelated existing MCP servers.

    Refuse symlinks and unsafe/non-object configs. Back up existing files
    before atomic 0600 replacement. Caller must explicitly opt in.
    """
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing to overwrite an MCP config symlink")
    if path.exists():
        if not path.is_file():
            raise ValueError("MCP config path is not a regular file")
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Existing MCP config cannot be parsed; refusing overwrite") from exc
        if not isinstance(existing, dict):
            raise ValueError("Existing MCP config must be a JSON object")
    else:
        existing = {}
    servers = existing.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be a JSON object")
    current = servers.get("shards-mcp")
    wanted = {"url": url}
    if current is not None and current != wanted:
        raise ValueError("A different shards-mcp entry exists; refusing to replace it")
    if current == wanted:
        return "already configured"

    existing["mcpServers"] = dict(servers, **{"shards-mcp": wanted})
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists() or backup.is_symlink():
            raise ValueError("Backup already exists; move it before retrying")
        shutil.copy2(path, backup, follow_symlinks=False)
        if os.name == "posix":
            backup.chmod(0o600)

    fd, temp = tempfile.mkstemp(prefix=".mcp-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(path)


def verify_endpoint(url: str = DEFAULT_URL) -> dict:
    """Perform a non-mutating, anonymous, real remote MCP initialize call."""
    import urllib.parse

    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Verification requires a public HTTPS MCP endpoint")
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "shards-mcp-connect", "version": "0.1.0"}}
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "shards-mcp-connect/0.1"
    })
    with urllib.request.urlopen(req, timeout=12) as response:
        if response.geturl() != url:
            raise ValueError("Refusing redirected MCP endpoint")
        payload = response.read(16384)
    parsed = json.loads(payload)
    result = parsed.get("result", {})
    if not isinstance(result, dict) or result.get("serverInfo", {}).get("name") != "shards-mcp-edge":
        raise ValueError("Endpoint did not return the expected Shards MCP server identity")
    return {
        "server": result["serverInfo"]["name"],
        "version": result["serverInfo"].get("version"),
        "protocol": result.get("protocolVersion"),
        "endpoint": url,
    }


def _client_command(client: str, url: str) -> list[str] | None:
    if client == "claude-code":
        return ["claude", "mcp", "add", "--transport", "http", "shards-mcp", url]
    if client in {"codex-app", "codex-cli"}:
        return ["codex", "mcp", "add", "shards-mcp", "--url", url]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the actual Shards MCP Streamable HTTP endpoint in a supported local MCP client."
    )
    parser.add_argument("--client", required=True, choices=(
        "claude-desktop", "claude-code", "chatgpt",
        "codex-app", "codex-cli", "cursor-app", "cursor-cli"
    ))
    parser.add_argument("--install", action="store_true", help="Explicitly make client-local changes")
    parser.add_argument("--verify", action="store_true", help="Read-only remote MCP handshake")
    parser.add_argument("--scope", choices=("user", "project"), default="user",
                        help="Cursor only; default global ~/.cursor/mcp.json")
    parser.add_argument("--endpoint", default=DEFAULT_URL)
    args = parser.parse_args(argv)

    import urllib.parse
    u = urllib.parse.urlsplit(args.endpoint)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        parser.error("MCP URL must be HTTPS with no userinfo, query, or fragment")
    if args.verify:
        try:
            print(json.dumps(verify_endpoint(args.endpoint), indent=2))
        except Exception as exc:
            print("MCP verification FAILED: " + str(exc), file=sys.stderr)
            return 1
    if not args.install:
        print("Read-only by default. To install, append --install.")
        cmd = _client_command(args.client, args.endpoint)
        if cmd:
            print("Command:", " ".join(cmd))
        elif args.client in {"cursor-app", "cursor-cli"}:
            print("Target: ~/.cursor/mcp.json (or .cursor/mcp.json with --scope project)")
        else:
            print("Use https://mcp.shardsinc.co.uk for guided setup in your client.")
        return 0

    if args.client in {"cursor-app", "cursor-cli"}:
        path = (Path.home() / ".cursor" / "mcp.json") if args.scope == "user" else (Path.cwd() / ".cursor" / "mcp.json")
        try:
            print("Cursor configuration:", install_cursor(path, url=args.endpoint))
            print("Confirm under Cursor Customize > MCP or 'agent mcp list'.")
            return 0
        except (ValueError, OSError) as exc:
            print("Installation refused: " + str(exc), file=sys.stderr)
            return 1

    cmd = _client_command(args.client, args.endpoint)
    if cmd:
        if not shutil.which(cmd[0]):
            print("Client executable not installed: " + cmd[0], file=sys.stderr)
            return 1
        print("Running native client installer:", " ".join(cmd))
        try:
            done = subprocess.run(cmd, check=False, timeout=45)
            return done.returncode
        except (subprocess.TimeoutExpired, OSError) as exc:
            print("Native MCP install failed: " + str(exc), file=sys.stderr)
            return 1

    print(
        "No supported silent installer exists for this cloud client. "
        "Open https://mcp.shardsinc.co.uk and complete its official setup UI. "
        "No local files were changed.",
        file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
