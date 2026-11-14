-- Operator-owned SKILL.md registry. Imported text is inert and never executed by the Worker.
-- Apply after 0002_operator_settings.sql and before deploying the Skills UI.
CREATE TABLE IF NOT EXISTS operator_skills (
  id TEXT NOT NULL PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES operator_accounts(id),
  name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 90),
  description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=400),
  category TEXT NOT NULL DEFAULT 'other' CHECK(length(category) BETWEEN 1 AND 50),
  source_type TEXT NOT NULL CHECK(source_type IN ('upload','github')),
  source_url TEXT,
  content TEXT NOT NULL CHECK(length(content) BETWEEN 20 AND 65000),
  content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
  created_at TEXT NOT NULL,
  CHECK ((source_type='github' AND source_url IS NOT NULL) OR (source_type='upload' AND source_url IS NULL)),
  UNIQUE(owner_id,source_url)
);
CREATE INDEX IF NOT EXISTS idx_operator_skills_owner ON operator_skills(owner_id,created_at DESC);
