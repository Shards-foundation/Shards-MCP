-- Operator-only CLUSTER bootstrap, not a tenant database migration.
-- Managed PostgreSQL: a DBA may create equivalent roles with the attributes
-- below. Safe to execute repeatedly in a cluster with CREATEROLE privilege.
DO $bootstrap$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='shards_v2_runtime') THEN
    CREATE ROLE shards_v2_runtime NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='shards_v2_verifier') THEN
    CREATE ROLE shards_v2_verifier NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='shards_v2_maintenance') THEN
    CREATE ROLE shards_v2_maintenance NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
 END IF;
END
$bootstrap$;
DO $verify$
BEGIN
 IF (SELECT count(*) FROM pg_roles
    WHERE rolname IN ('shards_v2_runtime','shards_v2_verifier','shards_v2_maintenance')
      AND NOT (rolsuper OR rolbypassrls OR rolcanlogin OR rolcreaterole
               OR rolcreatedb OR rolreplication OR rolinherit)) <> 3
    OR EXISTS (
      SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
       WHERE r.rolname IN ('shards_v2_runtime','shards_v2_verifier','shards_v2_maintenance')
    ) THEN
     RAISE EXCEPTION 'missing or insecure v2 role attributes or memberships'
       USING ERRCODE='42501';
 END IF;
END
$verify$;
