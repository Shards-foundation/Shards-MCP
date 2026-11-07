"""Stateless MCP Streamable HTTP endpoint.

Implements the tool server subset of MCP 2025-11-25. Does not claim OAuth,
A2A, SSE subscriptions, or arbitrary tool proxying. No network writes occur
unless a privileged agent explicitly invokes one of the local gateway tools.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import socket
import threading
import json
import sqlite3
import os
import sys
import secrets
import time
from typing import Any, Callable

from . import __version__
from .core import Gateway, GatewayError, Principal, canonical
from .oauth import OAuthResourceServer
from .a2a import A2AAdapter
from .observability import RequestMetrics, route_class
from .config import admin_token_from_environment


MCP_PROTOCOL_VERSION = "2025-11-25"


def schema(properties: dict[str, dict[str, Any]], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


S = {"type": "string"}
OBJ = {"description": "JSON-serialisable object or value"}
ARR = {"type": "array", "items": S}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}

# Tool descriptions deliberately state authority boundaries. They do not grant authority.
TOOL_DEFS = [
    ("agent_identity", "Identify the authenticated agent and its granted scopes without exposing credentials.",
     schema({}), True),
    ("agent_list", "List registered agents (credentials never returned).",
     schema({}), True),
    ("agent_heartbeat", "Record authenticated agent liveness.", schema({}), False),
    ("message_send", "Send a durable, idempotent message from the authenticated agent.",
     schema({"destination": S, "body": OBJ, "idempotency_key": S, "task_id": S},
            ("destination", "body", "idempotency_key")), False),
    ("message_inbox", "Read recipient's messages, or all messages for admin.",
     schema({"limit": INT}), True),
    ("message_ack", "Recipient acknowledgement of a stored message.",
     schema({"message_id": S}, ("message_id",)), False),
    ("message_poll", "Read durable recipient messages using a monotonic cursor; unread by default.",
     schema({"after_seq": INT, "limit": INT, "unread_only": BOOL}), True),
    ("task_create", "Create durable assigned task; does not execute arbitrary commands.",
     schema({"assignee": S, "payload": OBJ, "idempotency_key": S},
            ("assignee", "payload", "idempotency_key")), False),
    ("task_get", "Read task owned by creator or assignee.", schema({"task_id": S}, ("task_id",)), True),
    ("task_inbox", "List tasks assigned to caller and filtered by state.",
     schema({"state": S, "limit": INT}), True),
    ("task_cancel", "Creator or operator: cancel a queued task before worker claim; cannot stop running work.",
     schema({"task_id": S}, ("task_id",)), False),
    ("task_claim", "Claim assigned queued task with a bounded lease.",
     schema({"task_id": S, "lease_seconds": INT}, ("task_id",)), False),
    ("task_renew", "Renew an active task lease.",
     schema({"task_id": S, "lease_seconds": INT}, ("task_id",)), False),
    ("task_complete", "Record worker result; successful worker claims require independent task_verify.",
     schema({"task_id": S, "success": BOOL, "result": OBJ}, ("task_id", "success", "result")), False),
    ("task_verify", "Independent reviewer: approve or reject a reported worker result.",
     schema({"task_id": S, "approved": BOOL, "evidence": OBJ},
            ("task_id", "approved", "evidence")), False),
    ("verification_get", "Inspect retained verification evidence for a task.",
     schema({"task_id": S}, ("task_id",)), True),
    ("checkpoint_write", "Persist a versioned checkpoint for a running owned task.",
     schema({"task_id": S, "body": OBJ}, ("task_id", "body")), False),
    ("checkpoint_get", "Retrieve latest task checkpoint.",
     schema({"task_id": S}, ("task_id",)), True),
    ("task_scan_expired", "Admin only: block expired leases until reconciled.",
     schema({}), False),
    ("task_reconcile", "Admin only: requeue blocked task after verified external-effect reconciliation.",
     schema({"task_id": S, "external_effects_checked": BOOL, "explanation": S},
            ("task_id", "external_effects_checked", "explanation")), False),
    ("event_publish", "Append an idempotent operational event to the shared agent event stream.",
     schema({"topic": S, "body": OBJ, "idempotency_key": S, "correlation_id": S},
            ("topic", "body", "idempotency_key")), False),
    ("event_poll", "Poll the durable event stream by cursor and optional topic.",
     schema({"after_seq": INT, "limit": INT, "topic": S}), True),
    ("audit_list", "Read recent internal audit events.", schema({"limit": INT}), True),
    ("audit_verify", "Verify internal audit hash chain.", schema({}), True),
    ("schedule_create", "Admin only: create periodic assigned task schedule (interval, not cron expression).",
     schema({"assignee": S, "payload": OBJ, "interval_seconds": INT},
            ("assignee", "payload", "interval_seconds")), False),
    ("schedule_tick", "Admin only: dispatch due periodic tasks; call from trusted scheduler.",
     schema({}), False),
    ("schedule_list", "Admin only: list recurring schedules.", schema({}), True),
    ("schedule_disable", "Admin only: stop an active recurring schedule.",
     schema({"schedule_id": S}, ("schedule_id",)), False),
    ("system_status", "Admin only: inspect database and gateway counts; no raw credentials.",
     schema({}), True),
    ("system_sanity_check", "Admin only: check SQLite integrity, foreign keys and audit hash chain.",
     schema({}), True),
]

TOOL_LIST = [
    {"name": name, "description": description, "inputSchema": input_schema,
     "annotations": {"readOnlyHint": read_only, "destructiveHint": name == "task_cancel"}}
    for name, description, input_schema, read_only in TOOL_DEFS
]
SCHEMAS = {item["name"]: item["inputSchema"] for item in TOOL_LIST}
TOOL_SCOPES = {
    "agent_identity": "__authenticated__",
    "agent_list": "agent:read",
    "agent_heartbeat": "agent:heartbeat",
    "message_send": "message:send", "message_inbox": "message:read",
    "message_ack": "message:read", "message_poll": "message:read",
    "task_create": "task:create", "task_get": "task:read",
    "task_inbox": "task:read", "task_cancel": "task:cancel",
    "task_claim": "task:claim",
    "task_renew": "task:update", "task_complete": "task:update",
    "task_verify": "task:verify", "verification_get": "task:read",
    "checkpoint_write": "checkpoint:write", "checkpoint_get": "task:read",
    "task_scan_expired": "*", "task_reconcile": "*",
    "event_publish": "event:write", "event_poll": "event:read",
    "audit_list": "audit:read", "audit_verify": "*",
    "schedule_create": "*", "schedule_tick": "*",
    "schedule_list": "*", "schedule_disable": "*",
    "system_status": "*", "system_sanity_check": "*",
}
if set(TOOL_SCOPES) != set(SCHEMAS):
    raise RuntimeError("every tool requires an explicit permission map")


def visible_tools(principal: Principal) -> list[dict[str, Any]]:
    if "*" in principal.scopes:
        return TOOL_LIST
    return [tool for tool in TOOL_LIST if (TOOL_SCOPES[tool["name"]] in principal.scopes
            or TOOL_SCOPES[tool["name"]] == "__authenticated__")]


def decode_auth(value: str) -> str:
    scheme, separator, token = value.partition(" ")
    return token if separator and scheme.casefold() == "bearer" and token and token == token.strip() else ""


def reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def reject_duplicate_properties(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON payloads with ambiguous duplicate properties must fail closed."""
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON object property")
        obj[key] = value
    return obj


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args: Any, **kwargs: Any):
        self._slots = threading.BoundedSemaphore(64)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()



