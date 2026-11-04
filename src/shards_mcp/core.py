"""Durable single-organisation control plane. Uses SQLite transactions, not in-memory state.

Security: the caller identity is always derived from the bearer credential, never tool input.
Durability: every write and corresponding audit entry commit in one transaction.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Iterator


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def uid(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(12)


class GatewayError(Exception):
    def __init__(self, message: str, code: str = "INVALID_REQUEST"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Principal:
    agent_id: str
    scopes: tuple[str, ...]

    def require(self, scope: str) -> None:
        if "*" not in self.scopes and scope not in self.scopes:
            raise GatewayError("permission denied", "FORBIDDEN")


SCOPES = (
    "agent:read", "agent:heartbeat", "message:send", "message:read",
    "task:create", "task:read", "task:claim", "task:update", "task:verify",
    "checkpoint:write", "audit:read", "event:read", "event:write",
)


class Gateway:
    def __init__(self, path: str, admin_token: str):
        if len(admin_token) < 32 or len(set(admin_token)) < 12:
            raise ValueError("SHARDS_ADMIN_TOKEN must be >=32 characters with >=12 distinct characters")
        requested = Path(path).expanduser()
        if requested.is_symlink():
            raise ValueError("database path must not be a symbolic link")
        self.path = str(requested.resolve())
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
        self.admin_hash = hashlib.sha256(admin_token.encode()).digest()
        with self.tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, provider TEXT NOT NULL,
                  capabilities TEXT NOT NULL, scopes TEXT NOT NULL,
                  token_hash TEXT NOT NULL UNIQUE, oauth_subject TEXT UNIQUE, created TEXT NOT NULL,
                  last_seen TEXT, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                  id TEXT PRIMARY KEY, source TEXT NOT NULL, destination TEXT NOT NULL,
                  body TEXT NOT NULL, task_id TEXT, idem TEXT,
                  created TEXT NOT NULL, read_at TEXT,
                  UNIQUE(source, idem)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, creator TEXT NOT NULL, assignee TEXT NOT NULL,
                  state TEXT NOT NULL, input TEXT NOT NULL, result TEXT,
                  lease_until TEXT, lease_started TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                  idem TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
                  UNIQUE(creator, idem)
                );
                CREATE TABLE IF NOT EXISTS verifications (
                  task_id TEXT PRIMARY KEY, verifier TEXT NOT NULL,
                  approved INTEGER NOT NULL, evidence TEXT NOT NULL, created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                  task_id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL,
                  body TEXT NOT NULL, created TEXT NOT NULL,
                  PRIMARY KEY(task_id, version)
                );
                CREATE TABLE IF NOT EXISTS schedules (
                  id TEXT PRIMARY KEY, assignee TEXT NOT NULL, input TEXT NOT NULL,
                  interval_seconds INTEGER NOT NULL, next_due TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT NOT NULL, topic TEXT NOT NULL, body TEXT NOT NULL,
                  correlation_id TEXT, idem TEXT NOT NULL, created TEXT NOT NULL,
                  UNIQUE(source, idem)
                );
                CREATE INDEX IF NOT EXISTS idx_events_topic_seq ON events(topic,seq);
                CREATE TABLE IF NOT EXISTS audit (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                  actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL,
                  details TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS audit_reject_update BEFORE UPDATE ON audit
                  BEGIN SELECT RAISE(ABORT, 'audit entries are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS audit_reject_delete BEFORE DELETE ON audit
                  BEGIN SELECT RAISE(ABORT, 'audit entries are immutable'); END;
            """)
            # Migration from existing experimental 0.1 databases.
            agent_columns = {row["name"] for row in db.execute("PRAGMA table_info(agents)")}
            if "oauth_subject" not in agent_columns:
                db.execute("ALTER TABLE agents ADD COLUMN oauth_subject TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_oauth_subject ON agents(oauth_subject)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            if "lease_started" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN lease_started TEXT")
            # Pin existing in-flight leases to a persistent, non-sliding timestamp.
            db.execute("""UPDATE tasks SET lease_started=updated
                          WHERE state='running' AND lease_started IS NULL""")

    @contextmanager
    def read_tx(self) -> Iterator[sqlite3.Connection]:
        # Read-only authentication never waits behind BEGIN IMMEDIATE writer locks.
        db = sqlite3.connect(self.path, timeout=1, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only = ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 15000")
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, db: sqlite3.Connection, actor: str, action: str,
              subject: str, details: dict[str, Any]) -> None:
        last = db.execute("SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last["entry_hash"] if last else "0" * 64
        record = {"at": now(), "actor": actor, "action": action,
                  "subject": subject, "details": details}
        digest = hashlib.sha256((previous + canonical(record)).encode()).hexdigest()
        db.execute("""INSERT INTO audit
          (at,actor,action,subject,details,previous_hash,entry_hash)
          VALUES (?,?,?,?,?,?,?)""",
          (record["at"], actor, action, subject, canonical(details), previous, digest))

    def authenticate(self, token: str) -> Principal:
        if not token:
            raise GatewayError("authentication required", "UNAUTHENTICATED")
        digest = hashlib.sha256(token.encode()).digest()
        if hmac.compare_digest(digest, self.admin_hash):
            return Principal("operator", ("*",))
        with self.read_tx() as db:
            row = db.execute(
                "SELECT id,scopes,revoked FROM agents WHERE token_hash=?",
                (digest.hex(),)).fetchone()
        if not row or row["revoked"]:
            raise GatewayError("invalid credential", "UNAUTHENTICATED")
        return Principal(row["id"], tuple(json.loads(row["scopes"])))

    def authenticate_oauth(self, subject: str, granted: set[str]) -> Principal:
        """Map a verified external identity onto an existing, active Shards agent.

        A signed OAuth scope cannot elevate beyond the operator-registered scopes.
        The special bootstrap operator identity is never available through OAuth.
        """
        if not isinstance(subject, str) or not subject or not granted:
            raise GatewayError("invalid OAuth principal", "UNAUTHENTICATED")
        with self.read_tx() as db:
            row = db.execute(
                "SELECT id,scopes FROM agents WHERE oauth_subject=? AND revoked=0",
                (subject,),
            ).fetchone()
        if not row:
            raise GatewayError("OAuth subject not enrolled or revoked", "UNAUTHENTICATED")
        agent_scopes = set(json.loads(row["scopes"]))
        authorized = sorted(granted & agent_scopes & set(SCOPES))
        if not authorized:
            raise GatewayError("OAuth subject has no matching gateway permissions", "FORBIDDEN")
        return Principal(row["id"], tuple(authorized))

    @staticmethod
    def limit(value: Any, max_bytes: int = 131072) -> str:
        try:
            encoded = canonical(value)
        except (ValueError, RecursionError, TypeError) as exc:
            raise GatewayError("invalid or excessively nested JSON payload") from exc
        if len(encoded.encode("utf-8")) > max_bytes:
            raise GatewayError("payload too large", "PAYLOAD_TOO_LARGE")
        return encoded

    @staticmethod
    def required(value: Any, field: str) -> str:
        if not isinstance(value, str) or not (1 <= len(value) <= 200):
            raise GatewayError(f"{field} must be a non-empty string of <=200 characters")
        return value

    @staticmethod
    def agent_exists(db: sqlite3.Connection, agent_id: str) -> None:
        if not db.execute("SELECT 1 FROM agents WHERE id=? AND revoked=0", (agent_id,)).fetchone():
            raise GatewayError("unknown or revoked agent", "NOT_FOUND")

    def register(self, actor: Principal, name: str, provider: str,
                 capabilities: list[str], scopes: list[str],
                 oauth_subject: str | None = None) -> dict[str, Any]:
        actor.require("*")
        name = self.required(name, "name")
        provider = self.required(provider, "provider")
        if not isinstance(capabilities, list) or any(not isinstance(x, str) or len(x) > 100 for x in capabilities):
            raise GatewayError("invalid capabilities")
        if not isinstance(scopes, list) or any(x not in SCOPES for x in scopes):
            raise GatewayError("invalid scopes; cannot create administrative agent credentials")
        if oauth_subject is not None:
            self.required(oauth_subject, "oauth_subject")
        token = "shards_" + secrets.token_urlsafe(36)
        agent_id = uid("agt")
        with self.tx() as db:
            try:
                db.execute("""INSERT INTO agents
                    (id,name,provider,capabilities,scopes,token_hash,oauth_subject,created)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (agent_id, name, provider, self.limit(capabilities),
                     canonical(sorted(set(scopes))), hashlib.sha256(token.encode()).hexdigest(),
                     oauth_subject, now()))
            except sqlite3.IntegrityError as exc:
                raise GatewayError("agent name already registered", "CONFLICT") from exc
            self.audit(db, actor.agent_id, "agent.register", agent_id,
                       {"name": name, "scopes": sorted(set(scopes)), "oauth_bound": bool(oauth_subject)})
        return {"agent_id": agent_id, "token": token, "scopes": sorted(set(scopes))}

    def revoke(self, actor: Principal, agent_id: str) -> dict[str, Any]:
        actor.require("*")
        with self.tx() as db:
            result = db.execute("UPDATE agents SET revoked=1 WHERE id=? AND revoked=0", (agent_id,))
            if not result.rowcount:
                raise GatewayError("active agent not found", "NOT_FOUND")
            self.audit(db, actor.agent_id, "agent.revoke", agent_id, {})
        return {"revoked": True, "agent_id": agent_id}

    def agents(self, actor: Principal) -> list[dict[str, Any]]:
        actor.require("agent:read")
        with self.tx() as db:
            rows = db.execute("SELECT id,name,provider,capabilities,scopes,created,last_seen,revoked FROM agents").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item["capabilities"])
            item["scopes"] = json.loads(item["scopes"])
            item["revoked"] = bool(item["revoked"])
            if item["revoked"]:
                item["heartbeat_state"] = "revoked"
            elif not item["last_seen"]:
                item["heartbeat_state"] = "unobserved"
            elif (datetime.now(timezone.utc) - datetime.fromisoformat(
                    item["last_seen"])).total_seconds() <= 90:
                item["heartbeat_state"] = "recent"
            else:
                item["heartbeat_state"] = "stale"
            result.append(item)
        return result

    def heartbeat(self, actor: Principal) -> dict[str, Any]:
        actor.require("agent:heartbeat")
        at = now()
        with self.tx() as db:
            result = db.execute("UPDATE agents SET last_seen=? WHERE id=? AND revoked=0",
                                (at, actor.agent_id))
            if not result.rowcount:
                raise GatewayError("agent not found", "NOT_FOUND")
        return {"agent_id": actor.agent_id, "at": at}

    def send(self, actor: Principal, destination: str, body: Any,
             idempotency_key: str, task_id: str | None = None) -> dict[str, Any]:
        actor.require("message:send")
        self.required(idempotency_key, "idempotency_key")
        serialized = self.limit(body)
        with self.tx() as db:
            prev = db.execute("SELECT * FROM messages WHERE source=? AND idem=?",
                              (actor.agent_id, idempotency_key)).fetchone()
            if prev:
                if prev["destination"] != destination or prev["body"] != serialized or prev["task_id"] != task_id:
                    raise GatewayError("idempotency key reused with different payload", "CONFLICT")
                return {"message_id": prev["id"], "deduplicated": True}
            self.agent_exists(db, destination)
            message_id = uid("msg")
            db.execute("""INSERT INTO messages
                 (id,source,destination,body,task_id,idem,created)
                 VALUES (?,?,?,?,?,?,?)""",
                 (message_id, actor.agent_id, destination, serialized, task_id, idempotency_key, now()))
            self.audit(db, actor.agent_id, "message.send", message_id,
                       {"destination": destination, "task_id": task_id, "payload_sha256": hashlib.sha256(serialized.encode()).hexdigest()})
        return {"message_id": message_id, "deduplicated": False}

    def inbox(self, actor: Principal, limit: int = 50) -> list[dict[str, Any]]:
        actor.require("message:read")
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise GatewayError("limit must be 1..100")
        with self.tx() as db:
            if actor.agent_id == "operator":
                rows = db.execute("SELECT * FROM messages ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM messages WHERE destination=? ORDER BY created DESC LIMIT ?",
                                  (actor.agent_id, limit)).fetchall()
        return [{**dict(r), "body": json.loads(r["body"])} for r in rows]


    def message_poll(self, actor: Principal, after_seq: int = 0, limit: int = 50,
                     unread_only: bool = True) -> dict[str, Any]:
        """Monotonic message cursor; never strand older messages behind a newest-N window."""
        actor.require("message:read")
        if type(after_seq) is not int or not 0 <= after_seq <= 2**62:
            raise GatewayError("after_seq must be non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise GatewayError("limit must be 1..100")
        if type(unread_only) is not bool:
            raise GatewayError("unread_only must be boolean")
        filters = ["rowid > ?"]
        params: list[Any] = [after_seq]
        if actor.agent_id != "operator":
            filters.append("destination=?")
            params.append(actor.agent_id)
        if unread_only:
            filters.append("read_at IS NULL")
        params.append(limit)
        query = "SELECT rowid AS sequence,* FROM messages WHERE " + " AND ".join(filters) + " ORDER BY rowid LIMIT ?"
        with self.read_tx() as db:
            rows = db.execute(query, params).fetchall()
        messages = [{**dict(row), "body": json.loads(row["body"])} for row in rows]
        return {"messages": messages, "next_cursor": messages[-1]["sequence"] if messages else after_seq}

    def message_ack(self, actor: Principal, message_id: str) -> dict[str, Any]:
        actor.require("message:read")
        with self.tx() as db:
            msg = db.execute("SELECT destination,read_at FROM messages WHERE id=?",
                             (message_id,)).fetchone()
            if not msg or (actor.agent_id != "operator" and msg["destination"] != actor.agent_id):
                raise GatewayError("message not found", "NOT_FOUND")
            if not msg["read_at"]:
                stamp = now()
                db.execute("UPDATE messages SET read_at=? WHERE id=?", (stamp, message_id))
                self.audit(db, actor.agent_id, "message.ack", message_id, {})
            else:
                stamp = msg["read_at"]
        return {"message_id": message_id, "acknowledged_at": stamp}

    def task_create(self, actor: Principal, assignee: str, payload: Any,
                    idempotency_key: str) -> dict[str, Any]:
        actor.require("task:create")
        self.required(idempotency_key, "idempotency_key")
        data = self.limit(payload)
        with self.tx() as db:
            previous = db.execute("SELECT * FROM tasks WHERE creator=? AND idem=?",
                                  (actor.agent_id, idempotency_key)).fetchone()
            if previous:
                if previous["assignee"] != assignee or previous["input"] != data:
                    raise GatewayError("idempotency key reused with different task", "CONFLICT")
                return {"task_id": previous["id"], "state": previous["state"], "deduplicated": True}
            self.agent_exists(db, assignee)
            task_id = uid("tsk")
            stamp = now()
            db.execute("""INSERT INTO tasks
              (id,creator,assignee,state,input,idem,created,updated)
              VALUES (?,?,?,'queued',?,?,?,?)""",
              (task_id, actor.agent_id, assignee, data, idempotency_key, stamp, stamp))
            self.audit(db, actor.agent_id, "task.create", task_id, {"assignee": assignee})
        return {"task_id": task_id, "state": "queued", "deduplicated": False}


    def task_inbox(self, actor: Principal, state: str = "queued",
                   limit: int = 50) -> list[dict[str, Any]]:
        actor.require("task:read")
        if state not in ("queued", "running", "blocked", "reported", "succeeded", "failed"):
            raise GatewayError("unsupported task state")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise GatewayError("limit must be 1..100")
        with self.tx() as db:
            if actor.agent_id == "operator":
                rows = db.execute("SELECT * FROM tasks WHERE state=? ORDER BY created LIMIT ?",
                                  (state, limit)).fetchall()
            else:
                rows = db.execute("""SELECT * FROM tasks WHERE state=? AND assignee=?
                                     ORDER BY created LIMIT ?""",
                                  (state, actor.agent_id, limit)).fetchall()
        return [{**dict(r), "input": json.loads(r["input"]),
                 "result": json.loads(r["result"]) if r["result"] is not None else None}
                for r in rows]

    def task_get(self, actor: Principal, task_id: str) -> dict[str, Any]:
        actor.require("task:read")
        with self.tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row or (actor.agent_id != "operator" and actor.agent_id not in (row["creator"], row["assignee"])):
            raise GatewayError("task not found", "NOT_FOUND")
        item = dict(row)
        item["input"] = json.loads(row["input"])
        item["result"] = json.loads(row["result"]) if row["result"] is not None else None
        return item

    def task_claim(self, actor: Principal, task_id: str, lease_seconds: int = 60) -> dict[str, Any]:
        actor.require("task:claim")
        if type(lease_seconds) is not int or not 15 <= lease_seconds <= 3600:
            raise GatewayError("lease_seconds must be 15..3600")
        with self.tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["assignee"] != actor.agent_id:
                raise GatewayError("task not assigned to caller", "FORBIDDEN")
            if row["state"] != "queued":
                raise GatewayError("task not claimable", "CONFLICT")
            started = now()
            expiry = after(lease_seconds)
            db.execute("""UPDATE tasks SET state='running', lease_until=?, lease_started=?,
                          attempts=attempts+1, updated=? WHERE id=?""",
                       (expiry, started, started, task_id))
            self.audit(db, actor.agent_id, "task.claim", task_id, {"lease_until": expiry})
        return {"task_id": task_id, "state": "running", "lease_until": expiry}

    def task_renew(self, actor: Principal, task_id: str, lease_seconds: int = 60) -> dict[str, Any]:
        actor.require("task:update")
        if type(lease_seconds) is not int or not 15 <= lease_seconds <= 3600:
            raise GatewayError("lease_seconds must be 15..3600")
        with self.tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["assignee"] != actor.agent_id or row["state"] != "running" or row["lease_until"] <= now():
                raise GatewayError("lease invalid or expired", "CONFLICT")
            # Hard cap: one claim's lifetime is at most two hours, including renewals.
            started = datetime.fromisoformat(row["lease_started"] or row["updated"])
            deadline = started + timedelta(hours=2)
            requested = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
            if requested > deadline:
                raise GatewayError("maximum task lease lifetime exceeded", "CONFLICT")
            expiry = requested.isoformat(timespec="microseconds")
            db.execute("UPDATE tasks SET lease_until=?, updated=? WHERE id=?", (expiry, now(), task_id))
            self.audit(db, actor.agent_id, "task.renew", task_id, {"lease_until": expiry})
        return {"task_id": task_id, "lease_until": expiry}

    def task_complete(self, actor: Principal, task_id: str, success: bool, result: Any) -> dict[str, Any]:
        actor.require("task:update")
        if not isinstance(success, bool):
            raise GatewayError("success must be boolean")
        data = self.limit(result)
        with self.tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["assignee"] != actor.agent_id or row["state"] != "running" or row["lease_until"] <= now():
                raise GatewayError("task not owned or active lease expired", "CONFLICT")
            state = "reported" if success else "failed"
            db.execute("UPDATE tasks SET state=?, result=?, lease_until=NULL, updated=? WHERE id=?",
                       (state, data, now(), task_id))
            self.audit(db, actor.agent_id, "task.complete", task_id,
                       {"state": state, "result_sha256": hashlib.sha256(data.encode()).hexdigest()})
        return {"task_id": task_id, "state": state}

    def task_verify(self, actor: Principal, task_id: str, approved: bool,
                    evidence: Any) -> dict[str, Any]:
        """Separate verifier must attest a reported result before success."""
        actor.require("task:verify")
        if type(approved) is not bool:
            raise GatewayError("approved must be boolean")
        # A non-empty container alone is not evidence: {"x": null} must fail.
        # Treat evidence as an attestation, not a guarantee of external truth.
        if isinstance(evidence, str):
            meaningful = len(evidence.strip()) >= 8
        elif isinstance(evidence, (dict, list)):
            meaningful = False
            pending: list[Any] = [evidence]
            while pending:
                element = pending.pop()
                if isinstance(element, dict):
                    pending.extend(value for key, value in element.items()
                                   if isinstance(key, str) and key.strip())
                elif isinstance(element, list):
                    pending.extend(element)
                elif isinstance(element, str):
                    meaningful = meaningful or bool(element.strip())
                elif element is not None and type(element) in (bool, int, float):
                    meaningful = True
                if meaningful:
                    break
        else:
            meaningful = False
        if not meaningful:
            raise GatewayError("meaningful verification evidence required")
        serialized = self.limit(evidence)
        with self.tx() as db:
            row = db.execute("SELECT state, assignee, creator FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["state"] != "reported":
                raise GatewayError("task is not awaiting verification", "CONFLICT")
            if actor.agent_id in (row["assignee"], row["creator"]):
                raise GatewayError("creator or worker cannot verify their own task", "FORBIDDEN")
            state = "succeeded" if approved else "failed"
            db.execute("INSERT INTO verifications(task_id,verifier,approved,evidence,created) VALUES (?,?,?,?,?)",
                       (task_id, actor.agent_id, int(approved), serialized, now()))
            db.execute("UPDATE tasks SET state=?, updated=? WHERE id=?",
                       (state, now(), task_id))
            self.audit(db, actor.agent_id, "task.verify", task_id,
                       {"approved": approved, "state": state, "evidence_sha256":
                        hashlib.sha256(serialized.encode("utf-8")).hexdigest()})
        return {"task_id": task_id, "state": state, "verified_by": actor.agent_id}

    def verification_get(self, actor: Principal, task_id: str) -> dict[str, Any]:
        actor.require("task:read")
        with self.read_tx() as db:
            task = db.execute("SELECT creator,assignee FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or (actor.agent_id != "operator" and actor.agent_id not in (task["creator"], task["assignee"])):
                raise GatewayError("verification not found", "NOT_FOUND")
            result = db.execute("SELECT * FROM verifications WHERE task_id=?", (task_id,)).fetchone()
        if result is None:
            return {"task_id": task_id, "verification": None}
        item = dict(result)
        item["approved"] = bool(item["approved"])
        item["evidence"] = json.loads(item["evidence"])
        return {"task_id": task_id, "verification": item}

    def checkpoint(self, actor: Principal, task_id: str, body: Any) -> dict[str, Any]:
        actor.require("checkpoint:write")
        data = self.limit(body)
        with self.tx() as db:
            row = db.execute("SELECT assignee,state,lease_until FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["assignee"] != actor.agent_id or row["state"] != "running" or row["lease_until"] <= now():
                raise GatewayError("active task lease required", "FORBIDDEN")
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 v FROM checkpoints WHERE task_id=?",
                                 (task_id,)).fetchone()["v"]
            db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?)",
                       (task_id, version, actor.agent_id, data, now()))
            self.audit(db, actor.agent_id, "checkpoint.write", task_id, {"version": version})
        return {"task_id": task_id, "version": version}

    def checkpoint_get(self, actor: Principal, task_id: str) -> dict[str, Any]:
        actor.require("task:read")
        with self.tx() as db:
            task = db.execute("SELECT creator,assignee FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or (actor.agent_id != "operator" and actor.agent_id not in (task["creator"], task["assignee"])):
                raise GatewayError("checkpoint not found", "NOT_FOUND")
            cp = db.execute("SELECT * FROM checkpoints WHERE task_id=? ORDER BY version DESC LIMIT 1",
                            (task_id,)).fetchone()
        if cp is None:
            return {"task_id": task_id, "checkpoint": None}
        item = dict(cp)
        item["body"] = json.loads(item["body"])
        return {"task_id": task_id, "checkpoint": item}

    def expired(self, actor: Principal) -> list[str]:
        actor.require("*")
        with self.tx() as db:
            rows = db.execute("SELECT id FROM tasks WHERE state='running' AND lease_until<=?",
                              (now(),)).fetchall()
            for row in rows:
                db.execute("UPDATE tasks SET state='blocked',updated=? WHERE id=?", (now(), row["id"]))
                self.audit(db, actor.agent_id, "task.lease_expired", row["id"], {"reason": "external effects require reconciliation"})
        return [r["id"] for r in rows]

    def reconcile(self, actor: Principal, task_id: str, external_effects_checked: bool,
                  explanation: str) -> dict[str, Any]:
        actor.require("*")
        if external_effects_checked is not True or len(self.required(explanation, "explanation")) < 8:
            raise GatewayError("explicit reconciliation evidence required")
        with self.tx() as db:
            row = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["state"] != "blocked":
                raise GatewayError("task must be blocked", "CONFLICT")
            db.execute("UPDATE tasks SET state='queued',lease_until=NULL,updated=? WHERE id=?",
                       (now(), task_id))
            self.audit(db, actor.agent_id, "task.reconcile", task_id, {"explanation": explanation})
        return {"task_id": task_id, "state": "queued"}


    @staticmethod
    def check_event_topic(actor: Principal, topic: str) -> None:
        # Public shared topics are explicitly untrusted cross-agent broadcasts.
        # Agent-prefixed topics are private to the authenticated principal.
        # System topics are reserved for the operator.
        if not isinstance(topic, str) or not 1 <= len(topic) <= 200 or not re.fullmatch(r"[a-z][a-z0-9_.-]*", topic):
            raise GatewayError("invalid event topic")
        if "*" in actor.scopes:
            return
        if topic.startswith("shared.") and len(topic) > len("shared."):
            return
        own_prefix = "agent." + actor.agent_id + "."
        if topic.startswith(own_prefix) and len(topic) > len(own_prefix):
            return
        raise GatewayError("event topic access denied", "FORBIDDEN")

    def event_publish(self, actor: Principal, topic: str, body: Any,
                      idempotency_key: str, correlation_id: str | None = None) -> dict[str, Any]:
        actor.require("event:write")
        self.check_event_topic(actor, topic)
        self.required(idempotency_key, "idempotency_key")
        if correlation_id is not None:
            self.required(correlation_id, "correlation_id")
        data = self.limit(body)
        with self.tx() as db:
            existing = db.execute("SELECT seq,topic,body,correlation_id FROM events WHERE source=? AND idem=?",
                                  (actor.agent_id, idempotency_key)).fetchone()
            if existing:
                if existing["topic"] != topic or existing["body"] != data or existing["correlation_id"] != correlation_id:
                    raise GatewayError("idempotency key reused with different event", "CONFLICT")
                return {"event_seq": existing["seq"], "deduplicated": True}
            row = db.execute("""INSERT INTO events
              (source,topic,body,correlation_id,idem,created)
              VALUES (?,?,?,?,?,?)""",
              (actor.agent_id, topic, data, correlation_id, idempotency_key, now()))
            seq = row.lastrowid
            self.audit(db, actor.agent_id, "event.publish", str(seq),
                       {"topic": topic, "correlation_id": correlation_id,
                        "payload_sha256": hashlib.sha256(data.encode()).hexdigest()})
        return {"event_seq": seq, "deduplicated": False}

    def event_poll(self, actor: Principal, after_seq: int = 0, limit: int = 50,
                   topic: str | None = None) -> dict[str, Any]:
        actor.require("event:read")
        if type(after_seq) is not int or not 0 <= after_seq <= 2**62:
            raise GatewayError("after_seq must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise GatewayError("limit must be 1..100")
        if topic is not None:
            self.check_event_topic(actor, topic)
        with self.read_tx() as db:
            if "*" in actor.scopes:
                if topic is None:
                    rows = db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?",
                                      (after_seq, limit)).fetchall()
                else:
                    rows = db.execute("SELECT * FROM events WHERE seq>? AND topic=? ORDER BY seq LIMIT ?",
                                      (after_seq, topic, limit)).fetchall()
            else:
                private_prefix = "agent." + actor.agent_id + "."
                # Substring prefix avoids SQLite LIKE '_' wildcard ambiguity.
                if topic is None:
                    rows = db.execute("""SELECT * FROM events WHERE seq>?
                      AND (substr(topic,1,7)='shared.' OR substr(topic,1,?)=?)
                      ORDER BY seq LIMIT ?""",
                      (after_seq, len(private_prefix), private_prefix, limit)).fetchall()
                else:
                    rows = db.execute("SELECT * FROM events WHERE seq>? AND topic=? ORDER BY seq LIMIT ?",
                                      (after_seq, topic, limit)).fetchall()
        result = [{**dict(r), "body": json.loads(r["body"])} for r in rows]
        return {"events": result, "next_cursor": result[-1]["seq"] if result else after_seq}


    def sanity_check(self, actor: Principal) -> dict[str, Any]:
        actor.require("*")
        with self.tx() as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            broken_refs = db.execute("PRAGMA foreign_key_check").fetchall()
        audit_result = self.audit_verify(actor)
        return {"healthy": integrity == "ok" and len(broken_refs) == 0 and audit_result["valid"],
                "sqlite_integrity": integrity,
                "foreign_key_violations": len(broken_refs),
                "audit": audit_result}

    def audit_list(self, actor: Principal, limit: int = 50) -> list[dict[str, Any]]:
        actor.require("audit:read")
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise GatewayError("limit must be 1..200")
        with self.read_tx() as db:
            if "*" in actor.scopes:
                rows = db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM audit WHERE actor=? ORDER BY seq DESC LIMIT ?",
                                  (actor.agent_id, limit)).fetchall()
        return [{**dict(r), "details": json.loads(r["details"])} for r in rows]

    def audit_verify(self, actor: Principal) -> dict[str, Any]:
        # Full ledger scans are privileged and do not monopolise the SQLite writer.
        actor.require("*")
        previous = "0" * 64
        count = 0
        with self.read_tx() as db:
            for r in db.execute("SELECT * FROM audit ORDER BY seq"):
                record = {"at": r["at"], "actor": r["actor"], "action": r["action"],
                          "subject": r["subject"], "details": json.loads(r["details"])}
                digest = hashlib.sha256((previous + canonical(record)).encode()).hexdigest()
                if r["previous_hash"] != previous or r["entry_hash"] != digest:
                    return {"valid": False, "first_invalid_seq": r["seq"]}
                previous = digest
                count += 1
        return {"valid": True, "count": count, "head": previous}

    def schedule_create(self, actor: Principal, assignee: str, payload: Any,
                        interval_seconds: int) -> dict[str, Any]:
        actor.require("*")
        if not isinstance(interval_seconds, int) or not 60 <= interval_seconds <= 2592000:
            raise GatewayError("interval_seconds must be 60..2592000")
        data = self.limit(payload)
        with self.tx() as db:
            self.agent_exists(db, assignee)
            sid = uid("sch")
            db.execute("INSERT INTO schedules VALUES (?,?,?,?,?,1,?)",
                       (sid, assignee, data, interval_seconds, after(interval_seconds), now()))
            self.audit(db, actor.agent_id, "schedule.create", sid, {"assignee": assignee, "interval_seconds": interval_seconds})
        return {"schedule_id": sid}

    def schedule_list(self, actor: Principal) -> list[dict[str, Any]]:
        actor.require("*")
        with self.read_tx() as db:
            rows = db.execute("SELECT * FROM schedules ORDER BY created").fetchall()
        return [{**dict(row), "enabled": bool(row["enabled"]), "input": json.loads(row["input"])}
                for row in rows]

    def schedule_disable(self, actor: Principal, schedule_id: str) -> dict[str, Any]:
        actor.require("*")
        with self.tx() as db:
            changed = db.execute("UPDATE schedules SET enabled=0 WHERE id=? AND enabled=1", (schedule_id,))
            if changed.rowcount != 1:
                raise GatewayError("schedule not active", "NOT_FOUND")
            self.audit(db, actor.agent_id, "schedule.disable", schedule_id, {})
        return {"schedule_id": schedule_id, "enabled": False}

    def schedule_tick(self, actor: Principal) -> dict[str, Any]:
        actor.require("*")
        created: list[str] = []
        with self.tx() as db:
            due = db.execute("""SELECT * FROM schedules WHERE enabled=1 AND next_due<=?
                AND EXISTS (SELECT 1 FROM agents WHERE agents.id=schedules.assignee
                            AND agents.revoked=0) LIMIT 100""", (now(),)).fetchall()
            for sch in due:
                tid = uid("tsk")
                timestamp = now()
                db.execute("""INSERT INTO tasks (id,creator,assignee,state,input,created,updated)
                              VALUES (?,'scheduler',?,'queued',?,?,?)""",
                           (tid, sch["assignee"], sch["input"], timestamp, timestamp))
                # Skip missed intervals in O(1); do not iterate millions of overdue ticks.
                previous_due = datetime.fromisoformat(sch["next_due"])
                elapsed = max(0.0, (datetime.now(timezone.utc) - previous_due).total_seconds())
                intervals = int(elapsed // sch["interval_seconds"]) + 1
                next_due = (previous_due + timedelta(
                    seconds=intervals * sch["interval_seconds"])).isoformat(timespec="microseconds")
                db.execute("UPDATE schedules SET next_due=? WHERE id=?", (next_due, sch["id"]))
                self.audit(db, actor.agent_id, "schedule.dispatch", tid, {"schedule_id": sch["id"]})
                created.append(tid)
        return {"dispatched": created}
