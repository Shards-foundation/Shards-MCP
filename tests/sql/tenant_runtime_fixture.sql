\set ON_ERROR_STOP on
-- Runs ONLY against the disposable shards_contract_ci PostgreSQL service.
-- Test-only password; never use these credentials in any deployed environment.
CREATE ROLE shards_ci_v2_runtime LOGIN PASSWORD 'synthetic-v2-runtime-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE shards_contract_ci TO shards_ci_v2_runtime;
GRANT USAGE ON SCHEMA shards_v2 TO shards_ci_v2_runtime;
GRANT SELECT ON shards_v2.organizations, shards_v2.principals,
    shards_v2.memberships, shards_v2.tasks TO shards_ci_v2_runtime;

UPDATE shards_v2.principals
 SET external_issuer='https://issuer.example.invalid',
     external_subject='alice-a', scopes=ARRAY['task:read','agent:read']
 WHERE org_id='00000000-0000-4000-8000-000000000001'
   AND principal_id='agt_a_creator';
UPDATE shards_v2.principals
 SET external_issuer='https://issuer.example.invalid',
     external_subject='bob-b', scopes=ARRAY['task:read','agent:read']
 WHERE org_id='00000000-0000-4000-8000-000000000002'
   AND principal_id='agt_b_worker';
INSERT INTO shards_v2.principals
(org_id,principal_id,kind,name,external_issuer,external_subject,scopes)
VALUES
('00000000-0000-4000-8000-000000000001','agt_a_auditor','agent',
 'Auditor A','https://issuer.example.invalid','auditor-a',
 ARRAY['task:read','task:claim']::text[]),
('00000000-0000-4000-8000-000000000001','agt_a_revoked','user',
 'Revoked A','https://issuer.example.invalid','revoked-a',
 ARRAY['task:read']::text[]);
INSERT INTO shards_v2.memberships(org_id,principal_id,role,revoked_at)
VALUES
('00000000-0000-4000-8000-000000000001','agt_a_creator','member',NULL),
('00000000-0000-4000-8000-000000000002','agt_b_worker','agent',NULL),
('00000000-0000-4000-8000-000000000001','agt_a_auditor','auditor',NULL),
('00000000-0000-4000-8000-000000000001','agt_a_revoked','member',now());
