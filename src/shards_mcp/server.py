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
from typing import Any, Callable

from . import __version__
from .core import Gateway, GatewayError, Principal, canonical


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
    ("agent_register", "Admin only: register an agent and issue a credential exactly once.",
     schema({"name": S, "provider": S, "capabilities": ARR, "scopes": ARR},
            ("name", "provider", "capabilities", "scopes")), False),
    ("agent_revoke", "Admin only: invalidate an agent's credential.",
     schema({"agent_id": S}, ("agent_id",)), False),
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
     "annotations": {"readOnlyHint": read_only, "destructiveHint": False}}
    for name, description, input_schema, read_only in TOOL_DEFS
]
SCHEMAS = {item["name"]: item["inputSchema"] for item in TOOL_LIST}
TOOL_SCOPES = {
    "agent_register": "*", "agent_revoke": "*", "agent_list": "agent:read",
    "agent_heartbeat": "agent:heartbeat",
    "message_send": "message:send", "message_inbox": "message:read",
    "message_ack": "message:read", "message_poll": "message:read",
    "task_create": "task:create", "task_get": "task:read",
    "task_inbox": "task:read", "task_claim": "task:claim",
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
assert set(TOOL_SCOPES) == set(SCHEMAS), "every tool requires an explicit permission map"


def visible_tools(principal: Principal) -> list[dict[str, Any]]:
    if "*" in principal.scopes:
        return TOOL_LIST
    return [tool for tool in TOOL_LIST if TOOL_SCOPES[tool["name"]] in principal.scopes]


def decode_auth(value: str) -> str:
    scheme, separator, token = value.partition(" ")
    return token if separator and scheme.casefold() == "bearer" and token and token == token.strip() else ""


def reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON constant")


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
        "agent_register": lambda: gateway.register(principal, a["name"], a["provider"], a["capabilities"], a["scopes"]),
        "agent_revoke": lambda: gateway.revoke(principal, a["agent_id"]),
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
    with gateway.tx() as db:
        return {
            "version": __version__,
            "agents": db.execute("SELECT COUNT(*) FROM agents WHERE revoked=0").fetchone()[0],
            "tasks": {r["state"]: r["count"] for r in
                      db.execute("SELECT state, COUNT(*) AS count FROM tasks GROUP BY state")},
            "messages": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "audit_entries": db.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
        }


def make_handler(gateway: Gateway, allowed_origins: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ShardsMCP/" + __version__

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format: str, *args: Any) -> None:
            # Do not log request headers (particularly bearer tokens).
            sys.stderr.write("%s %s\n" % (self.address_string(), format % args))

        def respond(self, status_code: int, data: Any, headers: dict[str, str] | None = None) -> None:
            raw = canonical(data).encode("utf-8") if data is not None else b""
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health/live":
                return self.respond(200, {"status": "alive", "version": __version__})
            if self.path == "/health/ready":
                try:
                    with gateway.tx() as db:
                        db.execute("SELECT 1").fetchone()
                    return self.respond(200, {"status": "ready"})
                except sqlite3.Error:
                    return self.respond(503, {"status": "not_ready"})
            if self.path == "/mcp":
                return self.respond(405, {"error": "GET streaming not supported; use POST"}, {"Allow": "POST"})
            if self.path == "/v1/tools":
                origin = self.headers.get("Origin")
                if origin and origin not in allowed_origins:
                    return self.respond(403, {"error": "origin denied"})
                token = decode_auth(self.headers.get("Authorization", ""))
                if not token:
                    return self.respond(401, {"error": "bearer authentication required"})
                try:
                    principal = gateway.authenticate(token)
                except GatewayError:
                    return self.respond(401, {"error": "invalid credentials"})
                return self.respond(200, {"tools": visible_tools(principal)})
            return self.respond(404, {"error": "not found"})

        def do_POST(self) -> None:
            is_rest = self.path.startswith("/v1/tools/") and len(self.path) > len("/v1/tools/")
            if self.path != "/mcp" and not is_rest:
                return self.respond(404, {"error": "not found"})
            # Version negotiation happens in initialize; the client may probe with
            # a newer header before accepting our supported version in the result.
            version = self.headers.get("MCP-Protocol-Version")
            origin = self.headers.get("Origin")
            if origin and origin not in allowed_origins:
                return self.respond(403, {"error": "origin denied"})
            if not self.headers.get("Content-Type", "").split(";")[0].strip() == "application/json":
                return self.respond(415, {"error": "application/json required"})
            if self.headers.get("Transfer-Encoding"):
                return self.respond(411, {"error": "Content-Length required; chunked transfer unsupported"})
            length_header = self.headers.get("Content-Length")
            if length_header is None or not re.fullmatch(r"[0-9]+", length_header):
                return self.respond(411, {"error": "valid ASCII Content-Length required"})
            length = int(length_header)
            if length > 262144:
                return self.respond(413, {"error": "request body exceeds 256 KiB"})
            token = decode_auth(self.headers.get("Authorization", ""))
            if not token:
                return self.respond(401, {"error": "bearer authentication required"},
                                    {"WWW-Authenticate": 'Bearer realm="Shards-MCP"'})
            try:
                principal = gateway.authenticate(token)
            except GatewayError:
                return self.respond(401, {"error": "invalid credentials"},
                                    {"WWW-Authenticate": 'Bearer realm="Shards-MCP"'})
            try:
                payload = json.loads(self.rfile.read(length), parse_constant=reject_nonfinite)
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self.respond(400, {"jsonrpc": "2.0", "id": None,
                                          "error": {"code": -32700, "message": "Parse error"}})
            except (TimeoutError, socket.timeout, OSError):
                return self.respond(408, {"error": "request body timed out"})
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
            method = payload.get("method")
            if not isinstance(method, str):
                return self.rpc_error(request_id, -32600, "Invalid Request")
            if method == "notifications/initialized":
                return self.respond(202, None)
            if "id" not in payload:
                return self.respond(202, None)
            try:
                if method == "initialize":
                    result = {"protocolVersion": "2025-11-25",
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
    token = os.getenv("SHARDS_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Refusing to start: SHARDS_ADMIN_TOKEN must be >=32 characters")
    host = os.getenv("SHARDS_BIND", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and os.getenv("SHARDS_ALLOW_REMOTE") != "1":
        raise SystemExit("Refusing non-loopback binding without SHARDS_ALLOW_REMOTE=1")
    try:
        port = int(os.getenv("SHARDS_PORT", "8787"))
        gateway = Gateway(os.getenv("SHARDS_DB", "shards.db"), token)
        origins = set(filter(None, os.getenv("SHARDS_ALLOWED_ORIGINS", "").split(",")))
        server = BoundedHTTPServer((host, port), make_handler(gateway, origins))
        print(f"Shards MCP {__version__} serving on {host}:{port}", file=sys.stderr)
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