def validate_args(name: str, args: Any) -> dict[str, Any]:
    if name not in SCHEMAS:
        raise GatewayError("unknown tool", "NOT_FOUND")
    if not isinstance(args, dict):
        raise GatewayError("arguments must be object")
    spec = SCHEMAS[name]
    if set(args) - set(spec["properties"]):
        raise GatewayError("unknown argument")
    if set(spec["required"]) - set(args):
        raise GatewayError("required argument missing")
    for key, value in args.items():
        kind = spec["properties"][key].get("type")
        if kind == "string" and not isinstance(value, str):
            raise GatewayError(f"{key} must be string")
        if kind == "integer" and (type(value) is not int):
            raise GatewayError(f"{key} must be integer")
        if kind == "boolean" and type(value) is not bool:
            raise GatewayError(f"{key} must be boolean")
        if kind == "array" and not isinstance(value, list):
            raise GatewayError(f"{key} must be array")
    return args


def dispatch(gateway: Gateway, principal: Principal, name: str, args: Any) -> Any:
    a = validate_args(name, args)
    calls: dict[str, Callable[[], Any]] = {
        "agent_identity": lambda: {"agent_id": principal.agent_id,
                                    "scopes": list(principal.scopes),
                                    "role": "operator" if "*" in principal.scopes else "agent"},
        "agent_list": lambda: gateway.agents(principal),
        "agent_heartbeat": lambda: gateway.heartbeat(principal),
        "message_send": lambda: gateway.send(principal, a["destination"], a["body"], a["idempotency_key"], a.get("task_id")),
        "message_inbox": lambda: gateway.inbox(principal, a.get("limit", 50)),
        "message_ack": lambda: gateway.message_ack(principal, a["message_id"]),
        "message_poll": lambda: gateway.message_poll(principal, a.get("after_seq", 0),
                                                    a.get("limit", 50), a.get("unread_only", True)),
        "task_create": lambda: gateway.task_create(principal, a["assignee"], a["payload"], a["idempotency_key"]),
        "task_get": lambda: gateway.task_get(principal, a["task_id"]),
        "task_inbox": lambda: gateway.task_inbox(principal, a.get("state", "queued"), a.get("limit", 50)),
        "task_cancel": lambda: gateway.task_cancel(principal, a["task_id"]),
        "task_claim": lambda: gateway.task_claim(principal, a["task_id"], a.get("lease_seconds", 60)),
        "task_renew": lambda: gateway.task_renew(principal, a["task_id"], a.get("lease_seconds", 60)),
        "task_complete": lambda: gateway.task_complete(principal, a["task_id"], a["success"], a["result"]),
        "task_verify": lambda: gateway.task_verify(principal, a["task_id"], a["approved"], a["evidence"]),
        "verification_get": lambda: gateway.verification_get(principal, a["task_id"]),
        "checkpoint_write": lambda: gateway.checkpoint(principal, a["task_id"], a["body"]),
        "checkpoint_get": lambda: gateway.checkpoint_get(principal, a["task_id"]),
        "task_scan_expired": lambda: gateway.expired(principal),
        "task_reconcile": lambda: gateway.reconcile(principal, a["task_id"], a["external_effects_checked"], a["explanation"]),
        "event_publish": lambda: gateway.event_publish(principal, a["topic"], a["body"],
                                                        a["idempotency_key"], a.get("correlation_id")),
        "event_poll": lambda: gateway.event_poll(principal, a.get("after_seq", 0),
                                                  a.get("limit", 50), a.get("topic")),
        "audit_list": lambda: gateway.audit_list(principal, a.get("limit", 50)),
        "audit_verify": lambda: gateway.audit_verify(principal),
        "schedule_create": lambda: gateway.schedule_create(principal, a["assignee"], a["payload"], a["interval_seconds"]),
        "schedule_tick": lambda: gateway.schedule_tick(principal),
        "schedule_list": lambda: gateway.schedule_list(principal),
        "schedule_disable": lambda: gateway.schedule_disable(principal, a["schedule_id"]),
        "system_status": lambda: status(gateway, principal),
        "system_sanity_check": lambda: gateway.sanity_check(principal),
    }
    return calls[name]()


