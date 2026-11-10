\set ON_ERROR_STOP on
-- Disposable Postgres 17 contract test, NEVER against any customer database.
-- The test runtime role is not the schema owner and has no BYPASSRLS privilege.
CREATE ROLE shards_ci_unprivileged NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA shards_v2 TO shards_ci_unprivileged;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA shards_v2 TO shards_ci_unprivileged;

-- Set up two organisations through the test-only superuser fixture.
INSERT INTO shards_v2.organizations(org_id,slug,lifecycle) VALUES
('00000000-0000-4000-8000-000000000001','tenant-alpha','active'),
('00000000-0000-4000-8000-000000000002','tenant-beta','active');
INSERT INTO shards_v2.principals(org_id,principal_id,kind,name) VALUES
('00000000-0000-4000-8000-000000000001','agt_a_creator','user','Creator A'),
('00000000-0000-4000-8000-000000000001','agt_a_worker','agent','Worker A'),
('00000000-0000-4000-8000-000000000001','agt_a_verifier','agent','Verifier A'),
('00000000-0000-4000-8000-000000000002','agt_b_worker','agent','Worker B');
INSERT INTO shards_v2.events(org_id,source_id,topic,body_json,idempotency_key) VALUES
('00000000-0000-4000-8000-000000000001','agt_a_creator','unit.audit','{}','fixture-a'),
('00000000-0000-4000-8000-000000000002','agt_b_worker','unit.audit','{}','fixture-b');

SET ROLE shards_ci_unprivileged;
-- A missing org context is default deny.
SELECT set_config('shards.org_id','',false);
DO $$
BEGIN
  IF (SELECT count(*) FROM shards_v2.events) <> 0 THEN
     RAISE EXCEPTION 'FAIL: no-org event read leaked tenant data';
  END IF;
  IF (SELECT count(*) FROM shards_v2.organizations) <> 0 THEN
     RAISE EXCEPTION 'FAIL: no-org organisation read leaked tenant data';
  END IF;
  BEGIN
    INSERT INTO shards_v2.events(org_id,source_id,topic,body_json,idempotency_key)
      VALUES ('00000000-0000-4000-8000-000000000001','agt_a_creator','x','{}','no-org');
    RAISE EXCEPTION 'FAIL: no-org insert succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;

-- Org A may read A, not B. Foreign key must prevent references to B.
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000001',false);
DO $$
BEGIN
  IF (SELECT count(*) FROM shards_v2.events) <> 1 THEN
    RAISE EXCEPTION 'FAIL: tenant A read isolation';
  END IF;
  IF (SELECT count(*) FROM shards_v2.principals) <> 3 THEN
    RAISE EXCEPTION 'FAIL: tenant A principal isolation';
  END IF;
  BEGIN
    INSERT INTO shards_v2.tasks(org_id,task_id,creator_id,worker_id,input_json)
      VALUES ('00000000-0000-4000-8000-000000000001','tsk_bad',
              'agt_a_creator','agt_b_worker','{}');
    RAISE EXCEPTION 'FAIL: cross-org task FK accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO shards_v2.events(org_id,source_id,topic,body_json,idempotency_key)
      VALUES ('00000000-0000-4000-8000-000000000002','agt_b_worker','x','{}','spoof');
    RAISE EXCEPTION 'FAIL: cross-org row inserted';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;

INSERT INTO shards_v2.tasks(org_id,task_id,creator_id,worker_id,input_json,idempotency_key)
 VALUES ('00000000-0000-4000-8000-000000000001','tsk_a',
         'agt_a_creator','agt_a_worker','{"intent":"no effect"}','op-a');

-- Independent evidence cannot be from worker or creator.
DO $$
BEGIN
  BEGIN
    INSERT INTO shards_v2.verifications
      (org_id,task_id,creator_id,worker_id,verifier_id,decision,evidence_sha256,evidence_json)
    VALUES
      ('00000000-0000-4000-8000-000000000001','tsk_a','agt_a_creator','agt_a_worker',
       'agt_a_worker','approved',decode(repeat('11',32),'hex'),'{}');
    RAISE EXCEPTION 'FAIL: worker self-verification accepted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;
INSERT INTO shards_v2.verifications
 (org_id,task_id,creator_id,worker_id,verifier_id,decision,evidence_sha256,evidence_json)
 VALUES
 ('00000000-0000-4000-8000-000000000001','tsk_a','agt_a_creator','agt_a_worker',
  'agt_a_verifier','approved',decode(repeat('11',32),'hex'),'{"ci":"independent"}');

-- A caller cannot insert a record already dispatched or with forged proof.
DO $$
BEGIN
  BEGIN
    INSERT INTO shards_v2.effect_outbox
     (org_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref,state)
    VALUES
     ('00000000-0000-4000-8000-000000000001','tsk_a','agt_a_worker',
      'github-pr','forged-idem',decode(repeat('aa',32),'hex'),'vault://ci/no-secret',
      'dispatching');
    RAISE EXCEPTION 'FAIL: dispatched outbox intent inserted directly';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- Outbox pending -> dispatching -> uncertain, NEVER automatic replay.
INSERT INTO shards_v2.effect_outbox
 (org_id,effect_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref)
 VALUES
 ('00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000001111',
  'tsk_a','agt_a_worker','github-pr','stable-provider-idem',decode(repeat('aa',32),'hex'),
  'vault://ci/no-secret');
DO $$
BEGIN
  BEGIN
    UPDATE shards_v2.effect_outbox SET state='confirmed'
     WHERE effect_id='00000000-0000-4000-8000-000000001111';
    RAISE EXCEPTION 'FAIL: pending went directly to confirmed';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;
