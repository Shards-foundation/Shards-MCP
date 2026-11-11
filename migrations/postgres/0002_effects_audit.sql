-- Shards-MCP v2 — transactional outbox and organisation-bound audit.
-- Requires 0001_tenancy.sql. Migration creates schema only; no runtime wiring.
BEGIN;

CREATE TABLE shards_v2.effect_outbox (
    org_id uuid NOT NULL,
    effect_id uuid NOT NULL DEFAULT gen_random_uuid(),
    task_id text NOT NULL,
    actor_id text NOT NULL,
    connector text NOT NULL,
    idempotency_key text NOT NULL,
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256) = 32),
    -- External request payload/credential belongs in a separate encrypted store.
    payload_vault_ref text NOT NULL CHECK (length(payload_vault_ref) BETWEEN 3 AND 255),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','dispatching','confirmed',
                         'needs_reconciliation','reconciled','canceled')),
    dispatch_attempts integer NOT NULL DEFAULT 0 CHECK (dispatch_attempts >= 0),
    provider_receipt jsonb,
    reconciliation_evidence jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, effect_id),
    UNIQUE (org_id, connector, idempotency_key),
    FOREIGN KEY (org_id, task_id) REFERENCES shards_v2.tasks(org_id, task_id),
    FOREIGN KEY (org_id, actor_id) REFERENCES shards_v2.principals(org_id, principal_id),
    CHECK (state <> 'confirmed' OR provider_receipt IS NOT NULL),
    CHECK (state <> 'reconciled' OR reconciliation_evidence IS NOT NULL)
);
CREATE INDEX effect_outbox_task_open ON shards_v2.effect_outbox(org_id,task_id,state);
CREATE INDEX effect_outbox_claim ON shards_v2.effect_outbox(org_id, state, created_at)
    WHERE state IN ('pending','dispatching','needs_reconciliation');

-- Serialize effect insertion/first dispatch with task-state writes.
CREATE FUNCTION shards_v2.lock_dispatchable_task(p_org uuid,p_task text)
RETURNS void LANGUAGE plpgsql AS $body$
DECLARE current_state text;
BEGIN
 SELECT t.state INTO current_state FROM shards_v2.tasks t
  WHERE t.org_id=p_org AND t.task_id=p_task FOR UPDATE;
 IF current_state IS DISTINCT FROM 'running' THEN
  RAISE EXCEPTION 'effect initiation requires running parent task' USING ERRCODE='23514';
 END IF;
END
$body$;

-- No direct reset of uncertain effects; terminal records are immutable.
-- The provider outcome must be reconciled independently before creating a
-- new separately authorised intent. This does NOT prove exactly-once effects.
CREATE FUNCTION shards_v2.enforce_outbox_transition() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    IF NEW.org_id IS DISTINCT FROM OLD.org_id OR
       NEW.effect_id IS DISTINCT FROM OLD.effect_id OR
       NEW.task_id IS DISTINCT FROM OLD.task_id OR
       NEW.actor_id IS DISTINCT FROM OLD.actor_id OR
       NEW.connector IS DISTINCT FROM OLD.connector OR
       NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR
       NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256 OR
       NEW.payload_vault_ref IS DISTINCT FROM OLD.payload_vault_ref THEN
        RAISE EXCEPTION 'outbox intent is immutable' USING ERRCODE = '42501';
    END IF;
    IF NEW.state='dispatching' AND OLD.state='pending' THEN
        PERFORM shards_v2.lock_dispatchable_task(NEW.org_id,NEW.task_id);
    END IF;
    IF OLD.state IN ('confirmed','reconciled','canceled') THEN
        RAISE EXCEPTION 'terminal outbox record cannot be updated'
            USING ERRCODE = '42501';
    END IF;
    IF OLD.state = 'needs_reconciliation' AND NEW.state <> 'reconciled' THEN
        RAISE EXCEPTION 'uncertain external effect requires independent reconciliation'
            USING ERRCODE = '42501';
    END IF;
    IF OLD.state = 'pending' AND NEW.state NOT IN ('pending','dispatching','canceled') THEN
        RAISE EXCEPTION 'invalid pending outbox transition' USING ERRCODE = '23514';
    END IF;
    IF OLD.state = 'dispatching' AND NEW.state NOT IN
       ('dispatching','confirmed','needs_reconciliation') THEN
        RAISE EXCEPTION 'invalid dispatching outbox transition' USING ERRCODE = '23514';
    END IF;
    IF OLD.state = 'needs_reconciliation' AND NEW.state = 'reconciled' AND
       NEW.reconciliation_evidence IS NULL THEN
        RAISE EXCEPTION 'reconciliation evidence is mandatory' USING ERRCODE = '23514';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END
