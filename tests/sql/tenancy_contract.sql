\set ON_ERROR_STOP on
-- PostgreSQL 17, disposable database only; runtime is a non-owner NOLOGIN role.
-- The same psql connection is reused throughout to expose context leakage.

-- Enrolment fixtures: only the privileged schema owner can mutate these.
INSERT INTO shards_v2.organizations(org_id,slug,lifecycle) VALUES
('00000000-0000-4000-8000-000000000001','tenant-alpha','active'),
('00000000-0000-4000-8000-000000000002','tenant-beta','active');

INSERT INTO shards_v2.controllers(org_id,controller_id,kind,attested_ref) VALUES
('00000000-0000-4000-8000-000000000001','ctrl_owner','person','issuer:owner-a'),
('00000000-0000-4000-8000-000000000001','ctrl_worker','person','issuer:worker-a'),
('00000000-0000-4000-8000-000000000001','ctrl_independent','person','issuer:reviewer-a'),
('00000000-0000-4000-8000-000000000002','ctrl_b','person','issuer:worker-b');

INSERT INTO shards_v2.principals
 (org_id,principal_id,kind,name,controller_id,external_issuer,external_subject) VALUES
('00000000-0000-4000-8000-000000000001','agt_a_creator','user','Creator A','ctrl_owner','https://issuer.test','shared-person'),
('00000000-0000-4000-8000-000000000001','agt_a_worker','agent','Worker A','ctrl_worker',NULL,NULL),
('00000000-0000-4000-8000-000000000001','agt_a_same','agent','Same controller reviewer','ctrl_worker',NULL,NULL),
('00000000-0000-4000-8000-000000000001','agt_a_verifier','agent','Independent reviewer','ctrl_independent',NULL,NULL),
('00000000-0000-4000-8000-000000000002','agt_b_worker','agent','Worker B','ctrl_b','https://issuer.test','shared-person');

INSERT INTO shards_v2.memberships(org_id,principal_id,role) VALUES
('00000000-0000-4000-8000-000000000001','agt_a_creator','member'),
('00000000-0000-4000-8000-000000000001','agt_a_worker','agent'),
('00000000-0000-4000-8000-000000000001','agt_a_same','auditor'),
('00000000-0000-4000-8000-000000000001','agt_a_verifier','auditor'),
('00000000-0000-4000-8000-000000000002','agt_b_worker','agent');

INSERT INTO shards_v2.events(org_id,source_id,topic,body_json,payload_sha256,idempotency_key) VALUES
('00000000-0000-4000-8000-000000000001','agt_a_creator','audit.test','{}',sha256(convert_to('{}','UTF8')),'evt-a'),
('00000000-0000-4000-8000-000000000002','agt_b_worker','audit.test','{}',sha256(convert_to('{}','UTF8')),'evt-b');

-- A non-owner runtime role has no enrolment, destructive or ledger-head power.
SET ROLE shards_v2_runtime;
DO $$
BEGIN
 IF has_table_privilege(current_user,'shards_v2.audit_heads','UPDATE')
    OR has_table_privilege(current_user,'shards_v2.audit_heads','INSERT')
    OR has_table_privilege(current_user,'shards_v2.audit_heads','DELETE')
    OR has_table_privilege(current_user,'shards_v2.audit_entries','DELETE')
    OR has_table_privilege(current_user,'shards_v2.effect_outbox','DELETE')
    OR has_table_privilege(current_user,'shards_v2.verifications','INSERT')
    OR has_table_privilege(current_user,'shards_v2.principals','INSERT')
    OR has_table_privilege(current_user,'shards_v2.memberships','UPDATE')
    OR has_table_privilege(current_user,'shards_v2.agent_grants','INSERT') THEN
   RAISE EXCEPTION 'FAIL: runtime has authority/enrolment/destructive privileges';
 END IF;
END $$;

-- No identity context: no rows, even when a service holds SELECT.
DO $$
BEGIN
 IF (SELECT count(*) FROM shards_v2.events) <> 0 OR
    (SELECT count(*) FROM shards_v2.organizations) <> 0 THEN
    RAISE EXCEPTION 'FAIL: absent tenant context leaked records';
 END IF;
 BEGIN
   INSERT INTO shards_v2.events(org_id,source_id,topic,body_json,payload_sha256,idempotency_key)
   VALUES ('00000000-0000-4000-8000-000000000001','agt_a_creator','forged','{}',
           sha256(convert_to('{}','UTF8')),'no-context');
   RAISE EXCEPTION 'FAIL: missing tenant was allowed to insert';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;

