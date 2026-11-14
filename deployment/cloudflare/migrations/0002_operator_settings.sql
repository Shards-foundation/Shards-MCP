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
