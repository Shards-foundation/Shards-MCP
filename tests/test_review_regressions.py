import secrets
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
        self.token = secrets.token_urlsafe(48)
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
        for evidence in ({}, [], 0, False, None, "", "short", {"x": None}, [None], {"": ""}, {"outer": [None, {}]}):
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
        self.assertFalse(any(proxies), "environment proxy must not be active")
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

    def test_stdio_rejects_excessively_nested_json(self):
        class FakeClient:
            pass
        nested = "[" * 1300 + "0" + "]" * 1300
        result = request_line(FakeClient(),
                              '{"jsonrpc":"2.0","id":7,"method":"tools/list","params":' + nested + '}')
        self.assertEqual(json.loads(result)["error"]["code"], -32700)

    def test_stdio_rejects_nonfinite_without_crashing(self):
        class FakeClient:
            pass
        # Parsed nonfinite JSON must never make canonical() kill the bridge loop.
        answer = request_line(FakeClient(), '{"jsonrpc":"2.0","id":99,"method":"ping","params":{"value":NaN}}')
        self.assertEqual(json.loads(answer)["error"]["code"], -32600)


    def test_task_creator_cannot_self_attest(self):
        origin = self.g.register(self.root, "creator-verifier", "test", [],
                                 ["task:create", "task:verify", "task:read"])
        creator = self.g.authenticate(origin["token"])
        task = self.g.task_create(creator, self.id_b, {"action": "health"}, "creator-self")["task_id"]
        self.g.task_claim(self.b, task)
        self.g.task_complete(self.b, task, True, {"ok": True})
        with self.assertRaises(GatewayError) as denial:
            self.g.task_verify(creator, task, True, {"summary": "self-confirmation"})
        self.assertEqual(denial.exception.code, "FORBIDDEN")
        independent = self.g.register(self.root, "different-verifier", "test", [],
                                      ["task:verify", "task:read"])
        self.assertEqual(self.g.task_verify(self.g.authenticate(independent["token"]),
                                            task, True, {"summary": "checked externally"})["state"],
                         "succeeded")

    def test_sqlite_cursor_bounds_are_enforced(self):
        for operation in (lambda: self.g.message_poll(self.b, after_seq=2**70),
                          lambda: self.g.event_poll(self.root, after_seq=2**70)):
            with self.assertRaises(GatewayError):
                operation()

    def test_cursor_can_reach_oldest_messages_beyond_default_limit(self):
        for index in range(115):
            self.g.send(self.a, self.id_b, {"number": index}, "message-" + str(index))
        cursor = 0
        received = []
        for _ in range(4):
            page = self.g.message_poll(self.b, after_seq=cursor, limit=40)
            received.extend(m["body"]["number"] for m in page["messages"])
            cursor = page["next_cursor"]
        self.assertEqual(received, list(range(115)))
        self.assertEqual(self.g.message_poll(self.a)["messages"], [])
        with self.assertRaises(GatewayError):
            self.g.message_poll(self.b, after_seq=-1)
        first = self.g.message_poll(self.b, limit=1)["messages"][0]
        self.g.message_ack(self.b, first["id"])
        self.assertEqual(self.g.message_poll(self.b, limit=1)["messages"][0]["body"]["number"], 1)
        self.assertEqual(self.g.message_poll(self.b, limit=1, unread_only=False)["messages"][0]["body"]["number"], 0)

    def test_schedules_can_be_stopped_and_cannot_target_revoked_workers(self):
        schedule = self.g.schedule_create(self.root, self.id_b, {"action": "health"}, 60)["schedule_id"]
        self.assertIn(schedule, [x["id"] for x in self.g.schedule_list(self.root)])
        with self.g.tx() as db:
            db.execute("UPDATE schedules SET next_due='2000-01-01T00:00:00+00:00' WHERE id=?", (schedule,))
        self.g.revoke(self.root, self.id_b)
        self.assertEqual(self.g.schedule_tick(self.root)["dispatched"], [])
        self.assertEqual(self.g.schedule_disable(self.root, schedule)["enabled"], False)
        self.assertEqual(self.g.schedule_tick(self.root)["dispatched"], [])
        with self.assertRaises(GatewayError):
            self.g.schedule_disable(self.root, schedule)


    def test_event_topic_isolation_and_global_audit_confinement(self):
        writer = self.g.register(self.root, "event-writer", "test", [],
                                 ["event:write", "event:read", "audit:read"])
        actor = self.g.authenticate(writer["token"])
        outsider = self.g.register(self.root, "event-reader", "test", [],
                                   ["event:write", "event:read", "audit:read"])
        reader = self.g.authenticate(outsider["token"])

        own = "agent." + actor.agent_id + ".progress"
        self.g.event_publish(actor, own, {"private": True}, "private-1")
        self.g.event_publish(actor, "shared.progress", {"broadcast": True}, "shared-1")
        self.g.event_publish(self.root, "system.policy", {"internal": True}, "system-1")
        with self.assertRaises(GatewayError):
            self.g.event_publish(actor, "system.policy", {"fake": True}, "fake-1")
        with self.assertRaises(GatewayError):
            self.g.event_publish(actor, "agent." + reader.agent_id + ".progress", {}, "fake-2")
        with self.assertRaises(GatewayError):
            self.g.event_poll(reader, topic=own)
        seen = self.g.event_poll(reader)["events"]
        self.assertEqual([x["topic"] for x in seen], ["shared.progress"])
        self.assertEqual({x["topic"] for x in self.g.event_poll(actor)["events"]},
                         {own, "shared.progress"})
        self.assertEqual(len(self.g.event_poll(self.root)["events"]), 3)
        self.assertEqual(self.g.audit_list(reader), [])
        actions = {x["action"] for x in self.g.audit_list(actor)}
        self.assertEqual(actions, {"event.publish"})


class ReviewHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = secrets.token_urlsafe(48)
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

    def test_ready_does_not_require_database_writer_lock(self):
        with self.g.tx() as db:
            db.execute("UPDATE agents SET last_seen=last_seen")
            c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
            started = time.monotonic()
            c.request("GET", "/health/ready")
            response = c.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            self.assertLess(time.monotonic() - started, 1.0)
            c.close()

    def test_large_content_length_header_rejected_cleanly(self):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        c.putrequest("POST", "/mcp")
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", "1" * 5000)
        c.endheaders()
        response = c.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        c.close()

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