$body$;
CREATE TRIGGER outbox_guard BEFORE UPDATE ON shards_v2.effect_outbox
FOR EACH ROW EXECUTE FUNCTION shards_v2.enforce_outbox_transition();
CREATE FUNCTION shards_v2.enforce_outbox_insert() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    PERFORM shards_v2.lock_dispatchable_task(NEW.org_id,NEW.task_id);
    IF NEW.state <> 'pending' OR NEW.provider_receipt IS NOT NULL OR
       NEW.reconciliation_evidence IS NOT NULL OR NEW.dispatch_attempts <> 0 THEN
        RAISE EXCEPTION 'new outbox intent must begin pending and unexecuted'
           USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER outbox_insert_guard BEFORE INSERT ON shards_v2.effect_outbox
FOR EACH ROW EXECUTE FUNCTION shards_v2.enforce_outbox_insert();
CREATE FUNCTION shards_v2.reject_outbox_delete() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    RAISE EXCEPTION 'outbox intent cannot be deleted' USING ERRCODE = '42501';
END
$body$;
CREATE TRIGGER outbox_no_delete BEFORE DELETE ON shards_v2.effect_outbox
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_outbox_delete();
-- TRUNCATE bypasses row-level triggers and RLS. Deny it explicitly.
CREATE TRIGGER outbox_no_truncate BEFORE TRUNCATE ON shards_v2.effect_outbox
FOR EACH STATEMENT EXECUTE FUNCTION shards_v2.reject_outbox_delete();

-- First write of an edge-signed one-use assertion is committed by the Python
-- origin *after* the user principal/org has been independently validated.
CREATE TABLE shards_v2.edge_request_nonces (
    org_id uuid NOT NULL,
    request_id uuid NOT NULL DEFAULT gen_random_uuid(),
    edge_key_id text NOT NULL,
    jti_sha256 bytea NOT NULL CHECK (octet_length(jti_sha256) = 32),
    request_sha256 bytea NOT NULL CHECK (octet_length(request_sha256) = 32),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, request_id),
    -- Replay across two orgs still conflicts even if an assertion is misbound.
    UNIQUE (edge_key_id, jti_sha256),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id),
    CHECK (expires_at > first_seen_at)
);

-- Retention: only authorised maintenance may remove security markers,
-- and never before token expiry plus ten minutes of clock-skew/retry margin.
CREATE FUNCTION shards_v2.restrict_security_marker_cleanup() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
 IF OLD.expires_at >= clock_timestamp()-interval '10 minutes' THEN
  RAISE EXCEPTION 'security marker still in active replay window' USING ERRCODE='42501';
 END IF;
 RETURN OLD;
END
$body$;
CREATE TRIGGER nonce_expiry_guard BEFORE DELETE ON shards_v2.edge_request_nonces
FOR EACH ROW EXECUTE FUNCTION shards_v2.restrict_security_marker_cleanup();

CREATE TABLE shards_v2.token_revocations (
    org_id uuid NOT NULL,
    issuer text NOT NULL,
    jti_sha256 bytea NOT NULL CHECK (octet_length(jti_sha256) = 32),
    revoked_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, issuer, jti_sha256),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id)
);

