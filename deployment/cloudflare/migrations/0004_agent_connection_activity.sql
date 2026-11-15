-- Authenticated MCP request receipts. A receipt proves use of a scoped token,
-- not agent process uptime or the provenance of the caller's software.
CREATE TABLE IF NOT EXISTS agent_connection_activity (
  agent_id TEXT NOT NULL PRIMARY KEY REFERENCES agents(id),
  first_authenticated_at TEXT NOT NULL,
  last_authenticated_at TEXT NOT NULL,
  last_operation TEXT NOT NULL CHECK(length(last_operation) BETWEEN 1 AND 80)
);
CREATE INDEX IF NOT EXISTS idx_agent_connection_last_seen ON agent_connection_activity(last_authenticated_at DESC);
