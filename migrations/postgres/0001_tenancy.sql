-- Shards-MCP authority v2: NEW PostgreSQL database only.
-- NOT compatible with the live SQLite v0.1 database or Cloudflare D1.
-- Apply as an operator-controlled migration exactly once, before runtime cutover.
BEGIN;
CREATE SCHEMA shards_v2;

CREATE TABLE shards_v2.organizations (
    org_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z][a-z0-9-]{2,62}$'),
    lifecycle text NOT NULL DEFAULT 'quarantined'
        CHECK (lifecycle IN ('quarantined','active','suspended','closed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- One tenant-bound principal per organisation membership. External issuer+sub
-- are unique WITHIN an org, never a browser-controlled actor ID.
CREATE TABLE shards_v2.principals (
    org_id uuid NOT NULL,
    principal_id text NOT NULL CHECK (length(principal_id) BETWEEN 3 AND 200),
    kind text NOT NULL CHECK (kind IN ('user','agent','service')),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    external_issuer text,
    external_subject text,
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','revoked','disabled')),
    scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, principal_id),
    UNIQUE (org_id, name),
    UNIQUE (org_id, external_issuer, external_subject),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id),
    CHECK ((external_issuer IS NULL) = (external_subject IS NULL))
);
CREATE INDEX principals_active_by_org ON shards_v2.principals(org_id, state, kind);

CREATE TABLE shards_v2.memberships (
    org_id uuid NOT NULL,
    principal_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('owner','admin','member','auditor','agent')),
    admitted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    PRIMARY KEY (org_id, principal_id),
    FOREIGN KEY (org_id, principal_id)
       REFERENCES shards_v2.principals(org_id, principal_id)
);
CREATE INDEX memberships_active ON shards_v2.memberships(org_id, role)
    WHERE revoked_at IS NULL;

-- A task ID is opaque to the caller and NEVER sufficient for access.
-- Shared-tenant FK constraints preserve creator/worker membership.
CREATE TABLE shards_v2.tasks (
    org_id uuid NOT NULL,
    task_id text NOT NULL CHECK (length(task_id) BETWEEN 3 AND 200),
    creator_id text NOT NULL,
    worker_id text NOT NULL,
    state text NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued','running','reported','succeeded','failed',
                         'canceled','needs_reconciliation')),
    input_json jsonb NOT NULL,
    result_json jsonb,
    idempotency_key text,
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, task_id),
    UNIQUE (org_id, task_id, creator_id, worker_id),
    UNIQUE (org_id, creator_id, idempotency_key),
    FOREIGN KEY (org_id, creator_id)
      REFERENCES shards_v2.principals(org_id, principal_id),
    FOREIGN KEY (org_id, worker_id)
      REFERENCES shards_v2.principals(org_id, principal_id),
    CHECK (creator_id <> worker_id)
);
CREATE INDEX task_queue_tenant ON shards_v2.tasks(org_id, worker_id, state, created_at, task_id);

CREATE TABLE shards_v2.messages (
    org_id uuid NOT NULL,
    message_id text NOT NULL,
    source_id text NOT NULL,
    destination_id text NOT NULL,
    task_id text,
    body_json jsonb NOT NULL,
    idempotency_key text,
    sent_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_at timestamptz,
    PRIMARY KEY (org_id, message_id),
    UNIQUE (org_id, source_id, idempotency_key),
    FOREIGN KEY (org_id, source_id) REFERENCES shards_v2.principals(org_id, principal_id),
    FOREIGN KEY (org_id, destination_id) REFERENCES shards_v2.principals(org_id, principal_id),
    FOREIGN KEY (org_id, task_id) REFERENCES shards_v2.tasks(org_id, task_id)
);
CREATE INDEX messages_inbox_tenant ON shards_v2.messages(org_id, destination_id, sent_at);

