"""Stateless tool-only MCP 2026-07-28 adapter.

This is a second wire era, not a replacement for the legacy 2025-11-25
handshake. Each request is authenticated independently by the existing HTTP
resource server. Tool execution uses the *same* scoped gateway dispatcher.
No server-initiated SSE, resources, prompts, or MRTR input requests are
advertised or implemented by this adapter.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any, Callable

from . import __version__
from .core import Gateway, GatewayError, Principal, canonical

MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = (MODERN_VERSION, LEGACY_VERSION)
SERVER_INFO = {"name": "shards-mcp", "version": __version__}
INFO_META = {"io.modelcontextprotocol/serverInfo": SERVER_INFO}
PROTOCOL_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"

# MCP 2026-07-28 protocol-defined errors.
HEADER_MISMATCH = -32020
UNSUPPORTED_VERSION = -32022


def error(code: int, message: str, request_id: Any = None,
          data: dict[str, Any] | None = None, status: int = 400
          ) -> tuple[int, dict[str, Any]]:
    value: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        value["data"] = data
    return status, {"jsonrpc": "2.0", "id": request_id, "error": value}


def unsupported(requested: str | None, request_id: Any = None
                ) -> tuple[int, dict[str, Any]]:
    return error(UNSUPPORTED_VERSION, "Unsupported protocol version", request_id,
                 {"supported": list(SUPPORTED_VERSIONS), "requested": requested})


def _header_value(headers: Any, name: str) -> str | None:
    values = headers.get_all(name, [])
    if len(values) != 1:
        return None
    return values[0]


def _decode_name(value: str | None) -> str | None:
    if not isinstance(value, str) or len(value) > 1024:
        return None
    prefix, suffix = "=?base64?", "?="
    if value.startswith(prefix) and value.endswith(suffix):
        encoded = value[len(prefix):-len(suffix)]
        try:
            # Don't allow noncanonical encodings or spurious trailing bytes.
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode("ascii") != encoded:
                return None
            return raw.decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error):
            return None
    # HTTP proxy parsers must see exactly the bytes we compare.
    if (not value or value != value.strip()
            or any(ord(c) < 33 or ord(c) > 126 for c in value)
            or value.startswith(prefix)):
        return None
    return value


def _result(request_id: str | int | float, value: dict[str, Any]
           ) -> tuple[int, dict[str, Any]]:
    return 200, {"jsonrpc": "2.0", "id": request_id,
                 "result": {"resultType": "complete", **value, "_meta": INFO_META}}


def process_modern(
    payload: Any, headers: Any, principal: Principal, gateway: Gateway,
    tools_fn: Callable[[Principal], list[dict[str, Any]]],
    dispatch_fn: Callable[[Gateway, Principal, str, Any], Any],
    known_tools: set[str],
) -> tuple[int, dict[str, Any]]:
    """Validate HTTP/body routing and handle only declared modern MCP methods."""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return error(-32600, "Invalid Request")
    request_id = payload.get("id")
    if type(request_id) not in (str, int, float):
        return error(-32600, "Invalid Request")
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        return error(-32600, "Invalid Request", request_id)
    params = payload.get("params")
    if not isinstance(params, dict):
        return error(-32602, "Invalid params", request_id)
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return error(-32602, "Missing request metadata", request_id)
    requested = meta.get(PROTOCOL_VERSION_KEY)
    if not isinstance(requested, str):
        return error(-32602, "Invalid protocol metadata", request_id)
    if requested != MODERN_VERSION:
        return error(HEADER_MISMATCH, "Header mismatch: protocol version",
                     request_id)
    if not isinstance(meta.get(CLIENT_CAPABILITIES_KEY), dict):
        return error(-32602, "Missing client capabilities", request_id)
    client_info = meta.get("io.modelcontextprotocol/clientInfo")
    if client_info is not None and (
        not isinstance(client_info, dict)
        or not isinstance(client_info.get("name"), str)
        or not isinstance(client_info.get("version"), str)
    ):
        return error(-32602, "Invalid client information", request_id)

    version_header = _header_value(headers, "MCP-Protocol-Version")
    if version_header != MODERN_VERSION:
        return error(HEADER_MISMATCH, "Header mismatch: protocol version",
                     request_id)
    method_header = _header_value(headers, "Mcp-Method")
    if method_header != method:
        return error(HEADER_MISMATCH, "Header mismatch: Mcp-Method",
                     request_id)

    name_headers = headers.get_all("Mcp-Name", [])
    if method == "tools/call":
        if len(name_headers) != 1 or _decode_name(name_headers[0]) != params.get("name"):
            return error(HEADER_MISMATCH, "Header mismatch: Mcp-Name", request_id)
    elif name_headers:
        return error(HEADER_MISMATCH, "Unexpected Mcp-Name header", request_id)
    # No tool in this gateway declares x-mcp-header. Reject an unvalidated
    # Mcp-Param-* header rather than letting a proxy route on a second meaning.
    if any(k.lower().startswith("mcp-param-") for k in headers.keys()):
        return error(HEADER_MISMATCH, "Unexpected Mcp-Param header", request_id)

    if method == "server/discover":
        if set(params) != {"_meta"}:
            return error(-32602, "Invalid discovery params", request_id)
        return _result(request_id, {
            "supportedVersions": list(SUPPORTED_VERSIONS),
            "capabilities": {"tools": {"listChanged": False}},
            "ttlMs": 0, "cacheScope": "private",
        })
    if method == "tools/list":
        if set(params) - {"_meta", "cursor"}:
            return error(-32602, "Invalid list params", request_id)
        if "cursor" in params and params["cursor"] not in ("", None):
            return error(-32602, "Unknown tool-list cursor", request_id)
        return _result(request_id, {
            "tools": tools_fn(principal),
            "ttlMs": 0, "cacheScope": "private",
        })
    if method == "tools/call":
        if set(params) - {"_meta", "name", "arguments"}:
            return error(-32602, "Invalid call params", request_id)
        name = params.get("name")
        if not isinstance(name, str) or name not in known_tools:
            return error(-32602, "Unknown tool", request_id)
        try:
            value = dispatch_fn(gateway, principal, name,
                                params.get("arguments", {}))
            outcome = {
                "content": [{"type": "text", "text": canonical(value)}],
                "structuredContent": value if isinstance(value, dict) else {"items": value},
                "isError": False,
            }
        except GatewayError as exc:
            # Business and permission denials are tool results, never a way
            # for clients to acquire privileges not granted to the principal.
            outcome = {
                "content": [{"type": "text", "text": canonical({
                    "error": exc.code, "message": str(exc),
                })}],
                "isError": True,
            }
        return _result(request_id, outcome)
    # 2026-07-28 removed initialize, ping and notifications/initialized.
    return error(-32601, "Method not found", request_id, status=404)
