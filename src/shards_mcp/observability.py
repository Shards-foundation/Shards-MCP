"""Bounded-cardinality, dependency-free operational telemetry.

Only fixed route/method/status labels are exported. Never use caller IDs, task IDs,
paths, tokens, host names, user content or request bodies as metric labels.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import threading
import time
from typing import Any

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
ROUTES = frozenset(("health", "mcp", "rest", "a2a", "oauth_metadata", "metrics", "other"))
STATES = ("queued", "running", "reported", "blocked", "succeeded", "failed")


def route_class(path: str) -> str:
    """Classify arbitrary paths into a fixed finite label set."""
    base = path.split("?", 1)[0]
    if base.startswith("/health/"):
        return "health"
    if base == "/mcp":
        return "mcp"
    if base == "/v1/tools" or base.startswith("/v1/tools/"):
        return "rest"
    if base.startswith("/a2a/"):
        return "a2a"
    if base.startswith("/.well-known/oauth-protected-resource"):
        return "oauth_metadata"
    if base == "/metrics":
        return "metrics"
    return "other"


class RequestMetrics:
    """Thread-safe counters and cumulative response-time histograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._count: Counter[tuple[str, str, str]] = Counter()
        self._hist: Counter[tuple[str, str, str]] = Counter()
        self._duration: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_count: Counter[tuple[str, str]] = Counter()

    def observe(self, method: str, path: str, status: int, elapsed: float) -> None:
        route = route_class(path)
        method = method if method in ("GET", "POST", "HEAD", "OPTIONS") else "OTHER"
        status_label = str(status) if 100 <= status <= 599 else "other"
        elapsed = max(0.0, elapsed)
        with self._lock:
            self._count[(route, method, status_label)] += 1
            key = (route, method)
            self._duration[key] += elapsed
            self._duration_count[key] += 1
            for threshold in BUCKETS:
                if elapsed <= threshold:
                    self._hist[(route, method, str(threshold))] += 1
            self._hist[(route, method, "+Inf")] += 1

    @staticmethod
    def _counts(db: Any) -> dict[str, int]:
        counts = {state: 0 for state in STATES}
        for row in db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state"):
            if row[0] in counts:
                counts[row[0]] = int(row[1])
        return {
            **{"tasks_" + key: val for key, val in counts.items()},
            "agents": int(db.execute("SELECT COUNT(*) FROM agents WHERE revoked=0").fetchone()[0]),
            "messages_unacknowledged": int(
                db.execute("SELECT COUNT(*) FROM messages WHERE read_at IS NULL").fetchone()[0]),
            "schedules_active": int(
                db.execute("SELECT COUNT(*) FROM schedules WHERE enabled=1").fetchone()[0]),
        }

    def render(self, db: Any) -> str:
        """Prometheus exposition format (0.0.4); database aggregation is read-only."""
        with self._lock:
            counts = list(self._count.items())
            hist = dict(self._hist)
            durations = dict(self._duration)
            duration_counts = dict(self._duration_count)
            uptime = max(0.0, time.monotonic() - self._started)

        lines = [
            "# HELP shards_uptime_seconds Seconds since the gateway process created its telemetry.",
            "# TYPE shards_uptime_seconds gauge",
            "shards_uptime_seconds %.6f" % uptime,
            "# HELP shards_http_requests_total HTTP responses by bounded route, method and status.",
            "# TYPE shards_http_requests_total counter",
        ]
        for (route, method, status), count in sorted(counts):
            lines.append(
                f'shards_http_requests_total{{route="{route}",method="{method}",status="{status}"}} {count}')
        lines += [
            "# HELP shards_http_request_duration_seconds HTTP response latency in seconds.",
            "# TYPE shards_http_request_duration_seconds histogram",
        ]
        for route, method in sorted(duration_counts):
            for threshold in BUCKETS:
                lines.append(
                    f'shards_http_request_duration_seconds_bucket{{route="{route}",method="{method}",le="{threshold}"}} '
                    f'{hist.get((route, method, str(threshold)), 0)}')
            lines.append(
                f'shards_http_request_duration_seconds_bucket{{route="{route}",method="{method}",le="+Inf"}} '
                f'{hist.get((route, method, "+Inf"), 0)}')
            lines.append(
                f'shards_http_request_duration_seconds_sum{{route="{route}",method="{method}"}} '
                f'{durations[(route, method)]:.6f}')
            lines.append(
                f'shards_http_request_duration_seconds_count{{route="{route}",method="{method}"}} '
                f'{duration_counts[(route, method)]}')
        values = self._counts(db)
        for key, value in sorted(values.items()):
            metric = "shards_state_" + key
            lines.extend([f"# TYPE {metric} gauge", f"{metric} {value}"])
        return "\n".join(lines) + "\n"
