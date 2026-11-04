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
from urllib.request import HTTPRedirectHandler, Request, build_opener

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
        self.url = url.rstrip("/")
        self.token = token
        self.opener = build_opener(NoRedirects())

    def call(self, name: str, args: dict) -> object:
        body = canonical(args).encode("utf-8")
        req = Request(self.url + "/v1/tools/" + name, body, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, method="POST")
        try:
            with self.opener.open(req, timeout=15) as res:
                value = json.loads(res.read(262145))
        except HTTPError as exc:
            # Deliberately do not include supplied authentication headers.
            raise RuntimeError("gateway tool call failed (HTTP %d)" % exc.code) from None
        if not value.get("ok"):
            raise RuntimeError("gateway rejected tool call")
        return value["result"]


def safe_operation(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("task input must be a JSON object")
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
    queue = client.call("task_inbox", {"state": "queued", "limit": 10})
    completed = 0
    for task in queue:
        task_id = task["id"]
        try:
            client.call("task_claim", {"task_id": task_id, "lease_seconds": 60})
        except RuntimeError:
            # Another worker can have claimed it in a concurrent poll.
            continue
        try:
            client.call("checkpoint_write", {"task_id": task_id, "body": {"stage": "started"}})
            result = safe_operation(task["input"])
            client.call("task_complete", {"task_id": task_id, "success": True, "result": result})
        except (ValueError, TypeError) as exc:
            # Only expected validation failures become a reported task failure.
            client.call("task_complete", {"task_id": task_id, "success": False,
                                          "result": {"error": str(exc)}})
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