CREATE TRIGGER revocation_expiry_guard BEFORE DELETE ON shards_v2.token_revocations
FOR EACH ROW EXECUTE FUNCTION shards_v2.restrict_security_marker_cleanup();

-- Serialize per-tenant hash-chain append by locking audit_heads inside the
-- SAME database transaction as task mutations/outbox issuance.
CREATE TABLE shards_v2.audit_heads (
    org_id uuid PRIMARY KEY,
    last_seq bigint NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
    head_sha256 bytea NOT NULL DEFAULT decode(repeat('00',32),'hex')
        CHECK (octet_length(head_sha256) = 32),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id)
);

CREATE TABLE shards_v2.audit_entries (
    org_id uuid NOT NULL,
    seq bigint NOT NULL CHECK (seq >= 1),
    canonical_version smallint NOT NULL DEFAULT 2 CHECK (canonical_version = 2),
    actor_id text NOT NULL,
    action text NOT NULL,
    subject_id text NOT NULL,
    -- Authoritative canonical bytes MUST include org_id, seq, action and digests.
    details_json jsonb NOT NULL,
    canonical_record bytea NOT NULL,
    previous_sha256 bytea NOT NULL CHECK (octet_length(previous_sha256) = 32),
    entry_sha256 bytea NOT NULL CHECK (octet_length(entry_sha256) = 32),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, seq),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id),
    FOREIGN KEY (org_id, actor_id) REFERENCES shards_v2.principals(org_id, principal_id)
);
-- The application supplies the *expected* canonical record/hash. The database
-- independently reconstructs them, serialises on the tenant head row, validates
-- every link and atomically advances the head in the insert transaction.
-- No runtime UPDATE/DELETE privilege is granted on audit_heads.
CREATE FUNCTION shards_v2.guard_audit_append() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, shards_v2 AS $body$
DECLARE head record;
DECLARE expected_canonical bytea;
DECLARE expected_hash bytea;
BEGIN
  IF NULLIF(current_setting('shards.org_id',true),'')::uuid IS DISTINCT FROM NEW.org_id THEN
    RAISE EXCEPTION 'audit append requires transaction-bound tenant' USING ERRCODE='42501';
  END IF;
  INSERT INTO shards_v2.audit_heads(org_id) VALUES (NEW.org_id)
  ON CONFLICT (org_id) DO NOTHING;
  SELECT last_seq,head_sha256 INTO STRICT head
    FROM shards_v2.audit_heads WHERE org_id=NEW.org_id FOR UPDATE;
  expected_canonical := convert_to(jsonb_build_object(
    'version',NEW.canonical_version, 'org_id',NEW.org_id::text,
    'seq',NEW.seq, 'actor_id',NEW.actor_id,'action',NEW.action,
    'subject_id',NEW.subject_id,'details',NEW.details_json)::text,'UTF8');
  expected_hash := sha256(head.head_sha256 || expected_canonical);
  IF NEW.seq <> head.last_seq + 1 OR
     NEW.previous_sha256 <> head.head_sha256 OR
     NEW.canonical_record <> expected_canonical OR
     NEW.entry_sha256 <> expected_hash THEN
    RAISE EXCEPTION 'invalid audit sequence, canonical bytes or hash link'
      USING ERRCODE='23514';
  END IF;
  UPDATE shards_v2.audit_heads SET last_seq=NEW.seq,
       head_sha256=expected_hash,updated_at=now()
    WHERE org_id=NEW.org_id;
  RETURN NEW;
END
$body$;
CREATE TRIGGER audit_append_guard BEFORE INSERT ON shards_v2.audit_entries
FOR EACH ROW EXECUTE FUNCTION shards_v2.guard_audit_append();

