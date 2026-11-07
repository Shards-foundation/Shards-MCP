"""MCP stdio-to-HTTPS bridge for desktop and CLI agent runtimes.

No credentials are read from JSON-RPC messages: SHARDS_AGENT_TOKEN and
SHARDS_GATEWAY_URL are resolved from the local process environment.
All requests are sent to the existing authenticated gateway, avoiding
a second database writer or policy engine. Stdout is protocol-only.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .core import canonical
from .json_limits import enforce_json_depth
from .worker import AgentClient


def request_line(client: AgentClient, line: str) -> str | None:
    try:
        enforce_json_depth(line)
        payload = json.loads(line)
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise ValueError("invalid JSON-RPC request")
        if not isinstance(payload.get("method"), str):
            raise ValueError("missing JSON-RPC method")
    except (ValueError, json.JSONDecodeError, RecursionError):
        return canonical({"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": "Parse error"}})
    try:
        raw = canonical(payload).encode("utf-8")
    except (ValueError, RecursionError, TypeError):
        return canonical({"jsonrpc": "2.0", "id": payload.get("id"),
                          "error": {"code": -32600, "message": "Invalid JSON request"}})
    if len(raw) > 262144:
        return canonical({"jsonrpc": "2.0", "id": payload.get("id"),
                          "error": {"code": -32600, "message": "Request too large"}})
    req = Request(client.url + "/mcp", raw, headers={
        "Authorization": "Bearer " + client.token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }, method="POST")
    try:
        with client.opener.open(req, timeout=20) as response:
            if response.status == 202:
                return None
            result = response.read(262145)
            if len(result) > 262144:
                raise RuntimeError("gateway response exceeds maximum size")
            json.loads(result)
            return result.decode("utf-8")
    except (HTTPError, URLError, RuntimeError, ValueError) as exc:
        # Do not forward gateway response bodies or credentials to stdout.
        if "id" not in payload:
            return None
        code = -32603
        if isinstance(exc, HTTPError) and exc.code in (400, 406):
            code = -32602
        return canonical({"jsonrpc": "2.0", "id": payload.get("id"),
                          "error": {"code": code, "message": "Gateway request failed"}})


def main() -> None:
    client = AgentClient(os.getenv("SHARDS_GATEWAY_URL", "http://127.0.0.1:8787"),
                         os.getenv("SHARDS_AGENT_TOKEN", ""))
    for line in sys.stdin:
        if not line.strip():
            continue
        response = request_line(client, line)
        if response is not None:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
