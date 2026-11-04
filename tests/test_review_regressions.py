"""Regressions for independent review of PR #1 (B1-B4 and transport hardening)."""
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import make_handler, BoundedHTTPServer
from shards_mcp.worker import AgentClient
from shards_mcp.stdio import request_line


class ReviewCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "state.sqlite")
        self.token = "R" * 48
        self.g = Gateway(self.path, self.token)
        self.root = self.g.authenticate(self.token)
        scopes = ["agent:heartbeat", "task:create", "task:read", "task:claim",
                  "task:update", "checkpoint:write", "message:send", "message:read"]
        a = self.g.register(self.root, "origin", "test", [], scopes)
        b = self.g.register(self.root, "worker", "test", [], scopes)
        self.a, self.b = self.g.authenticate(a["token"]), self.g.authenticate(b["token"])
        self.id_a, self.id_b = self.a.agent_id, self.b.agent_id

    def tearDown(self):
        self.temp.cleanup()

    def test_authentication_does_not_acquire_write_lock(self):
        # A read-only authentication query must be possible during BEGIN IMMEDIATE.
        with self.g.tx() as db:
            db.execute("UPDATE agents SET last_seen=last_seen")
            started = time.monotonic()
            with self.assertRaises(GatewayError):
                self.g.authenticate("not-a-valid-token")
            self.assertEqual(self.g.authenticate(self.token).agent_id, "operator")
            self.assertLess(time.monotonic() - started, 1.0)

    def test_lease_renewal_is_audited_and_bounded(self):
        tid = self.g.task_create(self.a, self.id_b, {"action": "health"}, "renew-test")["task_id"]
        self.g.task_claim(self.b, tid)
        before = self.g.audit_verify(self.root)["count"]
        renewed = self.g.task_renew(self.b, tid, 60)
        self.assertTrue(renewed["lease_until"])
        self.assertEqual(self.g.audit_verify(self.root)["count"], before + 1)
        self.assertEqual(self.g.audit_list(self.root, 1)[0]["action"], "task.renew")
        with self.g.tx() as db:
            old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="microseconds")
            db.execute("UPDATE tasks SET lease_started=? WHERE id=?", (old, tid))
        with self.assertRaises(GatewayError):
            self.g.task_renew(self.b, tid, 60)

    def test_empty_verifications_rejected_and_evidence_retained(self):
        tid = self.g.task_create(self.a, self.id_b, {"action": "health"}, "verify-regression")["task_id"]
        self.g.task_claim(self.b, tid)
        self.g.task_complete(self.b, tid, True, {"ok": True})
        reviewer = self.g.register(self.root, "reviewer", "test", [], ["task:verify", "task:read"])
        verifier = self.g.authenticate(reviewer["token"])
        for evidence in ({}, [], 0, False, None, "", "short"):
            with self.subTest(evidence=evidence):
                with self.assertRaises(GatewayError):
                    self.g.task_verify(verifier, tid, True, evidence)
        approved = {"tests": [{"case": "contract", "result": "pass"}], "sha256": "a" * 64}
        self.assertEqual(self.g.task_verify(verifier, tid, True, approved)["state"], "succeeded")
        persisted = self.g.verification_get(self.a, tid)["verification"]
        self.assertEqual(persisted["evidence"], approved)
        self.assertEqual(persisted["verifier"], verifier.agent_id)
        self.assertTrue(persisted["approved"])
        with self.assertRaises(GatewayError):
            self.g.verification_get(self.b.__class__("intruder", ("task:read",)), tid)

    @unittest.skipUnless(os.name == "posix", "POSIX mode only")
    def test_database_permissions_restrict_world_access(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_agent_client_rejects_proxy_redirect_and_admin_reuse(self):
        client = AgentClient("http://127.0.0.1:8787", "x" * 48)
        from urllib.request import ProxyHandler
        proxies = [h.proxies for h in client.opener.handlers if isinstance(h, ProxyHandler)]
        self.assertEqual(proxies, [{}])
        old = os.environ.get("SHARDS_ADMIN_TOKEN")
        try:
            os.environ["SHARDS_ADMIN_TOKEN"] = "x" * 48
            with self.assertRaises(ValueError):
                AgentClient("http://127.0.0.1:8787", "x" * 48)
        finally:
            if old is None:
                os.environ.pop("SHARDS_ADMIN_TOKEN", None)
            else:
                os.environ["SHARDS_ADMIN_TOKEN"] = old

    def test_stdio_rejects_nonfinite_without_crashing(self):
        class FakeClient:
            pass
        # Parsed nonfinite JSON must never make canonical() kill the bridge loop.
        answer = request_line(FakeClient(), '{"jsonrpc":"2.0","id":99,"method":"ping","params":{"value":NaN}}')
        self.assertEqual(json.loads(answer)["error"]["code"], -32600)


class ReviewHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = "S" * 48
        self.g = Gateway(os.path.join(self.tmp.name, "db.sqlite"), self.token)
        self.server = BoundedHTTPServer(("127.0.0.1", 0), make_handler(self.g, set()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def send(self, path, body, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        h = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json", **(headers or {})}
        c.request("POST", path, body=body, headers=h)
        r = c.getresponse()
        result = r.status, r.read()
        c.close()
        return result

    def test_bad_json_nonfinite_and_excessive_nesting(self):
        self.assertEqual(self.send("/v1/tools/system_status", b'{"value":NaN}')[0], 400)
        nested = ("[" * 1300 + "0" + "]" * 1300).encode()
        self.assertEqual(self.send("/v1/tools/system_status", nested)[0], 400)
        self.assertEqual(self.send("/mcp", b'{"jsonrpc":"2.0","id":1,')[0], 400)

    def test_malformed_unicode_length_rejected_before_auth(self):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        c.putrequest("POST", "/mcp")
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", "\u00b2")
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 411)
        r.read()
        c.close()

    def test_oversize_rejected_and_wrong_type(self):
        self.assertEqual(self.send("/mcp", b"x" * 262145)[0], 413)
        self.assertEqual(self.send("/mcp", b"{}", {"Content-Type": "text/plain"})[0], 415)

    def test_scoped_tool_discovery_does_not_advertise_admin_functions(self):
        worker = self.g.register(self.g.authenticate(self.token), "only-reader", "test", [], ["message:read"])
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        c.request("GET", "/v1/tools", headers={"Authorization": "bearer " + worker["token"]})
        r = c.getresponse()
        payload = json.loads(r.read())
        self.assertEqual(r.status, 200)
        names = {t["name"] for t in payload["tools"]}
        self.assertIn("message_inbox", names)
        self.assertNotIn("agent_register", names)
        self.assertNotIn("task_complete", names)
        self.assertNotIn("system_status", names)
        c.close()

    def test_unauthenticated_request_while_writer_active(self):
        with self.g.tx() as db:
            db.execute("UPDATE agents SET last_seen=last_seen")
            c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
            started = time.monotonic()
            c.request("POST", "/mcp", body=b"{}", headers={
                "Authorization": "Bearer bogus", "Content-Type": "application/json"
            })
            r = c.getresponse()
            self.assertEqual(r.status, 401)
            r.read()
            self.assertLess(time.monotonic() - started, 1.0)
            c.close()


if __name__ == "__main__":
    unittest.main()
