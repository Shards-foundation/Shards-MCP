"""Read-only connection diagnostic for scoped Shards MCP clients.

Three read-only MCP method calls plus the initialized lifecycle notification. It never
provisions identities, modifies tasks, publishes events or executes a worker.
HTTPS is required off loopback, redirects and proxies are disabled, and
sensitive transport details are deliberately omitted from error messages.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from http.client import HTTPException
import stat
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from .core import canonical
from .json_limits import enforce_json_depth
from .server import MCP_PROTOCOL_VERSION, reject_nonfinite, reject_overflowing_float, reject_duplicate_properties
from .worker import AgentClient


MAX_RESPONSE_BYTES = 262144


class DiagnosticError(Exception):
    """Stable, secret-free error for automation and local operators."""


def read_agent_token(filename: str | None = None) -> str:
    """Load one scoped credential, failing closed on ambiguous sources."""
    direct = os.getenv("SHARDS_AGENT_TOKEN", "")
    source = filename or os.getenv("SHARDS_AGENT_TOKEN_FILE", "")
    if direct and source:
        raise DiagnosticError("configure only one agent-token source")
    if source:
        path = Path(source).expanduser()
        if path.is_symlink():
            raise DiagnosticError("agent token file must not be a symlink")
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise DiagnosticError("agent token must be a regular file of at most 4096 bytes")
            if os.name == "posix" and info.st_mode & 0o077:
                raise DiagnosticError("agent token file must not be group/world accessible")
            with os.fdopen(fd, "r", encoding="ascii") as stream:
                fd = -1
                token = stream.read(4097).strip()
        finally:
            if fd != -1:
                os.close(fd)
    else:
        token = direct
    if len(token) < 32:
        raise DiagnosticError("a scoped agent token of at least 32 characters is required")
    return token


def _validate_gateway_url(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme not in ("http", "https") or not parts.hostname or
            parts.username or parts.password or parts.query or parts.fragment or
            parts.path not in ("", "/")):
        raise DiagnosticError("gateway URL must be an origin without credentials, query, or path")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise DiagnosticError("remote gateway requires HTTPS")
    return value.rstrip("/")


def _request(client: AgentClient, payload: dict[str, Any]) -> Request:
    """Prepare a single MCP POST without leaking or redirecting bearer tokens."""
    return Request(
        client.url + "/mcp", canonical(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + client.token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        },
        method="POST",
    )


def _initialized(client: AgentClient, timeout: float) -> None:
    """Complete MCP initialization before any tool discovery or execution."""
    req = _request(client, {
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })
    try:
        with client.opener.open(req, timeout=timeout) as response:
            if response.status not in (202, 204):
                raise DiagnosticError("MCP initialization notification not accepted")
            if response.read(1):
                raise DiagnosticError("MCP notification unexpectedly returned data")
    except HTTPError as exc:
        raise DiagnosticError("MCP initialization notification rejected (HTTP %d)" % exc.code) from None
    except (URLError, TimeoutError, OSError, RuntimeError, HTTPException):
        raise DiagnosticError("MCP transport unavailable or refused") from None


def _rpc(client: AgentClient, request_id: int, method: str,
         params: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = _request(client, {
        "jsonrpc": "2.0", "id": request_id,
        "method": method, "params": params,
    })
    try:
        with client.opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise DiagnosticError("unexpected MCP HTTP status")
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                raise DiagnosticError("MCP gateway did not return JSON")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise DiagnosticError("MCP gateway rejected request (HTTP %d)" % exc.code) from None
    except (URLError, TimeoutError, OSError, RuntimeError, HTTPException):
        raise DiagnosticError("MCP transport unavailable or refused") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DiagnosticError("MCP response exceeds maximum size")
    try:
        text = raw.decode("utf-8")
        enforce_json_depth(text)
        answer = json.loads(
            text, parse_constant=reject_nonfinite,
            parse_float=reject_overflowing_float,
            object_pairs_hook=reject_duplicate_properties,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise DiagnosticError("MCP response is invalid JSON") from None
    if (not isinstance(answer, dict) or answer.get("jsonrpc") != "2.0" or
            type(answer.get("id")) is not int or answer["id"] != request_id):
        raise DiagnosticError("invalid MCP JSON-RPC response envelope")
    if "error" in answer:
        err = answer["error"]
        code = err.get("code") if isinstance(err, dict) else None
        if type(code) is int:
            raise DiagnosticError("MCP method rejected (JSON-RPC %d)" % code)
        raise DiagnosticError("MCP method rejected")
    if not isinstance(answer.get("result"), dict):
        raise DiagnosticError("MCP method returned an invalid result")
    return answer["result"]


def diagnose(url: str, token: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Verify three read-only protocol interactions on the actual MCP transport."""
    if not isinstance(timeout, (int, float)) or type(timeout) is bool:
        raise DiagnosticError("timeout must be a finite number of seconds")
    timeout = float(timeout)
    if not math.isfinite(timeout) or not 1 <= timeout <= 30:
        raise DiagnosticError("timeout must be between 1 and 30 seconds")
    origin = _validate_gateway_url(url)
    try:
        client = AgentClient(origin, token)
    except ValueError:
        raise DiagnosticError("invalid agent credential or gateway address") from None
    started = time.monotonic()
    initialise = _rpc(client, 1, "initialize", {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "shards-mcp-doctor", "version": "0.1.0"},
    }, timeout)
    if initialise.get("protocolVersion") != MCP_PROTOCOL_VERSION:
        raise DiagnosticError("gateway negotiated an unsupported MCP version")
    info = initialise.get("serverInfo")
    if not isinstance(info, dict) or info.get("name") != "shards-mcp":
        raise DiagnosticError("unexpected MCP server identity")
    _initialized(client, timeout)
    listed = _rpc(client, 2, "tools/list", {}, timeout)
    tools = listed.get("tools")
    if not isinstance(tools, list) or len(tools) > 200:
        raise DiagnosticError("invalid MCP tool manifest")
    names = []
    for entry in tools:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise DiagnosticError("invalid MCP tool manifest")
        names.append(entry["name"])
    if len(names) != len(set(names)) or "agent_identity" not in names:
        raise DiagnosticError("MCP tool discovery is incomplete or ambiguous")
    call = _rpc(client, 3, "tools/call", {
        "name": "agent_identity", "arguments": {},
    }, timeout)
    if call.get("isError") is not False:
        raise DiagnosticError("agent identity tool denied")
    ident = call.get("structuredContent")
    if not isinstance(ident, dict):
        raise DiagnosticError("agent identity result is not structured")
    if (not isinstance(ident.get("agent_id"), str) or
            not ident["agent_id"].startswith("agt_") or
            ident.get("role") != "agent" or
            not isinstance(ident.get("scopes"), list) or
            any(not isinstance(x, str) for x in ident["scopes"])):
        raise DiagnosticError("credential is not a valid scoped agent identity")
    report = {
        "ok": True,
        "transport": "streamable-http",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "server_name": info["name"],
        "server_version": str(info.get("version", "")),
        "agent_id": ident["agent_id"],
        "scopes": sorted(ident["scopes"]),
        "tool_count": len(names),
        "tool_names": sorted(names),
        "round_trip_ms": round((time.monotonic() - started) * 1000, 2),
    }
    # Server metadata and tool names are untrusted even after a valid identity
    # response: a compromised endpoint could reflect the bearer credential
    # outside the identity tool result. Reject the entire output atomically.
    if token in canonical(report):
        raise DiagnosticError("gateway reflected an agent credential")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Shards-MCP client interoperability diagnostic"
    )
    parser.add_argument(
        "--url", default=os.getenv("SHARDS_GATEWAY_URL", "http://127.0.0.1:8787"),
        help="Gateway origin; HTTPS required off loopback",
    )
    parser.add_argument("--token-file", help="Private file containing scoped agent token")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    try:
        token = read_agent_token(args.token_file)
        report = diagnose(args.url, token, timeout=args.timeout)
    except (DiagnosticError, ValueError, OSError, UnicodeError) as exc:
        # Avoid exception repr/tracebacks/remote response bodies to prevent
        # inadvertent disclosure of agent tokens or untrusted server content.
        message = str(exc) if isinstance(exc, DiagnosticError) else "invalid local credential configuration"
        if args.json:
            print(canonical({"ok": False, "error": message}))
        else:
            print("Shards MCP diagnostic: FAIL — " + message, file=sys.stderr)
        return 1
    if args.json:
        print(canonical(report))
    else:
        print("Shards MCP diagnostic: PASS")
        print("Protocol: " + report["protocol_version"])
        print("Server: " + report["server_name"] + " " + report["server_version"])
        print("Agent: " + report["agent_id"])
        print("Scoped tools: " + str(report["tool_count"]))
        print("Round trip: " + str(report["round_trip_ms"]) + " ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
