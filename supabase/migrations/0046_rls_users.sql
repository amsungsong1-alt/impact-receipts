-- 0046_rls_users.sql
-- Laudon Ch.8 hardening, tier 6 (users -- the identity anchor).
--
-- *** DO NOT APPLY THIS MIGRATION until utils/db.py's own calls are routed
-- through a per-user Supabase Auth JWT. utils/supabase_auth.py and
-- utils/auth.py::attach_auth_session/get_auth_session already mint and
-- store that JWT as of this hardening pass, but utils/db.py's
-- get_user/upsert_user/mark_paid/set_user_plan/save_user_draft/etc. still
-- query through the plain anon-key client, which carries no auth.uid() at
-- all. Enabling this migration before that wiring lands would make every
-- one of those calls fail the SELECT/UPDATE policy below and lock every
-- user out of their own account, including at login. Tracked as the
-- remaining piece of the Ch.8 RLS rollout. ***
--
-- Policy design, effective once that wiring lands:
--   - INSERT: anon + authenticated, unrestricted -- upsert_user() creates a
--     brand-new row BEFORE any Supabase Auth session exists (see
--     utils/auth.py::generate_magic_link_token/issue_session_token, both of
--     which call it pre-verification) -- same chicken-and-egg as
--     login_tokens/sessions (see 0049). The insert always writes safe
--     defaults (is_paid=false, free_checks_used=0) from application code,
--     never caller-supplied privilege columns.
--   - SELECT/UPDATE: authenticated only, scoped to the caller's own row via
--     auth_email() (see 0039_auth_email_function.sql).
--   - Two call sites are NOT "the caller acting on their own row" and must
--     never depend on this policy: utils.db.list_all_users() (admin CRM
--     dashboard, reads every account) and
--     utils.db.set_marketing_opt_out_by_token() (identified by an
--     unsubscribe token, no logged-in session at all). Both already route
--     through utils.db._get_service_client() (service-role, bypasses RLS by
--     platform design) as of this hardening pass specifically so this
--     migration doesn't need to special-case them in SQL.
alter table users enable row level security;

create policy users_insert_signup on users
  for insert to authenticated, anon with check (true);

create policy users_owner_select on users
  for select to authenticated
  using (email = auth_email());

create policy users_owner_update on users
  for update to authenticated
  using (email = auth_email())
  with check (email = auth_email());

-- Row-level ownership alone isn't enough: without this, an authenticated
-- caller who owns their row could still PATCH is_paid/is_admin/plan/
-- free_checks_used directly via PostgREST. Column-scoped grants restrict
-- self-service UPDATE to profile fields only -- billing/admin/usage columns
-- are written exclusively by utils/db.py's own functions
-- (mark_paid/set_user_plan/increment_checks's RPC), never directly by an
-- authenticated client.
revoke update on users from authenticated;
grant update (
  draft_json, preferred_currency, account_sector, primary_donors,
  country, profile_completed_at, profile_skipped, marketing_opt_out
) on users to authenticated;
