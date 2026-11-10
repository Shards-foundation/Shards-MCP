-- Shards-MCP authority v2: NEW PostgreSQL database only.
-- NOT compatible with the live SQLite v0.1 database or Cloudflare D1.
-- Apply as an operator-controlled migration exactly once, before runtime cutover.
BEGIN;
CREATE SCHEMA shards_v2;

CREATE TABLE shards_v2.organizations (
    org_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_audience text GENERATED ALWAYS AS (
        'https://mcp.shardsinc.co.uk/orgs/' || org_id::text || '/mcp'
    ) STORED UNIQUE,
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z][a-z0-9-]{2,62}$'),
    lifecycle text NOT NULL DEFAULT 'quarantined'
        CHECK (lifecycle IN ('quarantined','active','suspended','closed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Independently attested controller is the person/service behind principals.
-- Only privileged enrolment may create or amend controller records.
CREATE TABLE shards_v2.controllers (
 org_id uuid NOT NULL, controller_id text NOT NULL,
 kind text NOT NULL CHECK (kind IN ('person','organisation','service')),
 attested_ref text NOT NULL CHECK (length(attested_ref) BETWEEN 3 AND 255),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (org_id,controller_id),
 FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id)
);

-- One tenant-bound principal per organisation membership. External issuer+sub
-- are unique WITHIN an org, never a browser-controlled actor ID.
CREATE TABLE shards_v2.principals (
    org_id uuid NOT NULL,
    principal_id text NOT NULL CHECK (length(principal_id) BETWEEN 3 AND 200),
    kind text NOT NULL CHECK (kind IN ('user','agent','service')),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    controller_id text NOT NULL,
    external_issuer text,
    external_subject text,
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','revoked','disabled')),
    scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, principal_id),
    UNIQUE (org_id, name),
    UNIQUE (org_id, external_issuer, external_subject),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id),
    FOREIGN KEY (org_id, controller_id) REFERENCES shards_v2.controllers(org_id,controller_id),
    CHECK ((external_issuer IS NULL) = (external_subject IS NULL))
);
CREATE INDEX principals_active_by_org ON shards_v2.principals(org_id, state, kind);
CREATE FUNCTION shards_v2.lock_principal_controller() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
 IF NEW.org_id IS DISTINCT FROM OLD.org_id OR
    NEW.principal_id IS DISTINCT FROM OLD.principal_id OR
    NEW.controller_id IS DISTINCT FROM OLD.controller_id OR
    NEW.external_issuer IS DISTINCT FROM OLD.external_issuer OR
    NEW.external_subject IS DISTINCT FROM OLD.external_subject THEN
  RAISE EXCEPTION 'immutable identity binding' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END
$body$;
CREATE TRIGGER principal_binding_immutable BEFORE UPDATE ON shards_v2.principals
FOR EACH ROW EXECUTE FUNCTION shards_v2.lock_principal_controller();

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
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256)=32),
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
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256)=32),
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
    decision text NOT NULL CHECK (decision IN ('approved','rejected','self_attested')),
    evidence_sha256 bytea NOT NULL CHECK (octet_length(evidence_sha256) = 32),
    result_sha256 bytea NOT NULL CHECK (octet_length(result_sha256) = 32),
    evidence_json jsonb NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, task_id),
    FOREIGN KEY (org_id, task_id, creator_id, worker_id)
      REFERENCES shards_v2.tasks(org_id, task_id, creator_id, worker_id),
    FOREIGN KEY (org_id, verifier_id) REFERENCES shards_v2.principals(org_id, principal_id),
    CHECK (verifier_id <> creator_id AND verifier_id <> worker_id)
);

-- Evidence is append-only. Approved verdict requires an independent controller,
-- active auditor membership, and a reported task.
CREATE FUNCTION shards_v2.guard_verification() RETURNS trigger LANGUAGE plpgsql AS $body$
DECLARE worker_controller text;
DECLARE creator_controller text;
DECLARE verifier_controller text;
DECLARE task_state text;
DECLARE verified_result jsonb;
BEGIN
 SELECT t.state,t.result_json,w.controller_id,c.controller_id,v.controller_id
 INTO task_state,verified_result,worker_controller,creator_controller,verifier_controller
 FROM shards_v2.tasks t
 JOIN shards_v2.principals w ON w.org_id=t.org_id AND w.principal_id=t.worker_id
 JOIN shards_v2.principals c ON c.org_id=t.org_id AND c.principal_id=t.creator_id
 JOIN shards_v2.principals v ON v.org_id=t.org_id AND v.principal_id=NEW.verifier_id AND v.state='active'
 WHERE t.org_id=NEW.org_id AND t.task_id=NEW.task_id
   AND t.creator_id=NEW.creator_id AND t.worker_id=NEW.worker_id;
 IF NEW.result_sha256 IS DISTINCT FROM sha256(convert_to(verified_result::text,'UTF8')) THEN
   RAISE EXCEPTION 'verifier result hash does not match immutable worker report' USING ERRCODE='23514';
 END IF;
 IF task_state IS DISTINCT FROM 'reported' THEN
   RAISE EXCEPTION 'only reported tasks may be verified' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM shards_v2.memberships m
   WHERE m.org_id=NEW.org_id AND m.principal_id=NEW.verifier_id
     AND m.role='auditor' AND m.revoked_at IS NULL) THEN
   RAISE EXCEPTION 'active auditor membership required' USING ERRCODE='42501';
 END IF;
 IF NEW.decision='approved' AND
    (verifier_controller=worker_controller OR verifier_controller=creator_controller) THEN
   RAISE EXCEPTION 'verifier shares a controller with worker or creator' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END
