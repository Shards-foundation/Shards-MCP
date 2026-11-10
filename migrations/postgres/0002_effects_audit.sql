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
CREATE INDEX effect_outbox_claim ON shards_v2.effect_outbox(org_id, state, created_at)
    WHERE state IN ('pending','dispatching','needs_reconciliation');

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
CREATE FUNCTION shards_v2.reject_outbox_delete() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    RAISE EXCEPTION 'outbox intent cannot be deleted' USING ERRCODE = '42501';
END
$body$;
CREATE TRIGGER outbox_no_delete BEFORE DELETE ON shards_v2.effect_outbox
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_outbox_delete();

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

CREATE TABLE shards_v2.token_revocations (
    org_id uuid NOT NULL,
    issuer text NOT NULL,
    jti_sha256 bytea NOT NULL CHECK (octet_length(jti_sha256) = 32),
    revoked_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, issuer, jti_sha256),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id)
);

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
    canonical_record bytea NOT NULL,
    previous_sha256 bytea NOT NULL CHECK (octet_length(previous_sha256) = 32),
    entry_sha256 bytea NOT NULL CHECK (octet_length(entry_sha256) = 32),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, seq),
    FOREIGN KEY (org_id) REFERENCES shards_v2.organizations(org_id),
    FOREIGN KEY (org_id, actor_id) REFERENCES shards_v2.principals(org_id, principal_id)
);
CREATE FUNCTION shards_v2.reject_audit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    RAISE EXCEPTION 'audit entries are append-only' USING ERRCODE = '42501';
END
$body$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON shards_v2.audit_entries
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_audit_mutation();

CREATE TABLE shards_v2.governance_receipts (
    org_id uuid NOT NULL,
    receipt_id uuid NOT NULL DEFAULT gen_random_uuid(),
    task_id text NOT NULL,
    verifier_id text NOT NULL,
    audit_seq bigint NOT NULL,
    evidence_sha256 bytea NOT NULL CHECK (octet_length(evidence_sha256) = 32),
    signer_key_ref text NOT NULL,
    signature bytea NOT NULL CHECK (octet_length(signature) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, receipt_id),
    FOREIGN KEY (org_id, task_id) REFERENCES shards_v2.tasks(org_id, task_id),
    FOREIGN KEY (org_id, verifier_id) REFERENCES shards_v2.principals(org_id, principal_id),
    FOREIGN KEY (org_id, audit_seq) REFERENCES shards_v2.audit_entries(org_id, seq)
);

-- Signed receipts are evidence, not mutable customer notes.
CREATE TRIGGER receipt_immutable BEFORE UPDATE OR DELETE ON shards_v2.governance_receipts
FOR EACH ROW EXECUTE FUNCTION shards_v2.reject_audit_mutation();

DO $
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