-- Tenant context exists exclusively for one transaction.
BEGIN;
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000001',true);
DO $$
BEGIN
 IF (SELECT resource_audience FROM shards_v2.organizations) <>
    'https://mcp.shardsinc.co.uk/orgs/00000000-0000-4000-8000-000000000001/mcp' THEN
   RAISE EXCEPTION 'FAIL: organisation audience not bound to UUID';
 END IF;
 IF (SELECT count(*) FROM shards_v2.events) <> 1 OR
    (SELECT count(*) FROM shards_v2.principals) <> 4 THEN
   RAISE EXCEPTION 'FAIL: tenant-A read isolation';
 END IF;
 BEGIN
   INSERT INTO shards_v2.tasks(org_id,task_id,creator_id,worker_id,input_json,payload_sha256)
   VALUES ('00000000-0000-4000-8000-000000000001','task_bad','agt_a_creator','agt_b_worker','{}',
           sha256(convert_to('{}','UTF8')));
   RAISE EXCEPTION 'FAIL: cross-tenant worker FK accepted';
 EXCEPTION WHEN foreign_key_violation THEN NULL;
 END;
 BEGIN
   INSERT INTO shards_v2.tasks(org_id,task_id,creator_id,worker_id,input_json,payload_sha256,state)
   VALUES ('00000000-0000-4000-8000-000000000001','task_bad','agt_a_creator','agt_a_worker','{}',
           sha256(convert_to('{}','UTF8')),'succeeded');
   RAISE EXCEPTION 'FAIL: task inserted as succeeded';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
 BEGIN
   INSERT INTO shards_v2.events(org_id,source_id,topic,body_json,payload_sha256,idempotency_key)
   VALUES ('00000000-0000-4000-8000-000000000002','agt_b_worker','forged','{}',
           sha256(convert_to('{}','UTF8')),'spoof-org');
   RAISE EXCEPTION 'FAIL: cross-org insert succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;

INSERT INTO shards_v2.tasks
 (org_id,task_id,creator_id,worker_id,input_json,payload_sha256,idempotency_key)
VALUES
 ('00000000-0000-4000-8000-000000000001','task_a','agt_a_creator','agt_a_worker','{"task":"safe test"}',
  sha256(convert_to('{"task":"safe test"}','UTF8')),'task-idem');
DO $queued_denial$
BEGIN
 BEGIN
   UPDATE shards_v2.tasks SET state='succeeded' WHERE task_id='task_a';
   RAISE EXCEPTION 'FAIL: queued->succeeded accepted';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $queued_denial$;
UPDATE shards_v2.tasks SET state='running',attempts=1 WHERE task_id='task_a';
UPDATE shards_v2.tasks SET state='reported',result_json='{"status":"checked"}' WHERE task_id='task_a';
DO $success_denial$
BEGIN
 BEGIN
   UPDATE shards_v2.tasks SET state='succeeded' WHERE task_id='task_a';
   RAISE EXCEPTION 'FAIL: succeeded without independent approval';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $success_denial$;

-- Generic worker role cannot write approval evidence at all.
DO $worker_privilege$
BEGIN
 BEGIN
  INSERT INTO shards_v2.verifications
   (org_id,task_id,creator_id,worker_id,verifier_id,decision,evidence_sha256,result_sha256,evidence_json)
  VALUES ('00000000-0000-4000-8000-000000000001','task_a','agt_a_creator','agt_a_worker',
   'agt_a_verifier','approved',decode(repeat('11',32),'hex'),
   sha256(convert_to('{"status":"checked"}'::jsonb::text,'UTF8')),'{}');
  RAISE EXCEPTION 'FAIL: worker inserted a forged reviewer record';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $worker_privilege$;

SET ROLE shards_v2_verifier;
SELECT set_config('shards.principal_id','agt_a_same',true);
DO $same_controller$
BEGIN
 BEGIN
   INSERT INTO shards_v2.verifications
      (org_id,task_id,creator_id,worker_id,verifier_id,decision,evidence_sha256,result_sha256,evidence_json)
   VALUES ('00000000-0000-4000-8000-000000000001','task_a','agt_a_creator','agt_a_worker',
     'agt_a_same','approved',decode(repeat('11',32),'hex'),sha256(convert_to('{"status": "checked"}'::jsonb::text,'UTF8')),'{"verified":false}');
   RAISE EXCEPTION 'FAIL: same-controller verifier approved';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $same_controller$;