-- The only audit writer used by business triggers. Runtime and verifier roles
-- may not EXECUTE this function or directly INSERT arbitrary audit entries.
-- Internal event generation and the state change share the same transaction.
CREATE FUNCTION shards_v2.emit_audit_event(
    p_org uuid, p_actor text, p_action text, p_subject text, p_details jsonb
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,shards_v2 AS $body$
DECLARE h record;
DECLARE next_seq bigint;
DECLARE canonical bytea;
BEGIN
 IF NULLIF(current_setting('shards.org_id',true),'')::uuid IS DISTINCT FROM p_org THEN
    RAISE EXCEPTION 'audit event tenant context missing or mismatched' USING ERRCODE='42501';
 END IF;
 INSERT INTO shards_v2.audit_heads(org_id) VALUES(p_org) ON CONFLICT(org_id) DO NOTHING;
 SELECT last_seq,head_sha256 INTO STRICT h
  FROM shards_v2.audit_heads WHERE org_id=p_org FOR UPDATE;
 next_seq:=h.last_seq+1;
 canonical:=convert_to(jsonb_build_object(
    'version',2,'org_id',p_org::text,'seq',next_seq,
    'actor_id',p_actor,'action',p_action,'subject_id',p_subject,
    'details',p_details)::text,'UTF8');
 INSERT INTO shards_v2.audit_entries
  (org_id,seq,actor_id,action,subject_id,details_json,canonical_record,previous_sha256,entry_sha256)
 VALUES(p_org,next_seq,p_actor,p_action,p_subject,p_details,canonical,h.head_sha256,
        sha256(h.head_sha256 || canonical));
 RETURN next_seq;
END
$body$;
REVOKE ALL ON FUNCTION shards_v2.emit_audit_event(uuid,text,text,text,jsonb) FROM PUBLIC;

-- The source row, not a tool argument, defines the kind of audit event.
-- Actor IDs below are row-party attribution, not a replacement for verifying
-- the authenticated caller in the eventual Python tenancy middleware.
CREATE FUNCTION shards_v2.audit_task_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,shards_v2 AS $body$
DECLARE event_action text;
DECLARE actor text;
DECLARE details jsonb;
BEGIN
 IF TG_OP='INSERT' THEN
    event_action:='task.created';
    actor:=NEW.creator_id;
    details:=jsonb_build_object('state',NEW.state,'worker',NEW.worker_id,
      'payload_sha256',encode(NEW.payload_sha256,'hex'));
 ELSE
    event_action:='task.updated';
    actor:=NEW.worker_id;
    details:=jsonb_build_object('from',OLD.state,'to',NEW.state,
      'result_sha256',CASE WHEN NEW.result_json IS NULL THEN NULL
        ELSE encode(sha256(convert_to(NEW.result_json::text,'UTF8')),'hex') END,
      'attempts',NEW.attempts);
 END IF;
 PERFORM shards_v2.emit_audit_event(NEW.org_id,actor,event_action,NEW.task_id,details);
 RETURN NULL;
END
$body$;
CREATE TRIGGER audit_task_insert AFTER INSERT ON shards_v2.tasks
FOR EACH ROW EXECUTE FUNCTION shards_v2.audit_task_change();
CREATE TRIGGER audit_task_update AFTER UPDATE ON shards_v2.tasks
FOR EACH ROW EXECUTE FUNCTION shards_v2.audit_task_change();

CREATE FUNCTION shards_v2.audit_effect_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,shards_v2 AS $body$
DECLARE event_action text;
DECLARE details jsonb;
BEGIN
 event_action:=CASE WHEN TG_OP='INSERT' THEN 'effect.created' ELSE 'effect.updated' END;
 details:=jsonb_build_object('effect_id',NEW.effect_id::text,'connector',NEW.connector,
   'task_id',NEW.task_id,
   'from',CASE WHEN TG_OP='INSERT' THEN NULL ELSE OLD.state END,
   'to',NEW.state,'payload_sha256',encode(NEW.payload_sha256,'hex'),
   'provider_receipt_sha256',CASE WHEN NEW.provider_receipt IS NULL THEN NULL
    ELSE encode(sha256(convert_to(NEW.provider_receipt::text,'UTF8')),'hex') END,
   'reconciliation_sha256',CASE WHEN NEW.reconciliation_evidence IS NULL THEN NULL
    ELSE encode(sha256(convert_to(NEW.reconciliation_evidence::text,'UTF8')),'hex') END);
 PERFORM shards_v2.emit_audit_event(NEW.org_id,NEW.actor_id,event_action,NEW.task_id,details);
 RETURN NULL;
END
$body$;
CREATE TRIGGER audit_effect_insert AFTER INSERT ON shards_v2.effect_outbox
FOR EACH ROW EXECUTE FUNCTION shards_v2.audit_effect_change();
CREATE TRIGGER audit_effect_update AFTER UPDATE ON shards_v2.effect_outbox
FOR EACH ROW EXECUTE FUNCTION shards_v2.audit_effect_change();

CREATE FUNCTION shards_v2.audit_verification_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,shards_v2 AS $body$
BEGIN
 PERFORM shards_v2.emit_audit_event(NEW.org_id,NEW.verifier_id,
   'verification.'||NEW.decision,NEW.task_id,
   jsonb_build_object('evidence_sha256',encode(NEW.evidence_sha256,'hex'),
    'result_sha256',encode(NEW.result_sha256,'hex'),
    'decision',NEW.decision));
 RETURN NULL;
END
$body$;
CREATE TRIGGER audit_verification_insert AFTER INSERT ON shards_v2.verifications
FOR EACH ROW EXECUTE FUNCTION shards_v2.audit_verification_change();


CREATE FUNCTION shards_v2.reject_audit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    RAISE EXCEPTION 'audit entries are append-only' USING ERRCODE = '42501';
END
$body$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON shards_v2.audit_entries
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_audit_mutation();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON shards_v2.audit_entries
FOR EACH STATEMENT EXECUTE FUNCTION shards_v2.reject_audit_mutation();

-- Composite references prohibit receipts from linking to a merely chain-valid,
-- unrelated audit entry, wrong task, wrong reviewer or different evidence.
ALTER TABLE shards_v2.audit_entries
 ADD CONSTRAINT audit_receipt_event_identity
 UNIQUE(org_id,seq,action,subject_id,actor_id);
ALTER TABLE shards_v2.verifications
 ADD CONSTRAINT verifier_receipt_identity
 UNIQUE(org_id,task_id,verifier_id,evidence_sha256);

CREATE TABLE shards_v2.governance_receipts (
    org_id uuid NOT NULL,
    receipt_id uuid NOT NULL DEFAULT gen_random_uuid(),
    task_id text NOT NULL,
    verifier_id text NOT NULL,
    audit_seq bigint NOT NULL,
    approval_action text NOT NULL DEFAULT 'verification.approved'
      CHECK (approval_action='verification.approved'),
    evidence_sha256 bytea NOT NULL CHECK (octet_length(evidence_sha256) = 32),
    signer_key_ref text NOT NULL,
    signature bytea NOT NULL CHECK (octet_length(signature) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, receipt_id),
    FOREIGN KEY (org_id, task_id) REFERENCES shards_v2.tasks(org_id, task_id),
    FOREIGN KEY (org_id, verifier_id) REFERENCES shards_v2.principals(org_id, principal_id),
    FOREIGN KEY (org_id,audit_seq,approval_action,task_id,verifier_id)
      REFERENCES shards_v2.audit_entries(org_id,seq,action,subject_id,actor_id),
    FOREIGN KEY (org_id,task_id,verifier_id,evidence_sha256)
      REFERENCES shards_v2.verifications(org_id,task_id,verifier_id,evidence_sha256)
);

-- Signed receipts are evidence, not mutable customer notes.
CREATE TRIGGER receipt_immutable BEFORE UPDATE OR DELETE ON shards_v2.governance_receipts
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_audit_mutation();
CREATE TRIGGER receipt_no_truncate BEFORE TRUNCATE ON shards_v2.governance_receipts
FOR EACH STATEMENT EXECUTE FUNCTION shards_v2.reject_audit_mutation();

-- Only trusted gateway processes may be granted the NOLOGIN runtime role.
-- No browser, agent, tool, or arbitrary SQL account gets membership in it.
-- Separate enrolment and retention privileges from the runtime role.
-- Cluster-global roles must be provisioned outside database migrations.
DO $roles$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='shards_v2_runtime')
    OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='shards_v2_maintenance')
    OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='shards_v2_verifier') THEN
    RAISE EXCEPTION 'missing v2 roles; provision with infra/postgres/bootstrap_roles.sql';
 END IF;
