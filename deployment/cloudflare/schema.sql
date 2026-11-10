PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
INSERT OR IGNORE INTO tenants(id,display_name,created_at)
VALUES('shards-internal','Shards Foundation / Internal','2026-11-10T00:00:00Z');
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  name TEXT NOT NULL,
  client TEXT NOT NULL,
  scopes TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  disabled_at TEXT,
  UNIQUE(tenant_id,name)
);
CREATE TABLE IF NOT EXISTS access_tokens (
  id TEXT PRIMARY KEY,
  token_sha256 TEXT UNIQUE NOT NULL,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_access_agent ON access_tokens(agent_id);
CREATE TABLE IF NOT EXISTS agent_messages (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  sender_id TEXT NOT NULL REFERENCES agents(id),
  recipient_id TEXT NOT NULL REFERENCES agents(id),
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  read_at TEXT,
  request_key TEXT,
  UNIQUE(tenant_id,sender_id,request_key)
);
CREATE INDEX IF NOT EXISTS idx_inbox ON agent_messages(tenant_id,recipient_id,created_at DESC);
CREATE TABLE IF NOT EXISTS agent_tasks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  creator_id TEXT NOT NULL REFERENCES agents(id),
  assignee_id TEXT NOT NULL REFERENCES agents(id),
  title TEXT NOT NULL,
  input_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','claimed','completed')),
  created_at TEXT NOT NULL,
  claimed_at TEXT,
  completed_at TEXT,
  result_json TEXT,
  request_key TEXT,
  UNIQUE(tenant_id,creator_id,request_key)
);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON agent_tasks(tenant_id,assignee_id,state,created_at);
CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  agent_id TEXT,
  action TEXT NOT NULL,
  object_id TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(tenant_id,created_at DESC);
CREATE TABLE IF NOT EXISTS route_budgets (
  window_key TEXT NOT NULL,
  operation TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0 CHECK(used>=0),
  PRIMARY KEY(window_key,operation)
);