SELECT set_config('shards.principal_id','agt_a_verifier',true);
INSERT INTO shards_v2.verifications
 (org_id,task_id,creator_id,worker_id,verifier_id,decision,evidence_sha256,result_sha256,evidence_json)
 VALUES ('00000000-0000-4000-8000-000000000001','task_a','agt_a_creator','agt_a_worker',
  'agt_a_verifier','approved',decode(repeat('11',32),'hex'),sha256(convert_to('{"status": "checked"}'::jsonb::text,'UTF8')),'{"ci":"independent fixture"}');
SET ROLE shards_v2_runtime;
SELECT set_config('shards.principal_id','',true);
UPDATE shards_v2.tasks SET state='succeeded' WHERE task_id='task_a';
DO $$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET result_json='{"status":"tampered"}' WHERE task_id='task_a';
  RAISE EXCEPTION 'FAIL: worker changed result after approval';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
DO $$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET state='queued' WHERE task_id='task_a';
  RAISE EXCEPTION 'FAIL: terminal task requeued';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
  UPDATE shards_v2.verifications SET decision='rejected' WHERE task_id='task_a';
  RAISE EXCEPTION 'FAIL: verifier evidence mutated';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;

-- An ambiguous effect cannot silently return to the queue.
INSERT INTO shards_v2.tasks
 (org_id,task_id,creator_id,worker_id,input_json,payload_sha256)
 VALUES ('00000000-0000-4000-8000-000000000001','task_uncertain','agt_a_creator',
  'agt_a_worker','{}',sha256(convert_to('{}','UTF8')));
UPDATE shards_v2.tasks SET state='running' WHERE task_id='task_uncertain';
UPDATE shards_v2.tasks SET state='needs_reconciliation' WHERE task_id='task_uncertain';
DO $$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET state='queued' WHERE task_id='task_uncertain';
  RAISE EXCEPTION 'FAIL: uncertain task requeued';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $$;

-- A task with no effects must not leave reconciliation without evidence.
DO $unverified_resolution$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET state='failed' WHERE task_id='task_uncertain';
  RAISE EXCEPTION 'FAIL: task resolved without provider reconciliation';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $unverified_resolution$;

-- Use a separate live task for effect lifecycle. A terminal task can never
-- gain a new effect (prevents post-closure dispatch from racing a task close).
DO $late_effect$
BEGIN
 BEGIN
  INSERT INTO shards_v2.effect_outbox
   (org_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref)
  VALUES ('00000000-0000-4000-8000-000000000001',
   'task_a','agt_a_worker','github-pr','post-success',
   decode(repeat('aa',32),'hex'),'vault://ci/no-secret');
  RAISE EXCEPTION 'FAIL: external effect appended after task success';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $late_effect$;

INSERT INTO shards_v2.tasks
 (org_id,task_id,creator_id,worker_id,input_json,payload_sha256)
VALUES ('00000000-0000-4000-8000-000000000001','task_effect',
 'agt_a_creator','agt_a_worker','{"action":"provider-effect"}',
 sha256(convert_to('{"action":"provider-effect"}','UTF8')));
UPDATE shards_v2.tasks SET state='running' WHERE task_id='task_effect';

-- Outbox default is pending. Forged directly dispatched rows fail.
DO $$
BEGIN
 BEGIN
   INSERT INTO shards_v2.effect_outbox
      (org_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref,state)
    VALUES ('00000000-0000-4000-8000-000000000001','task_effect','agt_a_worker',
    'github-pr','bad',decode(repeat('aa',32),'hex'),'vault://ci/no-secret','dispatching');
   RAISE EXCEPTION 'FAIL: directly dispatched outbox insert accepted';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $$;
INSERT INTO shards_v2.effect_outbox
 (org_id,effect_id,task_id,actor_id,connector,idempotency_key,payload_sha256,payload_vault_ref)
 VALUES ('00000000-0000-4000-8000-000000000001',
 '00000000-0000-4000-8000-000000001111','task_effect','agt_a_worker',
 'github-pr','stable-effect-idem',decode(repeat('aa',32),'hex'),'vault://ci/no-secret');
DO $pending_effect_close$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET state='failed' WHERE task_id='task_effect';
  RAISE EXCEPTION 'FAIL: task closed over pending effect';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $pending_effect_close$;
UPDATE shards_v2.effect_outbox SET state='dispatching'
 WHERE effect_id='00000000-0000-4000-8000-000000001111';
