"""Minimal, fail-closed external agent worker.

This process is an example runtime, not a general-purpose executor. It only
supports deterministic local operations. Its credential is distinct from the
gateway bootstrap credential; never use an administrator token here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import __version__
from .core import canonical


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect refused: gateway URL must be exact")


class AgentClient:
    def __init__(self, url: str, token: str):
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError("gateway URL must use HTTPS or localhost HTTP")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("remote gateway must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("gateway URL must not contain credentials, query or fragment")
        if not token or len(token) < 32:
            raise ValueError("SHARDS_AGENT_TOKEN is required")
        # Never use a bootstrap administrator credential when it is in the same environment.
        if os.getenv("SHARDS_ADMIN_TOKEN") and token == os.getenv("SHARDS_ADMIN_TOKEN"):
            raise ValueError("an administrator token cannot be used by the agent client")
        self.url = url.rstrip("/")
        self.token = token
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def call(self, name: str, args: dict) -> object:
        body = canonical(args).encode("utf-8")
        req = Request(self.url + "/v1/tools/" + name, body, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, method="POST")
        try:
            with self.opener.open(req, timeout=15) as res:
                raw = res.read(262145)
        except HTTPError as exc:
            # Deliberately do not include supplied authentication headers.
            raise RuntimeError("gateway tool call failed (HTTP %d)" % exc.code) from None
        if len(raw) > 262144:
            raise RuntimeError("gateway response exceeds worker size limit")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise RuntimeError("gateway returned invalid JSON") from None
        if not isinstance(value, dict) or value.get("ok") is not True or "result" not in value:
            raise RuntimeError("gateway returned an invalid tool response")
        return value["result"]


def safe_operation(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("task input must be a JSON object")
    # Safe demonstration of a real A2A worker. This does not run an LLM or
    # execute instructions: it only echoes validated text for proof of delivery.
    if payload.get("protocol") == "a2a/1.0":
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != "ROLE_USER":
            raise ValueError("invalid A2A worker input")
        parts = message.get("parts")
        if (not isinstance(parts, list) or not 1 <= len(parts) <= 16
                or any(not isinstance(p, dict) or not isinstance(p.get("text"), str)
                       or not p["text"].strip() or len(p) != 1 for p in parts)):
            raise ValueError("invalid A2A text parts")
        return {"text": "\n".join(p["text"] for p in parts), "worker": "deterministic-echo"}
    action = payload.get("action")
    if action == "echo":
        return {"echo": payload.get("data")}
    if action == "sha256":
        return {"sha256": hashlib.sha256(canonical(payload.get("data")).encode()).hexdigest()}
    if action == "health":
        return {"worker": "shards-reference-worker", "version": __version__, "healthy": True}
    raise ValueError("unsupported operation; refusing arbitrary execution")


def process_once(client: AgentClient) -> int:
    client.call("agent_heartbeat", {})
    completed = 0
    # Claim-and-fetch is one atomic server transaction: a concurrent worker
    # cannot take the same task between an inbox poll and separate lease claim.
    for _ in range(10):
        claimed = client.call("task_claim_next", {"lease_seconds": 60})
        if not isinstance(claimed, dict) or type(claimed.get("claimed")) is not bool:
            raise RuntimeError("gateway returned an invalid task claim")
        if not claimed["claimed"]:
            break
        task = claimed.get("task")
        if (not isinstance(task, dict) or not isinstance(task.get("id"), str)
                or not task["id"] or "input" not in task):
            raise RuntimeError("gateway returned an invalid claimed task")
        task_id = task["id"]
        client.call("checkpoint_write", {"task_id": task_id, "body": {"stage": "started"}})
        try:
            result = safe_operation(task["input"])
        except (ValueError, TypeError) as exc:
            # Only local input validation errors become task failures.
            # A completion or checkpoint transport failure must never be
            # converted into a second, contradictory completion attempt.
            client.call("task_complete", {"task_id": task_id, "success": False,
                                          "result": {"error": str(exc)}})
        else:
            client.call("task_complete", {"task_id": task_id, "success": True, "result": result})
        completed += 1
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description="Shards safe reference agent worker")
    parser.add_argument("--once", action="store_true", help="Poll and process one task batch")
    args = parser.parse_args()
    client = AgentClient(os.getenv("SHARDS_GATEWAY_URL", "http://127.0.0.1:8787"),
                         os.getenv("SHARDS_AGENT_TOKEN", ""))
    interval = int(os.getenv("SHARDS_WORKER_POLL_SECONDS", "5"))
    if not 1 <= interval <= 60:
        raise SystemExit("SHARDS_WORKER_POLL_SECONDS must be 1..60")
    while True:
        try:
            count = process_once(client)
            print("worker cycle completed: %d tasks" % count, file=sys.stderr, flush=True)
        except (RuntimeError, OSError, ValueError) as exc:
            print("worker cycle failed: %s" % exc, file=sys.stderr, flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
