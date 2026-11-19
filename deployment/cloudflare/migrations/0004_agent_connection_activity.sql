-- Source-reconciled from deployed EU D1 schema, 15 Nov 2026.
-- Authenticated activity records are not evidence that a client is presently online.
CREATE TABLE IF NOT EXISTS agent_connection_activity (
  agent_id TEXT NOT NULL PRIMARY KEY REFERENCES agents(id),
  first_authenticated_at TEXT NOT NULL,
  last_authenticated_at TEXT NOT NULL,
  last_operation TEXT NOT NULL CHECK(length(last_operation) BETWEEN 1 AND 80)
);
CREATE INDEX IF NOT EXISTS idx_agent_connection_last_seen ON agent_connection_activity(last_authenticated_at DESC);