DO $dispatching_effect_close$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET state='failed' WHERE task_id='task_effect';
  RAISE EXCEPTION 'FAIL: task closed over dispatching effect';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $dispatching_effect_close$;
UPDATE shards_v2.effect_outbox SET state='needs_reconciliation'
 WHERE effect_id='00000000-0000-4000-8000-000000001111';
DO $uncertain_effect_close$
BEGIN
 BEGIN
  UPDATE shards_v2.tasks SET state='failed' WHERE task_id='task_effect';
  RAISE EXCEPTION 'FAIL: task closed over uncertain effect';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $uncertain_effect_close$;

DO $$
BEGIN
 BEGIN
   UPDATE shards_v2.effect_outbox SET state='pending'
    WHERE effect_id='00000000-0000-4000-8000-000000001111';
   RAISE EXCEPTION 'FAIL: uncertain effect was requeued';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
   UPDATE shards_v2.effect_outbox SET state='reconciled'
    WHERE effect_id='00000000-0000-4000-8000-000000001111';
   RAISE EXCEPTION 'FAIL: reconciliation without evidence accepted';
 EXCEPTION WHEN check_violation THEN NULL;
 END;
END $$;
UPDATE shards_v2.effect_outbox
  SET state='reconciled',reconciliation_evidence='{"provider":"checked","status":"unexecuted"}'
  WHERE effect_id='00000000-0000-4000-8000-000000001111';
-- After independent provider-evidence reconciliation, a live task may fail.
UPDATE shards_v2.tasks SET state='failed' WHERE task_id='task_effect';

-- A delivered message cannot be rewritten, and an acknowledgment is one-way.
INSERT INTO shards_v2.messages
 (org_id,message_id,source_id,destination_id,body_json,payload_sha256,idempotency_key)
 VALUES ('00000000-0000-4000-8000-000000000001','message_a',
         'agt_a_creator','agt_a_worker','{"body":"original"}',
         sha256(convert_to('{"body":"original"}','UTF8')),'message-idem');
DO $message_rewrite$
BEGIN
 BEGIN
  UPDATE shards_v2.messages SET body_json='{"body":"forged"}' WHERE message_id='message_a';
  RAISE EXCEPTION 'FAIL: message payload changed after delivery';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $message_rewrite$;
UPDATE shards_v2.messages SET acknowledged_at=now() WHERE message_id='message_a';
DO $message_repeat$
BEGIN
 BEGIN
  UPDATE shards_v2.messages SET acknowledged_at=now() WHERE message_id='message_a';
  RAISE EXCEPTION 'FAIL: acknowledged message changed again';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $message_repeat$;

-- Canonical request ledger cannot rewrite payload or restart ambiguous effects.
INSERT INTO shards_v2.idempotency_requests
 (org_id,actor_id,operation,idempotency_key,payload_sha256,state)
 VALUES ('00000000-0000-4000-8000-000000000001','agt_a_creator','github-pr',
         'canonical-request',decode(repeat('cd',32),'hex'),'pending');
DO $request_mutation$
BEGIN
 BEGIN
  UPDATE shards_v2.idempotency_requests
  SET payload_sha256=decode(repeat('ee',32),'hex')
  WHERE idempotency_key='canonical-request';
  RAISE EXCEPTION 'FAIL: request digest was rewritten';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $request_mutation$;
UPDATE shards_v2.idempotency_requests
 SET state='needs_reconciliation',receipt_json='{"provider":"uncertain"}'
 WHERE idempotency_key='canonical-request';
DO $request_replay$
BEGIN
 BEGIN
  UPDATE shards_v2.idempotency_requests
  SET state='pending',receipt_json=NULL
  WHERE idempotency_key='canonical-request';
  RAISE EXCEPTION 'FAIL: uncertain request restarted';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $request_replay$;

