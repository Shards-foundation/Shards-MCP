"""Single-instance external scheduler and expired-lease sweeper.

This is an operational supervisor, NOT a distributed scheduler. Run exactly
one instance against a SQLite database to avoid redundant operator overhead.
The task dispatcher itself is transactionally protected and remains idempotent
per interval, but no multi-host leader election is provided.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading

from .config import admin_token_from_environment
from .core import Gateway, GatewayError


def run_cycle(gateway: Gateway) -> dict[str, int]:
    root = gateway.authenticate(admin_token_from_environment())
    result = gateway.schedule_tick(root)
    blocked = gateway.expired(root)
    return {"dispatched": len(result["dispatched"]), "leases_blocked": len(blocked)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Shards single-host scheduling supervisor")
    parser.add_argument("--once", action="store_true", help="Run one schedule/expiry cycle and exit")
    parser.add_argument("--interval-seconds", type=int,
                        default=int(os.getenv("SHARDS_SCHEDULER_INTERVAL_SECONDS", "30")))
    options = parser.parse_args()
    if not 5 <= options.interval_seconds <= 3600:
        parser.error("interval must be between 5 and 3600 seconds")
    try:
        token = admin_token_from_environment()
        gateway = Gateway(os.getenv("SHARDS_DB", "shards.db"), token)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            principal = gateway.authenticate(token)
            created = gateway.schedule_tick(principal)
            blocked = gateway.expired(principal)
            sys.stderr.write(json.dumps({
                "event": "scheduler_cycle", "dispatched": len(created["dispatched"]),
                "leases_blocked": len(blocked),
            }, separators=(",", ":")) + "\n")
        except (OSError, GatewayError, ValueError) as exc:
            # Never print credentials, schedule/task payloads or raw SQL.
            sys.stderr.write(json.dumps({
                "event": "scheduler_error", "error_type": type(exc).__name__,
            }) + "\n")
            if options.once:
                raise SystemExit(1) from None
        if options.once:
            break
        stop.wait(options.interval_seconds)


if __name__ == "__main__":
    main()
