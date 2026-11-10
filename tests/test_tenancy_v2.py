"""PostgreSQL tenant binding: pure-Python denial and real PG RLS acceptance."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shards_mcp.tenancy_v2 import (
    TenantBoundaryError, TenantMembershipAuthority, TokenClaims,
)

ORG_A = "00000000-0000-4000-8000-000000000001"
ORG_B = "00000000-0000-4000-8000-000000000002"
ISSUER = "https://issuer.example.invalid"
RESOURCE = "https://mcp.example.invalid/mcp"


def claims(subject="alice-a", scopes=("task:read", "agent:read")):
    now = int(time.time())
    return TokenClaims(
        issuer=ISSUER, audience=RESOURCE, subject=subject,
        scopes=scopes, issued_at=now-30, expires_at=now+120,
    )


class DenyBeforeDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.authority = TenantMembershipAuthority(issuer=ISSUER, resource=RESOURCE)

    def test_claims_shape_expiry_audience_and_lifetime(self):
        base = claims()
        bad = [
            replace(base, issuer="https://other-issuer.invalid"),
            replace(base, audience="https://wrong.example.invalid/mcp"),
            replace(base, subject=""),
            replace(base, scopes=("*",)),
            replace(base, scopes=("task:read", "unknown")),
            replace(base, scopes="task:read"),
            replace(base, expires_at=int(time.time())-1),
            replace(base, issued_at=int(time.time())-400, expires_at=int(time.time())+30),
            replace(base, issued_at=int(time.time())+60),
            replace(base, issued_at=True),
        ]
        for identity in bad:
            with self.subTest(identity=identity), self.assertRaises(TenantBoundaryError):
                with self.authority.bind(None, identity, ORG_A):
                    self.fail("untrusted token passed")
        with self.assertRaises(TenantBoundaryError):
            with self.authority.bind(None, object(), ORG_A):
                self.fail("untrusted object passed")

    def test_noncanonical_or_missing_org_is_denied_before_sql(self):
        for org in (None, "not-a-uuid", ORG_A.upper(), ORG_A + " ", "00000000-0000-4000-8000-000000000000"):
            with self.subTest(org=org), self.assertRaises(TenantBoundaryError):
                with self.authority.bind(None, claims(), org):
                    self.fail("invalid transaction passed")

    def test_nonidle_or_nonautocommit_connection_is_denied(self):
        for autocommit, status in [(False, 0), (True, 1), (True, 2)]:
            fake = SimpleNamespace(autocommit=autocommit, info=SimpleNamespace(transaction_status=status))
            with self.subTest(status=status), self.assertRaises(TenantBoundaryError):
                with self.authority.bind(fake, claims(), ORG_A):
                    self.fail("unsafe connection accepted")


class FakeCursor:
    def __init__(self, row):
        self.row = row
    def fetchone(self):
        return self.row
    def fetchall(self):
        return self.row


class FakeConnection:
    autocommit = True
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=0)
        self.sql = []
        self.ended = False
    @contextmanager
    def transaction(self):
        self.ended = False
        self.info.transaction_status = 2
        try:
            yield
        finally:
            self.info.transaction_status = 0
            self.ended = True
    def execute(self, query, values):
        self.sql.append((query, values))
        if "set_config" in query:
            return FakeCursor(None)
        if "JOIN shards_v2.memberships" in query:
            return FakeCursor(("agt_a_creator", ["task:read", "agent:read"], "member", "user"))
        if "FROM shards_v2.tasks" in query:
            return FakeCursor(("tsk_a", "queued", "agt_a_creator", "agt_a_worker", {}, None))
        if "FROM shards_v2.principals" in query:
            return FakeCursor([("agt_a_worker", "Worker", "agent", "active")])
        raise AssertionError("unexpected SQL from tenant adapter")


class FacadeContractTests(unittest.TestCase):
    def test_bounded_operations_and_expired_scope(self):
        conn = FakeConnection()
        auth = TenantMembershipAuthority(issuer=ISSUER, resource=RESOURCE)
        with auth.bind(conn, claims(), ORG_A, required_scope="task:read") as tenant:
            self.assertEqual(tenant.org_id, ORG_A)
            self.assertEqual(tenant.task_get("tsk_a")["creator_id"], "agt_a_creator")
            self.assertEqual(tenant.agent_directory()[0]["name"], "Worker")
            self.assertNotIn("execute", dir(tenant))
            self.assertEqual(conn.sql[0][1], (ORG_A,))
            self.assertEqual(conn.sql[1][1], (ORG_A, ISSUER, "alice-a"))
            self.assertEqual(conn.sql[2][1], (ORG_A, "tsk_a", "agt_a_creator", "agt_a_creator"))
        self.assertTrue(conn.ended)
        with self.assertRaisesRegex(TenantBoundaryError, "ended"):
            tenant.task_get("tsk_a")

    def test_scope_and_input_denials(self):
        auth = TenantMembershipAuthority(issuer=ISSUER, resource=RESOURCE)
        with self.assertRaises(TenantBoundaryError):
            with auth.bind(FakeConnection(), claims(), ORG_A, required_scope="task:claim"):
                pass
        with auth.bind(FakeConnection(), claims(), ORG_A) as tenant:
            for bad in (123, "", "a" * 201):
                with self.assertRaises(TenantBoundaryError):
                    tenant.task_get(bad)
            for bad in (True, 0, 101):
                with self.assertRaises(TenantBoundaryError):
                    tenant.agent_directory(bad)


@unittest.skipUnless(os.getenv("SHARDS_V2_PG_DSN"),
                     "requires isolated PostgreSQL 17 test instance and synthetic fixture")
class PostgreSQLAuthorityContractTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(os.environ["SHARDS_V2_PG_DSN"], autocommit=True)
        self.authority = TenantMembershipAuthority(issuer=ISSUER, resource=RESOURCE)

    def tearDown(self):
        self.conn.close()

    def test_valid_org_a_task_and_hygiene(self):
        with self.authority.bind(self.conn, claims(), ORG_A, required_scope="task:read") as tenant:
            self.assertEqual(tenant.principal_id, "agt_a_creator")
            self.assertEqual(tenant.role, "member")
            self.assertEqual(tenant.task_get("tsk_a")["state"], "queued")
            self.assertIsNone(tenant.task_get("missing"))
            agents = tenant.agent_directory()
            self.assertTrue(all(a["kind"] == "agent" for a in agents))
            self.assertNotIn("agt_b_worker", [a["principal_id"] for a in agents])
            setting = self.conn.execute("SELECT current_setting('shards.org_id',true)").fetchone()[0]
            self.assertEqual(setting, ORG_A)
        # Verify top-level transaction ended; SET LOCAL and RLS context are gone.
        result = self.conn.execute("SELECT current_setting('shards.org_id',true)").fetchone()[0]
        self.assertIn(result, (None, ""))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM shards_v2.tasks").fetchone()[0], 0)

    def test_wrong_org_or_revoked_identity_fails_without_ambient_context(self):
        for token, org in [(claims(), ORG_B),
                           (claims("bob-b"), ORG_A),
                           (claims("revoked-a"), ORG_A)]:
            with self.subTest(subject=token.subject, org=org), self.assertRaises(TenantBoundaryError):
                with self.authority.bind(self.conn, token, org):
                    self.fail("wrong membership accepted")
            self.assertEqual(self.conn.execute(
                "SELECT count(*) FROM shards_v2.principals").fetchone()[0], 0)
        with self.authority.bind(self.conn, claims("bob-b"), ORG_B) as tenant:
            self.assertEqual(tenant.principal_id, "agt_b_worker")
            self.assertIsNone(tenant.task_get("tsk_a"))
            self.assertTrue(all(a["principal_id"] == "agt_b_worker"
                                for a in tenant.agent_directory()))

    def test_auditor_role_attenuates_token_and_database_scopes(self):
        with self.authority.bind(self.conn,
                                 claims("auditor-a", ("task:read", "task:claim")),
                                 ORG_A) as tenant:
            self.assertEqual(tenant.role, "auditor")
            self.assertEqual(tenant.scopes, ("task:read",))
            with self.assertRaises(TenantBoundaryError):
                tenant.require("task:claim")
            # Auditor still cannot read another task without being its party.
            self.assertIsNone(tenant.task_get("tsk_a"))

    def test_failed_scope_check_rolls_back_local_org_setting(self):
        with self.assertRaises(TenantBoundaryError):
            with self.authority.bind(self.conn, claims(), ORG_A,
                                     required_scope="task:claim"):
                pass
        self.assertIn(self.conn.execute(
            "SELECT current_setting('shards.org_id',true)").fetchone()[0], (None, ""))


if __name__ == "__main__":
    unittest.main()