-- Audit completeness and truth: only schema-owned business triggers append.
-- The runtime account cannot create even a cryptographically well-formed
-- arbitrary verification.approved event.
DO $audit_integrity$
DECLARE n bigint;
BEGIN
 SELECT count(*) INTO n FROM shards_v2.audit_entries
  WHERE org_id='00000000-0000-4000-8000-000000000001';
 IF n < 13 THEN
   RAISE EXCEPTION 'FAIL: missing automatic business-event audit entries (% found)',n;
 END IF;
 IF (SELECT count(*) FROM shards_v2.audit_entries
      WHERE action='task.created' AND subject_id IN
       ('task_a','task_uncertain','task_effect')) <> 3 THEN
   RAISE EXCEPTION 'FAIL: missing task-created audit events';
 END IF;
 IF (SELECT count(*) FROM shards_v2.audit_entries
      WHERE action='task.updated' AND subject_id='task_a') < 3 THEN
   RAISE EXCEPTION 'FAIL: missing task transition audit events';
 END IF;
 IF (SELECT count(*) FROM shards_v2.audit_entries
      WHERE action='effect.created' AND subject_id='task_effect') <> 1 OR
    (SELECT count(*) FROM shards_v2.audit_entries
      WHERE action='effect.updated' AND subject_id='task_effect') <> 3 THEN
   RAISE EXCEPTION 'FAIL: effect lifecycle audit incomplete';
 END IF;
 IF (SELECT count(*) FROM shards_v2.audit_entries
      WHERE action='verification.approved' AND subject_id='task_a'
        AND actor_id='agt_a_verifier') <> 1 THEN
   RAISE EXCEPTION 'FAIL: independent approval not audited';
 END IF;

 IF EXISTS (
   SELECT 1 FROM (
     SELECT a.*,row_number() OVER (ORDER BY a.seq) AS expected_seq,
      coalesce(lag(a.entry_sha256) OVER (ORDER BY a.seq),
        decode(repeat('00',32),'hex')) AS expected_previous
     FROM shards_v2.audit_entries a
     WHERE a.org_id='00000000-0000-4000-8000-000000000001'
   ) links
   WHERE links.seq<>links.expected_seq
    OR links.previous_sha256<>links.expected_previous
    OR links.entry_sha256<>sha256(links.previous_sha256 || links.canonical_record)
    OR links.canonical_record<>convert_to(jsonb_build_object(
       'version',links.canonical_version,'org_id',links.org_id::text,
       'seq',links.seq,'actor_id',links.actor_id,'action',links.action,
       'subject_id',links.subject_id,'details',links.details_json)::text,'UTF8')
 ) THEN
   RAISE EXCEPTION 'FAIL: auto-generated audit chain invalid';
 END IF;
END $audit_integrity$;

DO $audit_forgery$
BEGIN
 BEGIN
  INSERT INTO shards_v2.audit_entries
   (org_id,seq,actor_id,action,subject_id,details_json,
    canonical_record,previous_sha256,entry_sha256)
  SELECT a.org_id,a.seq+1,'agt_a_worker','verification.approved',
    'task_uncertain','{"invented":true}'::jsonb,convert_to('{}','UTF8'),
    a.entry_sha256,sha256(a.entry_sha256 || convert_to('{}','UTF8'))
   FROM shards_v2.audit_entries a ORDER BY a.seq DESC LIMIT 1;
  RAISE EXCEPTION 'FAIL: runtime forged approval event';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
  UPDATE shards_v2.audit_heads SET last_seq=999;
  RAISE EXCEPTION 'FAIL: runtime rewrote tenant audit head';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $audit_forgery$;

-- Replay assertion JTI is unique across organisations, even when scoped.
INSERT INTO shards_v2.edge_request_nonces
 (org_id,edge_key_id,jti_sha256,request_sha256,expires_at)
 VALUES ('00000000-0000-4000-8000-000000000001','edge-test-key',
 decode(repeat('33',32),'hex'),decode(repeat('44',32),'hex'),now()+interval '30 seconds');
COMMIT;

-- Same physical session must lose tenant context after COMMIT.
DO $$
BEGIN
 IF nullif(current_setting('shards.org_id',true),'') IS NOT NULL THEN
  RAISE EXCEPTION 'FAIL: pooled connection retains tenant setting';
 END IF;
 IF (SELECT count(*) FROM shards_v2.events)<>0 OR
    (SELECT count(*) FROM shards_v2.audit_entries)<>0 THEN
  RAISE EXCEPTION 'FAIL: pooled connection leaks prior tenant rows';
 END IF;
END $$;

BEGIN;
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000002',true);
DO $$
BEGIN
 IF (SELECT count(*) FROM shards_v2.events)<>1 OR
    (SELECT count(*) FROM shards_v2.tasks)<>0 OR
    (SELECT count(*) FROM shards_v2.audit_entries)<>0 THEN
  RAISE EXCEPTION 'FAIL: tenant B sees tenant A data';
 END IF;
 BEGIN
  INSERT INTO shards_v2.edge_request_nonces
   (org_id,edge_key_id,jti_sha256,request_sha256,expires_at)
  VALUES ('00000000-0000-4000-8000-000000000002','edge-test-key',
    decode(repeat('33',32),'hex'),decode(repeat('55',32),'hex'),now()+interval '30 seconds');
  RAISE EXCEPTION 'FAIL: edge nonce replay across organisations succeeded';
 EXCEPTION WHEN unique_violation THEN NULL;
 END;
