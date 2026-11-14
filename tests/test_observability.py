"""Private observability endpoint, fixed-cardinality metrics and safe HTTP traces."""
import http.client
import json
import os
import secrets
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from shards_mcp.core import Gateway
from shards_mcp.observability import RequestMetrics, route_class
from shards_mcp.server import make_handler


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token = secrets.token_urlsafe(48)
        self.gateway = Gateway(os.path.join(self.temp.name, "state.sqlite"), self.token)
        self.metric = RequestMetrics()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
            make_handler(self.gateway, set(), metrics=self.metric))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, method, path, token=None, body=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        client.request(method, path, body=body, headers=headers)
        response = client.getresponse()
        code, data, headers = response.status, response.read().decode(), dict(response.getheaders())
        client.close()
        return code, data, headers

    def test_private_prometheus_scrape_requires_operator_and_local_peer(self):
        worker = self.gateway.register(self.gateway.authenticate(self.token),
            "reader", "test", [], ["agent:read"])
        self.assertEqual(self.request("GET", "/metrics")[0], 401)
        self.assertEqual(self.request("GET", "/metrics", worker["token"])[0], 403)
        self.assertEqual(self.request("GET", "/metrics", "bogus")[0], 403)
        self.assertEqual(self.request("GET", "/health/live")[0], 200)
        self.assertEqual(self.request("GET", "/health/ready")[0], 200)

        status, body, headers = self.request("GET", "/metrics", self.token)
        self.assertEqual(status, 200)
        self.assertIn("text/plain", headers["Content-Type"])
        self.assertIn("shards_http_requests_total", body)
        self.assertIn('route="metrics",method="GET",status="401"', body)
        self.assertIn('route="health",method="GET",status="200"', body)
        self.assertIn("shards_http_request_duration_seconds_bucket", body)
        self.assertIn("shards_state_agents 1", body)
        self.assertNotIn(self.token, body)
        self.assertNotIn(worker["agent_id"], body)
        self.assertIn("X-Request-ID", headers)
        self.assertEqual(len(headers["X-Request-ID"]), 16)

    def test_metrics_route_classifier_has_no_unbounded_agent_ids(self):
        first = "/a2a/agents/agt_111111111111111111111111/card"
        second = "/a2a/agents/agt_ffffffffffffffffffffffff/card"
        self.assertEqual(route_class(first), "a2a")
        self.assertEqual(route_class(second), "a2a")
        self.assertEqual(route_class("/mcp?token=REDACT"), "mcp")
        self.assertEqual(route_class("/untrusted/secret=123"), "other")
        for i in range(300):
            self.metric.observe("GET", "/a2a/agents/agt_" + str(i), 200, 0.02)
        with self.gateway.read_tx() as db:
            body = self.metric.render(db)
        self.assertIn('route="a2a",method="GET",status="200"} 300', body)
        self.assertNotIn("agt_200", body)
        self.assertNotIn("secret=123", body)
        self.assertIn('le="+Inf"} 300', body)

    def test_metrics_gauges_reflect_durable_queue_state(self):
        origin = self.gateway.register(self.gateway.authenticate(self.token),
            "origin", "test", [], ["task:create", "task:cancel"])
        worker = self.gateway.register(self.gateway.authenticate(self.token),
            "worker", "test", [], ["task:read", "task:claim"])
        self.gateway.delegation_grant(self.gateway.authenticate(self.token),
                                      origin["agent_id"], worker["agent_id"])
        creator = self.gateway.authenticate(origin["token"])
        created = self.gateway.task_create(
            creator, worker["agent_id"], {"action": "health"}, "metrics-queued"
        )
        code, body, _ = self.request("GET", "/metrics", self.token)
        self.assertEqual(code, 200)
        self.assertIn("shards_state_tasks_queued 1", body)
        self.assertIn("shards_state_tasks_canceled 0", body)
        self.assertIn("shards_state_agents 2", body)

        self.gateway.task_cancel(creator, created["task_id"])
        code, body, _ = self.request("GET", "/metrics", self.token)
        self.assertEqual(code, 200)
        self.assertIn("shards_state_tasks_queued 0", body)
        self.assertIn("shards_state_tasks_canceled 1", body)
        self.assertEqual(
            sum(int(line.split()[-1]) for line in body.splitlines()
                if line.startswith("shards_state_tasks_")), 1,
            "every persisted task must be reflected in exactly one state gauge",
        )


if __name__ == "__main__":
    unittest.main()
