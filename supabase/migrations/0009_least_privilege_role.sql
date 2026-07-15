-- 0009_least_privilege_role.sql
-- utils/audits.py's SQLAlchemy engine (SUPABASE_DB_URL) likely connects
-- today as the default `postgres` superuser -- superusers bypass every
-- GRANT/REVOKE check, so the access-log append-only guarantee (0010) and
-- any future GRANT-based hardening have no effect until this role exists AND
-- SUPABASE_DB_URL is switched to use it (see README.md's Supabase Setup
-- section for the connection-string change).
--
-- VERIFY AGAINST CURRENT SUPABASE DOCS: whether CREATE ROLE is permitted via
-- a migration/SQL editor on a hosted project, or restricted to the
-- dashboard's Database -> Roles UI. If this statement fails with a
-- permission error, create the role via that UI instead and skip straight
-- to the GRANT statements below (which should work regardless).
create role app_audits_rw with login nosuperuser nocreatedb nocreaterole noinherit;

-- Password is NOT set here and must never be committed to this repo. Run
-- once, by hand, directly in the Supabase SQL editor (or set it via the
-- dashboard's Roles UI):
--   ALTER ROLE app_audits_rw WITH PASSWORD '<generate a strong random password>';

grant usage on schema public to app_audits_rw;

grant select, insert, update, delete
  on audits, logframe_libraries, logframe_library_items
  to app_audits_rw;

grant select, insert, update on audit_aggregate_stats to app_audits_rw;

-- bigserial PK columns need sequence USAGE for nextval() under a non-owner role
grant usage, select on
  audits_id_seq, logframe_libraries_id_seq, logframe_library_items_id_seq
  to app_audits_rw;

-- Explicitly NOT granted: users, examples, wa_conversations, login_tokens,
-- sessions, payments -- this role has zero reach into any table outside
-- utils/audits.py's own schema. A bug in audits.py (or a future SQL-
-- injection-class failure) cannot touch billing/auth/session data, because
-- the connection-level privilege to do so doesn't exist at all.
