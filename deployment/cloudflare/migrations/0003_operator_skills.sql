-- Source-reconciled from deployed EU D1 schema, 15 Nov 2026.
-- Idempotent create-only migration: retains existing owner data and credentials.
CREATE TABLE IF NOT EXISTS operator_skills (
  id TEXT NOT NULL PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES operator_accounts(id),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 2 AND 90),
  description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=400),
  category TEXT NOT NULL DEFAULT 'other' CHECK(length(category) BETWEEN 1 AND 50),
  source_type TEXT NOT NULL CHECK(source_type IN ('upload','github')),
  source_url TEXT,
  content TEXT NOT NULL CHECK(length(content) BETWEEN 20 AND 65000),
  content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
  created_at TEXT NOT NULL,
  CHECK ((source_type='github' AND source_url IS NOT NULL AND length(trim(source_url))>0) OR (source_type='upload' AND source_url IS NULL)),
  UNIQUE(owner_id,source_url)
);
CREATE INDEX IF NOT EXISTS idx_operator_skills_owner ON operator_skills(owner_id,created_at DESC);