END $$;
COMMIT;
RESET ROLE;

-- Maintenance is a separate role: it cannot delete a live nonce.
SET ROLE shards_v2_maintenance;
BEGIN;
SELECT set_config('shards.org_id','00000000-0000-4000-8000-000000000001',true);
DO $maintenance$
BEGIN
 BEGIN
  DELETE FROM shards_v2.edge_request_nonces;
  RAISE EXCEPTION 'FAIL: live nonce could be purged';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $maintenance$;
COMMIT;
RESET ROLE;

-- Privileged test-only check: the true head equals the generated chain.
DO $head_check$
DECLARE row_count bigint; h record;
BEGIN
 SELECT count(*) INTO row_count FROM shards_v2.audit_entries
  WHERE org_id='00000000-0000-4000-8000-000000000001';
 SELECT last_seq,head_sha256 INTO STRICT h FROM shards_v2.audit_heads
  WHERE org_id='00000000-0000-4000-8000-000000000001';
 IF h.last_seq<>row_count OR h.head_sha256 IS DISTINCT FROM
    (SELECT entry_sha256 FROM shards_v2.audit_entries
     WHERE org_id='00000000-0000-4000-8000-000000000001'
     ORDER BY seq DESC LIMIT 1) THEN
  RAISE EXCEPTION 'FAIL: canonical head does not match generated events';
 END IF;
END
$head_check$;

-- The signer role (not the runtime) may only build a structurally valid
-- receipt against this task's *actual* approval by this verifier with this
-- evidence digest. Signature bytes here are fake test fixtures.
DO $receipt_link$
DECLARE seq_task bigint; seq_approval bigint;
BEGIN
 SELECT seq INTO STRICT seq_task FROM shards_v2.audit_entries
  WHERE action='task.created' AND subject_id='task_a';
 SELECT seq INTO STRICT seq_approval FROM shards_v2.audit_entries
  WHERE action='verification.approved' AND subject_id='task_a'
    AND actor_id='agt_a_verifier';
 BEGIN
  INSERT INTO shards_v2.governance_receipts
   (org_id,task_id,verifier_id,audit_seq,evidence_sha256,signer_key_ref,signature)
  VALUES ('00000000-0000-4000-8000-000000000001',
    'task_a','agt_a_verifier',seq_task,decode(repeat('11',32),'hex'),
    'vault://ci/fixture-signer',decode('deadbeef','hex'));
  RAISE EXCEPTION 'FAIL: unrelated audit entry accepted as approval receipt';
 EXCEPTION WHEN foreign_key_violation THEN NULL;
 END;
 INSERT INTO shards_v2.governance_receipts
  (org_id,task_id,verifier_id,audit_seq,evidence_sha256,signer_key_ref,signature)
 VALUES ('00000000-0000-4000-8000-000000000001',
    'task_a','agt_a_verifier',seq_approval,decode(repeat('11',32),'hex'),
    'vault://ci/fixture-signer',decode('deadbeef','hex'));
END $receipt_link$;

-- DDL owner is still blocked by statement-level TRUNCATE protections.
DO $$
BEGIN
 BEGIN
  TRUNCATE shards_v2.audit_entries CASCADE;
  RAISE EXCEPTION 'FAIL: audit truncate accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
  TRUNCATE shards_v2.effect_outbox;
  RAISE EXCEPTION 'FAIL: outbox truncate accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;

DO $$
DECLARE t record;
BEGIN
 FOR t IN
  SELECT c.relname AS table_name, c.relrowsecurity, c.relforcerowsecurity
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='shards_v2' AND c.relkind='r'
 LOOP
  IF NOT t.relrowsecurity OR NOT t.relforcerowsecurity OR NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema='shards_v2' AND table_name=t.table_name AND column_name='org_id'
  ) THEN RAISE EXCEPTION 'FAIL: missing tenant/RLS policy on %',t.table_name;
  END IF;
 END LOOP;
 IF NOT EXISTS(
  SELECT 1 FROM shards_v2.audit_heads
   WHERE org_id='00000000-0000-4000-8000-000000000001' AND last_seq=2
 ) THEN RAISE EXCEPTION 'FAIL: audit head not advanced atomically'; END IF;
END $$;
SELECT 'TENANCY_SCHEMA_ACCEPTANCE_PASS' AS result;