def status(gateway: Gateway, principal: Principal) -> dict[str, Any]:
    principal.require("*")
    with gateway.read_tx() as db:
        return {
            "version": __version__,
            "agents": db.execute("SELECT COUNT(*) FROM agents WHERE revoked=0").fetchone()[0],
            "tasks": {r["state"]: r["count"] for r in
                      db.execute("SELECT state, COUNT(*) AS count FROM tasks GROUP BY state")},
            "messages": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "audit_entries": db.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
        }


def make_handler(gateway: Gateway, allowed_origins: set[str],
                 oauth: OAuthResourceServer | None = None,
                 a2a: A2AAdapter | None = None,
                 metrics: RequestMetrics | None = None):
    meter = metrics if metrics is not None else RequestMetrics()
    # Only one token format is accepted per server mode. In OAuth mode, local
    # bootstrap/agent credentials cannot authenticate any network request.
    authenticate = oauth.authenticate if oauth is not None else gateway.authenticate
    challenge = oauth.challenge() if oauth is not None else 'Bearer realm="Shards-MCP"'

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShardsMCP/" + __version__

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)
            self._started = time.monotonic()
            self._request_id = secrets.token_hex(8)

        def log_message(self, format: str, *args: Any) -> None:
            # BaseHTTPRequestHandler can log raw paths, including user-controlled query
            # strings. We emit one sanitised structured event from respond() instead.
            return None

        def respond(self, status_code: int, data: Any,
                    headers: dict[str, str] | None = None,
                    content_type: str = "application/json") -> None:
            raw = (data.encode("utf-8") if content_type.startswith("text/plain")
                   else canonical(data).encode("utf-8")) if data is not None else b""
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-ID", self._request_id)
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if raw:
                self.wfile.write(raw)
            elapsed = max(0.0, time.monotonic() - self._started)
            meter.observe(self.command, self.path, status_code, elapsed)
            # Fixed labels only: never emit request headers, tokens, actor IDs,
            # message bodies, task payloads or arbitrary query paths.
            sys.stderr.write(json.dumps({
                "event": "http_response", "request_id": self._request_id,
                "method": self.command if self.command in ("GET", "POST") else "OTHER",
                "route": route_class(self.path), "status": status_code,
                "elapsed_ms": round(elapsed * 1000, 2),
            }, separators=(",", ":")) + "\n")

        def do_GET(self) -> None:
            if self.path == "/metrics":
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self.respond(404, {"error": "not found"})
                token = decode_auth(self.headers.get("Authorization", ""))
                if not token:
                    return self.respond(401, {"error": "operator credential required"})
                try:
                    principal = gateway.authenticate(token)
                    principal.require("*")
                except GatewayError:
                    return self.respond(403, {"error": "permission denied"})
                try:
                    with gateway.read_tx() as db:
                        exposed = meter.render(db)
                    return self.respond(200, exposed,
                                        content_type="text/plain; version=0.0.4; charset=utf-8")
                except sqlite3.Error:
                    return self.respond(503, {"error": "metrics storage unavailable"})
            if oauth and self.path in ("/.well-known/oauth-protected-resource",
                                      "/.well-known/oauth-protected-resource/mcp"):
                return self.respond(200, oauth.metadata())
            if self.path == "/health/live":
                return self.respond(200, {"status": "alive", "version": __version__})
            if self.path == "/health/ready":
                try:
                    with gateway.read_tx() as db:
                        db.execute("SELECT 1").fetchone()
                    return self.respond(200, {"status": "ready"})
                except sqlite3.Error:
                    return self.respond(503, {"status": "not_ready"})
            if self.path == "/mcp":
                origins = self.headers.get_all("Origin", [])
                if len(origins) > 1 or (origins and origins[0] not in allowed_origins):
                    return self.respond(403, {"error": "origin denied"})
                versions = self.headers.get_all("MCP-Protocol-Version", [])
                if len(versions) > 1 or (versions and versions[0] != MCP_PROTOCOL_VERSION):
                    return self.respond(400, {"error": "unsupported MCP protocol version"})
                return self.respond(405, {"error": "GET streaming not supported; use POST"}, {"Allow": "POST"})
            card_target = a2a.route(self.path, card=True) if a2a else None
            if card_target:
                origin = self.headers.get("Origin")
                if origin and origin not in allowed_origins:
                    return self.respond(403, {"error": "origin denied"})
                token = decode_auth(self.headers.get("Authorization", ""))
                if not token:
                    return self.respond(401, {"error": "bearer authentication required"},
                                        {"WWW-Authenticate": challenge})
                try:
                    principal = authenticate(token)
                    return self.respond(200, a2a.card(principal, card_target))
                except GatewayError as exc:
                    return self.respond(404 if exc.code == "NOT_FOUND" else 403,
                                        {"error": "agent card not available"})
            if self.path == "/v1/tools":
                origin = self.headers.get("Origin")
                if origin and origin not in allowed_origins:
                    return self.respond(403, {"error": "origin denied"})
                token = decode_auth(self.headers.get("Authorization", ""))
                if not token:
                    return self.respond(401, {"error": "bearer authentication required"},
                                        {"WWW-Authenticate": challenge})
                try:
                    principal = authenticate(token)
                except GatewayError:
                    return self.respond(401, {"error": "invalid credentials"},
                                        {"WWW-Authenticate": challenge})
                return self.respond(200, {"tools": visible_tools(principal)})
            return self.respond(404, {"error": "not found"})

        def do_POST(self) -> None:
            is_rest = self.path.startswith("/v1/tools/") and len(self.path) > len("/v1/tools/")
            a2a_target = a2a.route(self.path) if a2a else None
            if self.path != "/mcp" and not is_rest and not a2a_target:
                return self.respond(404, {"error": "not found"})
            # A client may probe with a newer version; initialize advertises the
            # version this implementation actually implements.
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1 or (origins and origins[0] not in allowed_origins):
                return self.respond(403, {"error": "origin denied"})
            if self.path == "/mcp":
                versions = self.headers.get_all("MCP-Protocol-Version", [])
                if len(versions) > 1 or (versions and versions[0] != MCP_PROTOCOL_VERSION):
                    return self.respond(400, {"error": "unsupported MCP protocol version"})
            if len(self.headers.get_all("Authorization", [])) > 1:
                return self.respond(400, {"error": "ambiguous Authorization headers"})
            if len(self.headers.get_all("Content-Length", [])) > 1:
                return self.respond(400, {"error": "ambiguous Content-Length headers"})
            if not self.headers.get("Content-Type", "").split(";")[0].strip() == "application/json":
                return self.respond(415, {"error": "application/json required"})
            if self.headers.get("Transfer-Encoding"):
                return self.respond(411, {"error": "Content-Length required; chunked transfer unsupported"})
            length_header = self.headers.get("Content-Length")
            if length_header is None or not re.fullmatch(r"[0-9]+", length_header):
                return self.respond(411, {"error": "valid ASCII Content-Length required"})
            if len(length_header) > 10:
                return self.respond(400, {"error": "Content-Length digit count exceeded"})
            try:
                length = int(length_header)
            except ValueError:
                return self.respond(400, {"error": "invalid Content-Length"})
            if length > 262144:
                return self.respond(413, {"error": "request body exceeds 256 KiB"})
            token = decode_auth(self.headers.get("Authorization", ""))
            if not token:
                return self.respond(401, {"error": "bearer authentication required"},
                                    {"WWW-Authenticate": challenge})
            try:
                principal = authenticate(token)
            except GatewayError:
                return self.respond(401, {"error": "invalid credentials"},
                                    {"WWW-Authenticate": challenge})
            try:
                payload = json.loads(self.rfile.read(length), parse_constant=reject_nonfinite,
                                     object_pairs_hook=reject_duplicate_properties)
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self.respond(400, {"jsonrpc": "2.0", "id": None,
                                          "error": {"code": -32700, "message": "Parse error"}})
            except (TimeoutError, socket.timeout, OSError):
                return self.respond(408, {"error": "request body timed out"})
            if a2a_target:
                if self.headers.get("A2A-Version") != "1.0":
                    return self.respond(400, {"error": "A2A-Version: 1.0 required"})
                return self.respond(200, a2a.process(principal, a2a_target, payload))
            if is_rest:
                try:
                    value = dispatch(gateway, principal, self.path[len("/v1/tools/"):], payload)
                    return self.respond(200, {"ok": True, "result": value})
                except GatewayError as exc:
                    code = {"UNAUTHENTICATED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404,
                            "CONFLICT": 409, "PAYLOAD_TOO_LARGE": 413}.get(exc.code, 400)
                    return self.respond(code, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
                except Exception:
                    self.log_error("Internal REST tool error")
                    return self.respond(500, {"ok": False, "error": {"code": "INTERNAL", "message": "Internal error"}})
            if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
                return self.respond(400, {"jsonrpc": "2.0", "id": None,
                                          "error": {"code": -32600, "message": "Invalid Request"}})
            request_id = payload.get("id")
            if "id" in payload and type(request_id) not in (str, int, float):
                return self.rpc_error(None, -32600, "Invalid Request")
            method = payload.get("method")
            if not isinstance(method, str):
                return self.rpc_error(request_id, -32600, "Invalid Request")
            if method == "notifications/initialized":
                if "id" in payload:
                    return self.rpc_error(request_id, -32600, "Invalid Request")
                return self.respond(202, None)
            if "id" not in payload:
                return self.respond(202, None)
            try:
                if method == "initialize":
                    result = {"protocolVersion": MCP_PROTOCOL_VERSION,
                              "capabilities": {"tools": {"listChanged": False}},
                              "serverInfo": {"name": "shards-mcp", "version": __version__}}
                elif method == "ping":
                    result = {}
                elif method == "tools/list":
                    result = {"tools": visible_tools(principal)}
                elif method == "tools/call":
                    params = payload.get("params", {})
                    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                        return self.rpc_error(request_id, -32602, "Invalid params")
                    if params["name"] not in SCHEMAS:
                        return self.rpc_error(request_id, -32602, "Unknown tool")
                    try:
                        value = dispatch(gateway, principal, params["name"], params.get("arguments", {}))
                        result = {"content": [{"type": "text", "text": canonical(value)}],
                                  "structuredContent": value if isinstance(value, dict) else {"items": value},
                                  "isError": False}
                    except GatewayError as exc:
                        result = {"content": [{"type": "text", "text": canonical(
                            {"error": exc.code, "message": str(exc)})}], "isError": True}
                else:
                    return self.rpc_error(request_id, -32601, "Method not found")
                return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
            except GatewayError as exc:
                return self.rpc_error(request_id, -32602, str(exc))
            except Exception:
                # Never expose internal error details to client.
                self.log_error("Internal gateway error processing %s", method)
                return self.rpc_error(request_id, -32603, "Internal error")

        def rpc_error(self, req_id: Any, code: int, message: str) -> None:
            return self.respond(200, {"jsonrpc": "2.0", "id": req_id,
                                      "error": {"code": code, "message": message}})
    return Handler


def main() -> None:
    try:
        token = admin_token_from_environment()
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"Refusing to start: {exc}") from None
    host = os.getenv("SHARDS_BIND", "127.0.0.1")
    remote = host not in ("127.0.0.1", "localhost", "::1")
    if remote and os.getenv("SHARDS_ALLOW_REMOTE") != "1":
        raise SystemExit("Refusing non-loopback binding without SHARDS_ALLOW_REMOTE=1")
    auth_mode = os.getenv("SHARDS_AUTH_MODE", "local").lower()
    if auth_mode not in ("local", "oauth"):
        raise SystemExit("SHARDS_AUTH_MODE must be local or oauth")
    if remote and auth_mode != "oauth":
        raise SystemExit("Refusing remote bearer-only mode: configure SHARDS_AUTH_MODE=oauth")
    try:
        port = int(os.getenv("SHARDS_PORT", "8787"))
        gateway = Gateway(os.getenv("SHARDS_DB", "shards.db"), token)
        origins = set(filter(None, os.getenv("SHARDS_ALLOWED_ORIGINS", "").split(",")))
        oauth = OAuthResourceServer.from_environment(gateway) if auth_mode == "oauth" else None
        a2a_base = os.getenv("SHARDS_A2A_BASE_URL", "").strip()
        if not a2a_base and oauth:
            a2a_base = oauth.resource.rsplit("/mcp", 1)[0]
        a2a = A2AAdapter(gateway, a2a_base) if a2a_base else None
        server = BoundedHTTPServer((host, port), make_handler(gateway, origins, oauth=oauth, a2a=a2a))
        print(f"Shards MCP {__version__} serving on {host}:{port}", file=sys.stderr)
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