-- Include creator/worker identity in FK, so a verifier cannot spoof the
-- task parties using a locally valid but unrelated principal.
CREATE TABLE shards_v2.verifications (
    org_id uuid NOT NULL,
    task_id text NOT NULL,
    creator_id text NOT NULL,
    worker_id text NOT NULL,
    verifier_id text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approved','rejected')),
    evidence_sha256 bytea NOT NULL CHECK (octet_length(evidence_sha256) = 32),
    evidence_json jsonb NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, task_id),
    FOREIGN KEY (org_id, task_id, creator_id, worker_id)
      REFERENCES shards_v2.tasks(org_id, task_id, creator_id, worker_id),
    FOREIGN KEY (org_id, verifier_id) REFERENCES shards_v2.principals(org_id, principal_id),
    CHECK (verifier_id <> creator_id AND verifier_id <> worker_id)
);

CREATE TABLE shards_v2.checkpoints (
    org_id uuid NOT NULL,
    task_id text NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    actor_id text NOT NULL,
    body_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, task_id, version),
    FOREIGN KEY (org_id, task_id) REFERENCES shards_v2.tasks(org_id, task_id),
    FOREIGN KEY (org_id, actor_id) REFERENCES shards_v2.principals(org_id, principal_id)
);

CREATE TABLE shards_v2.schedules (
    org_id uuid NOT NULL,
    schedule_id text NOT NULL,
    creator_id text NOT NULL,
    worker_id text NOT NULL,
    input_json jsonb NOT NULL,
    interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 60 AND 2592000),
    next_due timestamptz NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, schedule_id),
    FOREIGN KEY (org_id, creator_id) REFERENCES shards_v2.principals(org_id, principal_id),
    FOREIGN KEY (org_id, worker_id) REFERENCES shards_v2.principals(org_id, principal_id)
);
CREATE INDEX schedule_due_by_org ON shards_v2.schedules(org_id, next_due) WHERE enabled;

CREATE TABLE shards_v2.events (
    org_id uuid NOT NULL,
    event_id uuid NOT NULL DEFAULT gen_random_uuid(),
    source_id text NOT NULL,
    topic text NOT NULL,
    body_json jsonb NOT NULL,
    correlation_id text,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, event_id),
    UNIQUE (org_id, source_id, idempotency_key),
    FOREIGN KEY (org_id, source_id) REFERENCES shards_v2.principals(org_id, principal_id)
);
CREATE INDEX events_tenant_topic ON shards_v2.events(org_id, topic, created_at);

-- Holds only a secret-store reference, NEVER a provider API key.
CREATE TABLE shards_v2.connector_credentials (
    org_id uuid NOT NULL,
    credential_id uuid NOT NULL DEFAULT gen_random_uuid(),
    principal_id text NOT NULL,
    connector text NOT NULL,
    vault_ref text NOT NULL CHECK (length(vault_ref) BETWEEN 3 AND 255),
    scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, credential_id),
    FOREIGN KEY (org_id, principal_id) REFERENCES shards_v2.principals(org_id, principal_id)
);

CREATE TABLE shards_v2.idempotency_requests (
    org_id uuid NOT NULL,
    actor_id text NOT NULL,
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256) = 32),
    state text NOT NULL CHECK (state IN ('pending','completed','needs_reconciliation')),
    receipt_json jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, actor_id, operation, idempotency_key),
    FOREIGN KEY (org_id, actor_id) REFERENCES shards_v2.principals(org_id, principal_id)
);

-- RLS denies missing/invalid tenant context. Only the trusted Python gateway
-- may set shards.org_id, after verified membership. Never grant raw SQL to users.
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'organizations','principals','memberships','tasks','messages',
        'verifications','checkpoints','schedules','events',
        'connector_credentials','idempotency_requests'
    ] LOOP
        EXECUTE format('ALTER TABLE shards_v2.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE shards_v2.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_guard ON shards_v2.%I USING '
          || '(org_id = NULLIF(current_setting(''shards.org_id'',true),'''')::uuid) '
          || 'WITH CHECK (org_id = NULLIF(current_setting(''shards.org_id'',true),'''')::uuid)',
            table_name);
    END LOOP;
END $$;
COMMIT;
