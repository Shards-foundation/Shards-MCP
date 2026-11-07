"""Constrained A2A v1.0 JSON-RPC adapter for Shards agent task delegation.

The adapter supports authenticated per-agent Agent Cards and SendMessage/GetTask
with text-only input and polling. Unsupported methods fail explicitly.
Cancellation is supported only for queued, unclaimed tasks. No streaming,
push subscriptions or multi-turn semantics are claimed.
"""
from __future__ import annotations

from urllib.parse import urlsplit
import re
from typing import Any

from . import __version__
from .core import Gateway, GatewayError, Principal, now


AGENT_ID = r"agt_[0-9a-f]{24}"
A2A_PATH = re.compile(rf"^/a2a/agents/({AGENT_ID})$")
CARD_PATH = re.compile(rf"^/a2a/agents/({AGENT_ID})/card$")


def validate_base_url(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ("", "/")):
        raise ValueError("A2A public base URL must be an origin without credentials/query/fragment")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("A2A non-local origin must use HTTPS")
    return value.rstrip("/")


class A2AAdapter:
    def __init__(self, gateway: Gateway, base_url: str):
        self.gateway = gateway
        self.base_url = validate_base_url(base_url)

    @staticmethod
    def route(path: str, *, card: bool = False) -> str | None:
        match = (CARD_PATH if card else A2A_PATH).fullmatch(path)
        return match.group(1) if match else None

    def card(self, actor: Principal, target: str) -> dict[str, Any]:
        actor.require("agent:read")
        with self.gateway.read_tx() as db:
            row = db.execute("SELECT id,name,capabilities,revoked FROM agents WHERE id=?",
                             (target,)).fetchone()
        if not row or row["revoked"]:
            raise GatewayError("agent unavailable", "NOT_FOUND")
        return {
            "name": row["name"],
            "description": "Shards-scoped, durable text task delegation endpoint for an enrolled agent",
            "version": __version__,
            "supportedInterfaces": [{
                "url": f"{self.base_url}/a2a/agents/{target}",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }],
            "capabilities": {
                "streaming": False, "pushNotifications": False, "extendedAgentCard": False,
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["application/json"],
            "skills": [{
                "id": "durable_task_delegation",
                "name": "Durable text task delegation",
                "description": "Queue a text message for this authenticated agent. Worker execution and independent verification remain separate.",
                "tags": ["task", "delegation", "agent"],
            }],
            "securitySchemes": {
                "bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}},
            },
            "securityRequirements": [
                {"schemes": {"bearer": {"list": []}}},
            ],
        }

    @staticmethod
    def mapped_task(task: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "queued": "TASK_STATE_SUBMITTED",
            "running": "TASK_STATE_WORKING",
            "reported": "TASK_STATE_WORKING",
            "blocked": "TASK_STATE_WORKING",
            "succeeded": "TASK_STATE_COMPLETED",
            "failed": "TASK_STATE_FAILED",
            "canceled": "TASK_STATE_CANCELED",
        }
        state = mapping[task["state"]]
        result: dict[str, Any] = {
            "id": task["id"],
            "contextId": task["id"],
            "status": {"state": state, "timestamp": task["updated"]},
        }
        if task["state"] == "succeeded" and task["result"] is not None:
            result["artifacts"] = [{
                "artifactId": task["id"] + "-result",
                "name": "Verified Shards task result",
                "parts": [{"data": task["result"]}],
            }]
        return result

    def send_message(self, actor: Principal, target: str, params: Any) -> dict[str, Any]:
        actor.require("task:create")
        if not isinstance(params, dict) or not isinstance(params.get("message"), dict):
            raise GatewayError("message object required")
        message = params["message"]
        message_id = message.get("messageId")
        if (not isinstance(message_id, str) or not 1 <= len(message_id) <= 200
                or message.get("role") != "ROLE_USER"):
            raise GatewayError("A2A v1 ROLE_USER and messageId required")
        if message.get("contextId") is not None or message.get("taskId") is not None:
            raise GatewayError("multi-turn A2A messages are not supported yet")
        parts = message.get("parts")
        if (not isinstance(parts, list) or not 1 <= len(parts) <= 16
                or any(not isinstance(part, dict)
                       or not isinstance(part.get("text"), str)
                       or not part["text"].strip()
                       or len(part) != 1 for part in parts)):
            raise GatewayError("only non-empty A2A v1 text parts are supported")
        text = "\n".join(part["text"] for part in parts)
        if len(text.encode("utf-8")) > 65536:
            raise GatewayError("A2A message too large", "PAYLOAD_TOO_LARGE")
        payload = {"protocol": "a2a/1.0", "message": message}
        created = self.gateway.task_create(actor, target, payload, message_id)
        task = self.gateway.task_get(actor, created["task_id"])
        return {"task": self.mapped_task(task)}

    def get_task(self, actor: Principal, target: str, params: Any) -> dict[str, Any]:
        actor.require("task:read")
        task_id = params.get("id") if isinstance(params, dict) else None
        if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
            raise GatewayError("task id required")
        task = self.gateway.task_get(actor, task_id)
        if task["assignee"] != target:
            raise GatewayError("task not found", "NOT_FOUND")
        return self.mapped_task(task)

    def cancel_task(self, actor: Principal, target: str, params: Any) -> dict[str, Any]:
        """A2A CancelTask: only an unclaimed task created by this caller.

        A running task cannot be remotely interrupted by this gateway: doing so
        would misrepresent external effects and violate recovery invariants.
        """
        actor.require("task:cancel")
        task_id = params.get("id") if isinstance(params, dict) else None
        if not isinstance(task_id, str) or not 1 <= len(task_id) <= 200:
            raise GatewayError("task id required")
        task = self.gateway.task_get(actor, task_id)
        if task["assignee"] != target:
            raise GatewayError("task not found", "NOT_FOUND")
        cancelled = self.gateway.task_cancel(actor, task_id)
        # Per A2A, an already cancelled task is no longer cancellable; the
        # core MCP cancellation tool remains idempotent for retrying clients.
        if cancelled["already_canceled"]:
            raise GatewayError("task is no longer cancellable", "CONFLICT")
        return self.mapped_task(self.gateway.task_get(actor, task_id))

    def process(self, actor: Principal, target: str, request: Any) -> dict[str, Any]:
        request_id = request.get("id") if isinstance(request, dict) else None
        def error(code: int, message: str) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": code, "message": message}}

        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or "id" not in request:
            return error(-32600, "Invalid JSON-RPC request")
        method = request.get("method")
        if method not in ("SendMessage", "GetTask", "CancelTask"):
            return error(-32601, "Unsupported A2A method")
        params = request.get("params", {})
        try:
            if method == "SendMessage":
                response = self.send_message(actor, target, params)
            elif method == "CancelTask":
                response = self.cancel_task(actor, target, params)
            else:
                response = self.get_task(actor, target, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": response}
        except GatewayError as exc:
            code = (-32002 if method == "CancelTask" and exc.code == "CONFLICT"
                    else -32001 if exc.code == "NOT_FOUND"
                    else -32602 if exc.code == "INVALID_REQUEST"
                    else -32003 if exc.code in ("FORBIDDEN", "UNAUTHENTICATED")
                    else -32603)
            return error(code, str(exc) if code == -32602 else exc.code)
