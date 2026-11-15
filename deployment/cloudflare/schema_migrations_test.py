"""Deterministic SQLite verification of the reconciled Cloudflare D1 schema/audit SQL.

No network or production D1 reads/writes. SQLite itself executes the same SQL
embedded in the actual Worker; native Cloudflare D1 E2E remains a release gate.
"""
import pathlib
import re
import sqlite3
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FULL_SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")
LEGACY_SCHEMA = FULL_SCHEMA.split("-- Production schema reconciliation", 1)[0]
MIGRATIONS = sorted((HERE / "migrations").glob("000[2-4]*.sql"))
WORKER_SOURCE = (HERE / "worker.js").read_text(encoding="utf-8")
EXPECTED_TABLES = {
    "tenants", "agents", "access_tokens", "agent_messages", "agent_tasks",
    "audit_events", "route_budgets", "operator_accounts", "operator_api_keys",
    "operator_ssh_keys", "operator_skills", "agent_connection_activity",
}


def schema_objects(db):
    return {
        (kind, name)
        for kind, name in db.execute(
            "SELECT type,name FROM sqlite_master "
            "WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%'"
        )
    }


def schema_definitions(db):
    # Compare complete SQL declarations, not just matching object names.
    return {
        (kind, name): re.sub(r"\s+", " ", ddl.strip()).lower()
        for kind, name, ddl in db.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE type IN ('table','index') AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        )
    }


def db_from_schema(sql):
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(sql)
    return db


def insert_queued_task(db):
    db.execute(
        "INSERT INTO agents(id,tenant_id,name,client,scopes,created_by,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("test-agent", "shards-internal", "TestAgent", "test", '["task:claim"]',
         "synthetic-owner", "2026-11-15T00:00:00Z"),
    )
    db.execute(
        "INSERT INTO agent_tasks(id,tenant_id,creator_id,assignee_id,title,input_json,"
        "state,created_at,request_key) VALUES(?,?,?,?,?,?,?,?,?)",
        ("task-id", "shards-internal", "test-agent", "test-agent", "Test",
         '{"synthetic":true}', "queued", "2026-11-15T00:00:00Z", "test-request"),
    )


def transition_sql_from_worker():
    start = WORKER_SOURCE.index("function auditForTransition(")
    fragment = WORKER_SOURCE[start:start + 850]
    match = re.search(r'env\.EDGE_DB\.prepare\("([^"]+)"\)', fragment)
    if not match:
        raise AssertionError("Cannot find actual audit transition SQL in Worker source")
    return match.group(1)


class ReconciledD1SQL(unittest.TestCase):
    def test_schema_contains_all_live_tables_and_indexes(self):
        self.assertEqual(len(MIGRATIONS), 3)
        db = db_from_schema(FULL_SCHEMA)
        tables = {name for kind, name in schema_objects(db) if kind == "table"}
        self.assertEqual(tables, EXPECTED_TABLES)
        for table, required_columns in {
            "operator_accounts": {"id", "theme", "revision", "deleted_at"},
            "operator_api_keys": {"owner_id", "token_sha256", "revoked_at"},
            "operator_skills": {"source_type", "content", "content_sha256"},
            "agent_connection_activity": {"first_authenticated_at", "last_authenticated_at", "last_operation"},
        }.items():
            columns = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
            self.assertTrue(required_columns <= columns, (table, columns))
        db.close()

    def test_legacy_schema_upgrades_to_fresh_schema_without_losing_data(self):
        upgraded = db_from_schema(LEGACY_SCHEMA)
        upgraded.execute(
            "INSERT INTO agents(id,tenant_id,name,client,scopes,created_by,created_at) "
            "VALUES('existing-agent','shards-internal','Existing','test','[]','owner','2026-11-15')"
        )
        for _ in range(2):
            for file in MIGRATIONS:
                upgraded.executescript(file.read_text(encoding="utf-8"))
        fresh = db_from_schema(FULL_SCHEMA)
        self.assertEqual(schema_objects(upgraded), schema_objects(fresh))
        self.assertEqual(schema_definitions(upgraded), schema_definitions(fresh),
                         "Upgrade/fresh declarations must match columns, checks, keys and indexes")
        required_indexes = {
            "idx_access_agent", "idx_inbox", "idx_tasks_assignee", "idx_audit_time",
            "idx_operator_api_keys_owner", "idx_operator_ssh_keys_owner",
            "idx_agents_created_by", "idx_operator_skills_owner",
            "idx_agent_connection_last_seen"
        }
        actual = {name for kind,name in schema_objects(upgraded) if kind == "index"}
        self.assertTrue(required_indexes <= actual, required_indexes - actual)
        skills_columns = {row[1]: row for row in upgraded.execute("PRAGMA table_info(operator_skills)")}
        self.assertEqual(skills_columns["content_sha256"][3],1,"Digest must be NOT NULL")
        self.assertEqual(skills_columns["name"][3],1,"Skill name must be NOT NULL")
        fkeys = list(upgraded.execute("PRAGMA foreign_key_list(operator_skills)"))
        self.assertTrue(any(row[2]=="operator_accounts" for row in fkeys))
        self.assertEqual(upgraded.execute("SELECT COUNT(*) FROM agents WHERE id='existing-agent'").fetchone()[0], 1)
        upgraded.close()
        fresh.close()

    def test_successful_task_transition_also_writes_audit(self):
        db = db_from_schema(FULL_SCHEMA)
        insert_queued_task(db)
        db.execute("BEGIN IMMEDIATE")
        result = db.execute(
            "UPDATE agent_tasks SET state='claimed',claimed_at=? "
            "WHERE id=? AND tenant_id=? AND assignee_id=? AND state='queued' "
            "RETURNING id,title,input_json,state",
            ("2026-11-15T12:00:00Z", "task-id", "shards-internal", "test-agent"),
        ).fetchall()
        db.execute(transition_sql_from_worker(), (
            "audit-ok", "shards-internal", "test-agent", "shards_task_claim",
            "task-id", "accepted", "2026-11-15T12:00:00Z",
        ))
        db.execute("COMMIT")
        self.assertEqual(result[0][-1], "claimed")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 1)
        db.close()

    def test_zero_match_cannot_commit_a_false_positive_audit(self):
        db = db_from_schema(FULL_SCHEMA)
        insert_queued_task(db)
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            "UPDATE agent_tasks SET state='claimed' WHERE id='wrong-task' RETURNING id"
        ).fetchall()
        self.assertEqual(changed, [])
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(transition_sql_from_worker(), (
                "audit-deny", "shards-internal", "test-agent", "shards_task_claim",
                "wrong-task", "accepted", "2026-11-15T12:00:00Z",
            ))
        db.execute("ROLLBACK")
        self.assertEqual(db.execute("SELECT state FROM agent_tasks WHERE id='task-id'").fetchone()[0], "queued")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)
        db.close()

    def test_injected_audit_write_failure_rolls_back_prior_state_transition(self):
        db = db_from_schema(FULL_SCHEMA)
        insert_queued_task(db)
        db.execute(
            "CREATE TRIGGER deny_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ROLLBACK,'injected audit storage failure'); END"
        )
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_tasks SET state='claimed' WHERE id='task-id'")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(transition_sql_from_worker(), (
                "audit-fail", "shards-internal", "test-agent", "shards_task_claim",
                "task-id", "accepted", "2026-11-15T12:00:00Z",
            ))
        self.assertFalse(db.in_transaction,
                         "Injected audit failure must automatically roll back the whole transaction")
        self.assertEqual(db.execute("SELECT state FROM agent_tasks WHERE id='task-id'").fetchone()[0], "queued")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
