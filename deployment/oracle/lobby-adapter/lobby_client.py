#!/usr/bin/env python3
"""Local smoke client that reads only the adapter secret, directly from disk."""
from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import uuid
from pathlib import Path

import lobby_adapter as adapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route", choices=("health", "chat"))
    parser.add_argument("--secret-file", type=Path, default=adapter.default_secret_file())
    parser.add_argument("--conversation-id", type=uuid.UUID)
    args = parser.parse_args(argv)
    headers = {"Accept": "application/json", "Connection": "close"}
    try:
        secret = adapter.load_adapter_secret(args.secret_file).decode("ascii")
        headers["Authorization"] = "Bearer " + secret
        method, body = "GET", None
        if args.route == "chat":
            message = sys.stdin.buffer.read(adapter.MAX_MESSAGE_BYTES + 1).decode("utf-8")
            adapter._validate_text(message, adapter.MAX_MESSAGE_CHARS, adapter.MAX_MESSAGE_BYTES)
            conversation_id = str(args.conversation_id or uuid.uuid4())
            body = json.dumps(
                {"conversation_id": conversation_id, "message": message}, ensure_ascii=False
            ).encode("utf-8")
            if len(body) > adapter.MAX_REQUEST_BYTES:
                raise ValueError
            method = "POST"
            headers["Content-Type"] = "application/json"

        deadline = time.monotonic() + 2 * adapter.REQUEST_TIMEOUT + adapter.UPSTREAM_TIMEOUT
        connection = adapter._DeadlineHTTPConnection(adapter.BIND_HOST, adapter.BIND_PORT, deadline)
        try:
            connection.request(method, "/" + args.route, body=body, headers=headers)
            with connection.getresponse() as response:
                status = response.status
                raw = response.read(adapter.MAX_RESPONSE_BYTES + 1)
                if response.length not in (None, 0):
                    raise ValueError
        finally:
            connection.close()
        if len(raw) > adapter.MAX_RESPONSE_BYTES:
            raise ValueError
        payload = adapter.parse_strict_json(raw)
        if not isinstance(payload, dict):
            raise ValueError
        if status != 200:
            outcome = payload.get("outcome")
            detail = " (outcome unknown)" if args.route == "chat" and outcome == "unknown" else ""
            print(f"lobby-client: HTTP {status}{detail}", file=sys.stderr)
            return 1
        if args.route == "chat":
            if (
                set(payload) != {"conversation_id", "reply"}
                or payload["conversation_id"] != conversation_id
                or not isinstance(payload["reply"], str)
                or any(secret in value for value in payload.values())
            ):
                raise ValueError
        elif payload != {"status": "ok", "model": adapter.MODEL}:
            raise ValueError
        print(json.dumps(payload))
        return 0
    except (adapter.ConfigError, adapter.RequestRejected, http.client.HTTPException, OSError, ValueError):
        detail = " Check the conversation before retrying a submitted chat." if args.route == "chat" else ""
        print("lobby-client: request could not be completed." + detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
