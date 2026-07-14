-- 0005_disable_rls.sql
-- This app has no Supabase Auth integration -- every table is accessed via
-- the anon key with app-level, email-based identity (not auth.uid()), so
-- Postgres row-level security has no role to play here; access control is
-- enforced in application code, not the database (see utils/db.py, utils/
-- auth.py, utils/metering.py). Newer Supabase projects appear to auto-enable
-- RLS (with zero policies, i.e. deny-all) on tables created via the SQL
-- editor, which silently broke every anon-key INSERT/UPDATE against the new
-- tables -- discovered via login_tokens ("new row violates row-level
-- security policy for table login_tokens", Postgres error 42501). Disable it
-- explicitly on every table this app uses, matching the no-RLS posture the
-- original users/examples tables already had.
alter table if exists users disable row level security;
alter table if exists examples disable row level security;
alter table if exists wa_conversations disable row level security;
alter table if exists login_tokens disable row level security;
alter table if exists sessions disable row level security;
alter table if exists payments disable row level security;
