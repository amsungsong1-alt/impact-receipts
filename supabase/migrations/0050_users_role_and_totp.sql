-- 0050_users_role_and_totp.sql
-- Laudon Ch.8 hardening, C3 (IAM): least-privilege role tiers and mandatory
-- 2FA for admin/owner, layered on top of (not replacing) the existing
-- is_admin boolean + ADMIN_PASSPHRASE gate.
--
-- Scope note: ImpactProof has no customer-facing multi-seat organisation
-- feature today (migration 0030_organisations.sql is written but
-- deliberately not yet applied -- see its own header). "owner/admin/
-- analyst/viewer" role tiers therefore apply to the one place roles
-- concretely exist in this codebase: INTERNAL ImpactProof staff access to
-- the admin dashboard (_render_admin_view() in app.py), not a per-customer
-- team-membership model. Building the latter is a separate, larger product
-- feature (team invites, per-org seats, billing implications) that this
-- hardening pass does not invent.
--
--   'user'    -- default; a normal customer account, zero admin surface.
--   'analyst' -- reserved for a future internal hire with read-only access
--               to the admin dashboard's metrics/segments (not yet wired
--               into any code path -- the column exists so it's not a
--               later schema migration when that need arises).
--   'admin'   -- current is_admin=true equivalent: full admin dashboard
--               access, gated behind ADMIN_PASSPHRASE + mandatory TOTP.
--   'owner'   -- reserved for the most destructive future admin actions
--               (e.g. a cross-account data operation) -- not yet
--               distinguished from 'admin' by any code path today; the
--               tier exists so a future destructive feature has somewhere
--               to attach a stricter check without another migration.
alter table users add column if not exists role text not null default 'user'
  check (role in ('user', 'analyst', 'admin', 'owner'));

-- Backfill: every existing is_admin=true account becomes role='admin'.
-- is_admin itself is left in place, not dropped -- app._is_authorized_admin()
-- checks BOTH (role IN ('admin','owner') OR is_admin), so this migration is
-- purely additive and cannot lock out an existing admin account if the
-- backfill below is ever re-run or partially applied.
update users set role = 'admin' where is_admin = true and role = 'user';

-- TOTP secret is Fernet-encrypted by application code (utils/crypto.py,
-- same key as audits.submissions_json) before being written here -- never
-- store it in plaintext, it's a durable credential, not a session token.
alter table users add column if not exists totp_secret text;
alter table users add column if not exists totp_enabled boolean not null default false;
