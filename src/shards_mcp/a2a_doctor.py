"""Read-only A2A 1.0 connection doctor for a specific enrolled Shards agent.

Checks the authenticated Agent Card and an explicitly read-only GetTask probe.
Never sends SendMessage, claims, completes or cancels tasks, and never sends an
administrator credential. Does not certify all A2A methods or interoperability.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import uuid
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .a2a import AGENT_ID
from .core import canonical
from .doctor import (
    DiagnosticError,
    MAX_RESPONSE_BYTES,
    _validate_gateway_url,
    read_agent_token,
)
from .json_limits import enforce_json_depth
from .server import (
    reject_duplicate_properties,
    reject_nonfinite,
    reject_overflowing_float,
)
from .worker import AgentClient


def _read_json(client: AgentClient, request: Request,
               timeout: float) -> dict[str, Any]:
    try:
        with client.opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise DiagnosticError("unexpected A2A HTTP status")
            media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media != "application/json":
                raise DiagnosticError("A2A endpoint did not return JSON")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise DiagnosticError("A2A endpoint rejected request (HTTP %d)" % exc.code) from None
    except (URLError, TimeoutError, OSError, RuntimeError, HTTPException):
        raise DiagnosticError("A2A transport unavailable or refused") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DiagnosticError("A2A response exceeds maximum size")
    try:
        decoded = raw.decode("utf-8")
        enforce_json_depth(decoded)
        result = json.loads(
            decoded,
            parse_constant=reject_nonfinite,
            parse_float=reject_overflowing_float,
            object_pairs_hook=reject_duplicate_properties,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise DiagnosticError("A2A response is invalid JSON") from None
    if not isinstance(result, dict):
        raise DiagnosticError("A2A response must be a JSON object")
    if client.token in canonical(result):
        raise DiagnosticError("A2A peer reflected an agent credential")
    return result


def diagnose(url: str, token: str, target_agent: str, *,
             timeout: float = 10.0) -> dict[str, Any]:
    """Verify a single scoped A2A 1.0 endpoint without creating any task."""
    if not isinstance(target_agent, str) or not re.fullmatch(AGENT_ID, target_agent):
        raise DiagnosticError("target agent must be a Shards agent identifier")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 30:
        raise DiagnosticError("timeout must be 1..30 finite seconds")
    origin = _validate_gateway_url(url)
    try:
        client = AgentClient(origin, token)
    except ValueError:
        raise DiagnosticError("invalid scoped credential or A2A endpoint address") from None
    endpoint = client.url + "/a2a/agents/" + target_agent
    started = time.monotonic()
    card = _read_json(client, Request(
        endpoint + "/card",
        headers={
            "Authorization": "Bearer " + client.token,
            "Accept": "application/json",
        },
        method="GET",
    ), float(timeout))
    interfaces = card.get("supportedInterfaces")
    if (not isinstance(interfaces, list) or len(interfaces) != 1
            or not isinstance(interfaces[0], dict)
            or interfaces[0].get("url") != endpoint
            or interfaces[0].get("protocolBinding") != "JSONRPC"
            or interfaces[0].get("protocolVersion") != "1.0"):
        raise DiagnosticError("A2A Agent Card does not identify the expected v1 endpoint")
    capabilities = card.get("capabilities")
    if (not isinstance(capabilities, dict)
            or capabilities.get("streaming") is not False
            or capabilities.get("pushNotifications") is not False):
        raise DiagnosticError("A2A Agent Card advertises incompatible capabilities")
    schemes = card.get("securitySchemes")
    bearer = schemes.get("bearer") if isinstance(schemes, dict) else None
    scheme = bearer.get("httpAuthSecurityScheme") if isinstance(bearer, dict) else None
    if not isinstance(scheme, dict) or scheme.get("scheme") != "bearer":
        raise DiagnosticError("A2A Agent Card does not require bearer authentication")
    if not isinstance(card.get("name"), str) or not card["name"].strip():
        raise DiagnosticError("A2A Agent Card lacks an agent name")
    probe = "shards-a2a-doctor-" + uuid.uuid4().hex
    req = {
        "jsonrpc": "2.0", "id": 1, "method": "GetTask",
        "params": {"id": probe},
    }
    reply = _read_json(client, Request(
        endpoint, canonical(req).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + client.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
        },
        method="POST",
    ), float(timeout))
    if (reply.get("jsonrpc") != "2.0" or type(reply.get("id")) is not int
            or reply["id"] != 1 or "result" in reply):
        raise DiagnosticError("A2A GetTask probe returned invalid JSON-RPC envelope")
    err = reply.get("error")
    if (not isinstance(err, dict) or type(err.get("code")) is not int
            or err["code"] != -32001):
        raise DiagnosticError("A2A GetTask probe did not enforce task lookup")
    report = {
        "ok": True, "scope": "read-only-a2a-v1-card-and-gettask-probe",
        "protocol_binding": "JSONRPC", "protocol_version": "1.0",
        "target_agent": target_agent, "card_verified": True,
        "get_task_probe": "not-found-as-expected",
        "methods_exercised": ["GetTask"],
        "tasks_created": 0,
        "round_trip_ms": round((time.monotonic() - started) * 1000, 2),
        "full_a2a_conformance": False,
    }
    if token in canonical(report):
        raise DiagnosticError("A2A peer reflected an agent credential")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only A2A Agent Card and GetTask doctor")
    parser.add_argument("--url", default=os.getenv("SHARDS_GATEWAY_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--target-agent", required=True, help="Exact enrolled A2A assignee ID")
    parser.add_argument("--token-file", help="Private scoped agent token file")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = read_agent_token(args.token_file)
        report = diagnose(args.url, token, args.target_agent, timeout=args.timeout)
    except (DiagnosticError, ValueError, OSError, UnicodeError) as exc:
        message = str(exc) if isinstance(exc, DiagnosticError) else "invalid local credential configuration"
        if args.json:
            print(canonical({"ok": False, "error": message}))
        else:
            print("Shards A2A diagnostic: FAIL — " + message, file=sys.stderr)
        return 1
    if args.json:
        print(canonical(report))
    else:
        print("Shards A2A diagnostic: PASS")
        print("Protocol: A2A 1.0 JSONRPC subset")
        print("Target: " + report["target_agent"])
        print("Agent Card: verified")
        print("GetTask: expected not-found without task creation")
        print("Round trip: " + str(report["round_trip_ms"]) + " ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
