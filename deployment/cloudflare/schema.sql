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

-- Operator account baseline. Existing installations apply migrations/0002_operator_settings.sql.
-- Shards MCP Edge operator settings, created only after PR review and predeploy D1 backup.
-- Independent of the Python gateway and tenant-wide agent authorisation.
CREATE TABLE IF NOT EXISTS operator_accounts (
  id TEXT PRIMARY KEY CHECK(length(id)=64),
  email TEXT,
  full_name TEXT NOT NULL DEFAULT '',
  avatar_data TEXT,
  theme TEXT NOT NULL DEFAULT 'system' CHECK(theme IN ('system','dark','light','contrast')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
  deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS operator_api_keys (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES operator_accounts(id),
  kind TEXT NOT NULL CHECK(kind IN ('api','cli')),
  label TEXT NOT NULL,
  token_sha256 TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL,
  scopes TEXT NOT NULL CHECK(scopes='["account:read"]'),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_used_at TEXT,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_operator_api_keys_owner ON operator_api_keys(owner_id,created_at DESC);
CREATE TABLE IF NOT EXISTS operator_ssh_keys (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES operator_accounts(id),
  label TEXT NOT NULL,
  algorithm TEXT NOT NULL CHECK(algorithm='ssh-ed25519'),
  public_key TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(owner_id,fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_operator_ssh_keys_owner ON operator_ssh_keys(owner_id,created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agents_created_by ON agents(created_by,created_at DESC);
