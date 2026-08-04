-- 0038_users_auth_link.sql
-- First step of the Supabase Auth migration (Laudon Ch.8 security hardening):
-- this app has never had a Supabase Auth identity (see 0005_disable_rls.sql),
-- so Postgres RLS policies have had nothing to key off. This column links the
-- existing email-keyed `users` row to a real auth.users row, without touching
-- the login UX (magic link + 6-digit OTP) at all -- the auth.users row is
-- provisioned invisibly, server-side, the next time each user completes that
-- same login flow (see utils/supabase_auth.py::mint_auth_session).
--
-- `on delete set null`, not cascade: an Auth-side event (e.g. an admin
-- deleting the auth.users row directly in the Supabase dashboard) must never
-- silently delete this app's business data. Account erasure has its own
-- explicit, audited path (utils/audits.py::purge_account_audit_content).
alter table users
  add column if not exists auth_user_id uuid unique references auth.users(id) on delete set null;

create index if not exists users_auth_user_id_idx on users(auth_user_id);
