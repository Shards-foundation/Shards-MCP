#!/usr/bin/env python3
"""Generate credential-free MCP client setup data. Never installs or contacts a server."""
from __future__ import annotations

import argparse
import base64
import json
import shlex
from urllib.parse import quote, urlsplit
import sys


DEFAULT_ENDPOINT = "https://mcp.shardsinc.co.uk/mcp"
CLIENTS = ("cursor-app", "cursor-cli", "claude-code", "claude-desktop", "codex-app", "codex-cli", "chatgpt")


def validate_endpoint(value: str, *, allow_loopback: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("endpoint must be a nonempty URL without surrounding whitespace")
    if any(ord(ch) < 32 or ch == "\\" for ch in value):
        raise ValueError("endpoint contains unsafe characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint URL contains invalid authority or port") from exc
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or "?" in value or "#" in value
            or parsed.path != "/mcp" or not parsed.netloc or port == 0):
        raise ValueError("endpoint must have /mcp path and no credentials, query or fragment")
    local = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (allow_loopback and parsed.scheme == "http" and local):
        raise ValueError("HTTPS required; loopback HTTP requires --allow-loopback")
    return value


def configuration(client: str, endpoint: str) -> dict[str, object]:
    if client not in CLIENTS:
        raise ValueError("unsupported client")
    common = {
        "client": client, "endpoint": endpoint, "transport": "streamable-http",
        "secrets_embedded": False, "installed": False,
        "authenticated": False,
        "warning": "This generates local setup instructions, NOT a live test. Cloudflare edge private tools currently use scoped bearer credentials; OAuth client login is not implemented there.",
    }
    if client.startswith("cursor-"):
        server = {"shards": {"url": endpoint}}
        config = {"mcpServers": server}
        deeplink = "cursor://anysphere.cursor-deeplink/mcp/install?name=shards&config=" + quote(
            base64.b64encode(json.dumps(server, separators=(",", ":")).encode("utf-8")).decode("ascii"), safe=""
        )
        return {**common, "config": config, "install_url": deeplink,
                "instruction": "Use Cursor's MCP install link, review server permissions and independently verify tool calls."}
    if client == "claude-code":
        return {**common, "commands": [
            f"claude mcp add --transport http --scope user shards {shlex.quote(endpoint)}",
            "claude mcp list",
        ], "instruction": "Review commands; authentication must use the issuer/client mode supported by the deployed gateway."}
    if client.startswith("codex-"):
        return {**common, "commands": [
            f"codex mcp add shards --url {shlex.quote(endpoint)}",
            "codex mcp list",
        ], "instruction": "Only run 'codex mcp login shards' once the remote gateway implements supported OAuth."}
    if client == "claude-desktop":
        return {**common, "instruction": "Claude Desktop: open Settings/Connectors, add a custom remote MCP server, paste endpoint, then follow the supported auth flow."}
    return {**common, "instruction": "ChatGPT: add a custom MCP server in the supported plugin/developer interface, paste endpoint, and complete the available platform authorisation. Protected tools require OAuth support."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print audited client MCP configuration without modifying files")
    parser.add_argument("--client", choices=CLIENTS, required=True)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--allow-loopback", action="store_true")
    args = parser.parse_args(argv)
    try:
        endpoint = validate_endpoint(args.endpoint, allow_loopback=args.allow_loopback)
    except ValueError as exc:
        print(f"CONFIG BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(configuration(args.client, endpoint), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
