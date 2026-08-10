-- 0056_users_concessional_pricing.sql
-- Concessional (discounted) pricing for CBO/Government-type accounts,
-- gated behind manual admin approval -- not a self-service dropdown.
--
-- Context: knowledge/cltv_assumptions.yaml and scripts/pricing_model.py
-- already model a 60%-off CBO/Government tier, but pricing_model.py's own
-- check_cannibalization() flags why it was never wired into live pricing
-- as-is: a well-funded org could self-select "CBO" on a plain dropdown to
-- undercut Agency-tier pricing. This migration adds the fields needed for
-- a request -> admin-approval -> discounted-checkout flow instead of a
-- self-service one. Scope: CBO/Government tier only (60% off, matching
-- the number already modeled), monthly billing only -- National NGO's
-- already-modeled 30%-off tier and an annual concessional option are
-- deliberately deferred (same pattern, one more Paystack Plan + one more
-- request-form option, not a schema change).
--
-- Follows 0050_users_role_and_totp.sql's convention exactly: new columns
-- added directly to users (not a new table), since this is the same
-- shape of problem totp_secret/totp_enabled already solved -- an
-- admin-asserted fact about one account, not a new relation.
alter table users add column if not exists concessional_status text not null default 'none'
  check (concessional_status in ('none', 'requested', 'approved', 'denied'));

-- What the requester declared -- same two option strings Screen 1's own
-- org-type selectbox already uses (app.py), for consistency with the
-- scoring-threshold system this pricing tier is named after (but
-- structurally separate from -- see cltv_assumptions.yaml's own note that
-- pricing and scoring are independent mechanisms that happen to share
-- bucket names).
alter table users add column if not exists concessional_org_type text
  check (concessional_org_type is null or concessional_org_type in (
    'Community-Based Organisation (CBO)', 'Government department / local authority'
  ));
alter table users add column if not exists concessional_note text;
alter table users add column if not exists concessional_requested_at timestamptz;
alter table users add column if not exists concessional_approved_at timestamptz;
-- The approving admin's own email -- a lightweight accountability trail,
-- not a foreign key (admin accounts are just users.role IN ('admin','owner'),
-- no separate staff table exists to reference).
alter table users add column if not exists concessional_approved_by text;

-- No grant changes needed: 0046_rls_users.sql's `grant update (...) on
-- users to authenticated` is an explicit column allowlist, not a blanket
-- grant with per-column revokes -- these six new columns are excluded by
-- construction (simply not listed) unless a future migration deliberately
-- adds them. Writes go exclusively through utils/db.py's service-role
-- functions (request_concessional_pricing/set_user_concessional_status),
-- same as every other admin-asserted column on this table.

-- ==== DOWN (manual rollback -- this repo has no down-migration tooling) ====
-- alter table users drop column if exists concessional_status;
-- alter table users drop column if exists concessional_org_type;
-- alter table users drop column if exists concessional_note;
-- alter table users drop column if exists concessional_requested_at;
-- alter table users drop column if exists concessional_approved_at;
-- alter table users drop column if exists concessional_approved_by;
