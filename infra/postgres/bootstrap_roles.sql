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
 IF EXISTS(SELECT 1 FROM pg_roles
   WHERE rolname IN ('shards_v2_runtime','shards_v2_verifier','shards_v2_maintenance')
   AND (rolcanlogin OR rolbypassrls OR rolsuper)) THEN
    RAISE EXCEPTION 'insecure role attributes';
 END IF;
END
$verify$;