UPDATE shards_v2.effect_outbox SET state='dispatching'
 WHERE org_id='00000000-0000-4000-8000-000000000001'
   AND effect_id='00000000-0000-4000-8000-000000001111';
UPDATE shards_v2.effect_outbox SET state='needs_reconciliation'
 WHERE org_id='00000000-0000-4000-8000-000000000001'
   AND effect_id='00000000-0000-4000-8000-000000001111';
DO $$
BEGIN
  BEGIN
    UPDATE shards_v2.effect_outbox SET state='pending'
     WHERE effect_id='00000000-0000-4000-8000-000000001111';
    RAISE EXCEPTION 'FAIL: ambiguous effect was requeued';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    UPDATE shards_v2.effect_outbox SET state='reconciled'
     WHERE effect_id='00000000-0000-4000-8000-000000001111';
    RAISE EXCEPTION 'FAIL: reconciliation without evidence succeeded';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    DELETE FROM shards_v2.effect_outbox
     WHERE effect_id='00000000-0000-4000-8000-000000001111';
    RAISE EXCEPTION 'FAIL: unresolved effect deletion succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
UPDATE shards_v2.effect_outbox
  SET state='reconciled',reconciliation_evidence='{"provider":"checked","outcome":"not_executed"}'
 WHERE org_id='00000000-0000-4000-8000-000000000001'
   AND effect_id='00000000-0000-4000-8000-000000001111';

-- Audit append-only and tenant scoped; a digest is fixture data, not actual
-- cryptographic verification of a production receipt.
INSERT INTO shards_v2.audit_entries
 (org_id,seq,actor_id,action,subject_id,canonical_record,previous_sha256,entry_sha256)
 VALUES ('00000000-0000-4000-8000-000000000001',1,'agt_a_creator',
         'ci.test','tsk_a',convert_to('{"org_id":"tenant-a","schema":2}','UTF8'),
         decode(repeat('00',32),'hex'),decode(repeat('bb',32),'hex'));
DO $$
BEGIN
  BEGIN
    DELETE FROM shards_v2.audit_entries WHERE seq=1;
    RAISE EXCEPTION 'FAIL: audit deletion succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    UPDATE shards_v2.audit_entries SET action='altered' WHERE seq=1;
    RAISE EXCEPTION 'FAIL: audit mutation succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;


-- Replayed edge assertion JTI is rejected independently of tenant context.
INSERT INTO shards_v2.edge_request_nonces
 (org_id,edge_key_id,jti_sha256,request_sha256,expires_at)
 VALUES ('00000000-0000-4000-8000-000000000001','edge-test-key',
         decode(repeat('33',32),'hex'),decode(repeat('44',32),'hex'),now()+interval '30 seconds');
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000002',false);
DO $$
BEGIN
  BEGIN
    INSERT INTO shards_v2.edge_request_nonces
      (org_id,edge_key_id,jti_sha256,request_sha256,expires_at)
    VALUES ('00000000-0000-4000-8000-000000000002','edge-test-key',
            decode(repeat('33',32),'hex'),decode(repeat('55',32),'hex'),now()+interval '30 seconds');
    RAISE EXCEPTION 'FAIL: edge nonce reused across tenants';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000001',false);

-- Cross-org and missing-context reads remain denied after writes.
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000002',false);
DO $$
BEGIN
  IF (SELECT count(*) FROM shards_v2.tasks) <> 0 THEN
     RAISE EXCEPTION 'FAIL: tenant B sees tenant A tasks';
  END IF;
  IF (SELECT count(*) FROM shards_v2.audit_entries) <> 0 THEN
     RAISE EXCEPTION 'FAIL: tenant B sees tenant A audit';
  END IF;
  IF (SELECT count(*) FROM shards_v2.effect_outbox) <> 0 THEN
     RAISE EXCEPTION 'FAIL: tenant B sees tenant A outbox';
  END IF;
  IF (SELECT count(*) FROM shards_v2.events) <> 1 THEN
     RAISE EXCEPTION 'FAIL: tenant B event count';
  END IF;
END $$;
RESET ROLE;
-- Elevated DDL owners also hit the append-only TRUNCATE triggers.
-- These are destructive statements against disposable CI fixtures only.
DO $$
BEGIN
  BEGIN
    TRUNCATE TABLE shards_v2.audit_entries;
    RAISE EXCEPTION 'FAIL: audit truncate succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    TRUNCATE TABLE shards_v2.effect_outbox;
    RAISE EXCEPTION 'FAIL: outbox truncate succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    TRUNCATE TABLE shards_v2.governance_receipts;
    RAISE EXCEPTION 'FAIL: signed receipt truncate succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;

-- Ensure all tenant tables carry an org_id column and forced RLS.
DO $$
DECLARE item record;
BEGIN
  FOR item IN SELECT c.relname AS name,c.relrowsecurity,c.relforcerowsecurity
    FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid
    WHERE n.nspname='shards_v2' AND c.relkind='r'
  LOOP
    IF NOT item.relrowsecurity OR NOT item.relforcerowsecurity OR NOT EXISTS(
      SELECT 1 FROM information_schema.columns
       WHERE table_schema='shards_v2' AND table_name=item.name AND column_name='org_id'
    ) THEN RAISE EXCEPTION 'FAIL: org/RLS missing on %',item.name;
    END IF;
  END LOOP;
END $$;
SELECT 'TENANCY_SCHEMA_ACCEPTANCE_PASS' AS result;