$body$;
CREATE TRIGGER verify_independent BEFORE INSERT ON shards_v2.verifications
FOR EACH ROW EXECUTE FUNCTION shards_v2.guard_verification();
CREATE FUNCTION shards_v2.reject_verification_mutation() RETURNS trigger LANGUAGE plpgsql AS $body$
BEGIN
 RAISE EXCEPTION 'verification immutable' USING ERRCODE='42501';
END
$body$;
CREATE TRIGGER verification_immutable BEFORE UPDATE OR DELETE ON shards_v2.verifications
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_verification_mutation();
CREATE TRIGGER verification_no_truncate BEFORE TRUNCATE ON shards_v2.verifications
FOR EACH STATEMENT EXECUTE FUNCTION shards_v2.reject_verification_mutation();

CREATE FUNCTION shards_v2.guard_task_state() RETURNS trigger LANGUAGE plpgsql AS $body$
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.state<>'queued' OR NEW.result_json IS NOT NULL
      OR NEW.lease_until IS NOT NULL OR NEW.attempts<>0 THEN
     RAISE EXCEPTION 'new task must start queued and unexecuted' USING ERRCODE='23514';
   END IF;
 ELSE
   IF NEW.org_id IS DISTINCT FROM OLD.org_id OR NEW.task_id IS DISTINCT FROM OLD.task_id
      OR NEW.creator_id IS DISTINCT FROM OLD.creator_id
      OR NEW.worker_id IS DISTINCT FROM OLD.worker_id
      OR NEW.input_json IS DISTINCT FROM OLD.input_json
      OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
      OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
      OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
     RAISE EXCEPTION 'immutable task intent' USING ERRCODE='42501';
   END IF;
   IF OLD.state NOT IN ('queued','running') AND
      NEW.result_json IS DISTINCT FROM OLD.result_json THEN
     RAISE EXCEPTION 'reported result is immutable' USING ERRCODE='42501';
   END IF;
   IF OLD.state IN ('succeeded','failed','canceled') AND NEW IS DISTINCT FROM OLD THEN
     RAISE EXCEPTION 'terminal task is immutable' USING ERRCODE='42501';
   END IF;
   IF NEW.state <> OLD.state AND NOT (
       (OLD.state='queued' AND NEW.state IN ('running','canceled')) OR
       (OLD.state='running' AND NEW.state IN ('reported','failed','needs_reconciliation')) OR
       (OLD.state='reported' AND NEW.state IN ('succeeded','failed','needs_reconciliation')) OR
       (OLD.state='needs_reconciliation' AND NEW.state='failed')
   ) THEN
     RAISE EXCEPTION 'illegal task state transition' USING ERRCODE='23514';
   END IF;
   IF NEW.state='reported' AND NEW.result_json IS NULL THEN
     RAISE EXCEPTION 'worker report requires a result' USING ERRCODE='23514';
   END IF;
   IF NEW.state='succeeded' AND NOT EXISTS (
      SELECT 1 FROM shards_v2.verifications v
      WHERE v.org_id=NEW.org_id AND v.task_id=NEW.task_id AND v.decision='approved'
   ) THEN
     RAISE EXCEPTION 'independent approval required before success' USING ERRCODE='42501';
   END IF;
   NEW.updated_at=now();
 END IF;
 RETURN NEW;
END
$body$;
CREATE TRIGGER task_transition_guard BEFORE INSERT OR UPDATE ON shards_v2.tasks
FOR EACH ROW EXECUTE FUNCTION shards_v2.guard_task_state();

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
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256)=32),
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

-- Policy-enforced connector/resource/action grants. Mutable only by enrolment
-- authority; a broad tool scope is not a connector permission.
CREATE TABLE shards_v2.agent_grants (
 org_id uuid NOT NULL, principal_id text NOT NULL,
 connector text NOT NULL, resource text NOT NULL, action text NOT NULL,
 allowed boolean NOT NULL DEFAULT false, approval_required boolean NOT NULL DEFAULT true,
 expires_at timestamptz, granted_by text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (org_id,principal_id,connector,resource,action),
 FOREIGN KEY (org_id,principal_id) REFERENCES shards_v2.principals(org_id,principal_id),
 FOREIGN KEY (org_id,granted_by) REFERENCES shards_v2.principals(org_id,principal_id),
 CHECK(length(connector) BETWEEN 1 AND 120 AND length(resource) BETWEEN 1 AND 500
    AND length(action) BETWEEN 1 AND 120)
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
        'organizations','controllers','principals','memberships','tasks','messages',
        'verifications','checkpoints','schedules','events',
        'connector_credentials','agent_grants','idempotency_requests'
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