END
$roles$;
REVOKE ALL ON SCHEMA shards_v2 FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA shards_v2 FROM PUBLIC;
GRANT USAGE ON SCHEMA shards_v2 TO shards_v2_runtime, shards_v2_maintenance, shards_v2_verifier;
-- No INSERT/UPDATE of controllers, principals, memberships, grants or keys.
GRANT SELECT ON
 shards_v2.organizations,shards_v2.controllers,shards_v2.principals,
 shards_v2.memberships,shards_v2.agent_grants,
 shards_v2.tasks,shards_v2.messages,
 shards_v2.checkpoints,shards_v2.schedules,shards_v2.events,
 shards_v2.idempotency_requests,shards_v2.effect_outbox,
 shards_v2.edge_request_nonces,shards_v2.token_revocations,
 shards_v2.audit_entries
 TO shards_v2_runtime;
GRANT INSERT ON
 shards_v2.tasks,shards_v2.messages,shards_v2.verifications,
 shards_v2.checkpoints,shards_v2.events,
 shards_v2.idempotency_requests,shards_v2.effect_outbox,
 shards_v2.edge_request_nonces
 TO shards_v2_runtime;
-- Neither runtime nor verifier can forge audit entries; only the privileged
-- AFTER business triggers can call emit_audit_event.
GRANT UPDATE ON shards_v2.tasks,shards_v2.effect_outbox TO shards_v2_runtime;
GRANT UPDATE (acknowledged_at) ON shards_v2.messages TO shards_v2_runtime;
GRANT UPDATE (state,receipt_json) ON shards_v2.idempotency_requests TO shards_v2_runtime;
-- Runtime reads approved verdicts when checking task state, but only the
-- separate verifier role is allowed to create one.
GRANT SELECT ON shards_v2.verifications TO shards_v2_runtime;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON shards_v2.verifications FROM shards_v2_runtime;
-- Independent reviewer connections use their own non-inheriting role.
-- Reviewers cannot update tasks, audit heads, credentials or agent grants.
GRANT SELECT ON shards_v2.tasks,shards_v2.principals,shards_v2.memberships,
 shards_v2.verifications TO shards_v2_verifier;
GRANT INSERT ON shards_v2.verifications TO shards_v2_verifier;
REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA shards_v2 FROM shards_v2_verifier;
-- Intentionally NEVER grant UPDATE/INSERT/DELETE/TRUNCATE on audit_heads,
-- or DELETE/TRUNCATE on audit/outbox/verifications to runtime.
REVOKE ALL ON shards_v2.audit_heads FROM shards_v2_runtime;
REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA shards_v2 FROM shards_v2_runtime;
-- Expiry cleanup must run as a separately approved maintenance identity.
GRANT SELECT,DELETE ON shards_v2.edge_request_nonces,
 shards_v2.token_revocations TO shards_v2_maintenance;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
       'effect_outbox','edge_request_nonces','token_revocations','audit_heads',
       'audit_entries','governance_receipts'
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
