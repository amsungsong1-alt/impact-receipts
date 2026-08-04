-- 0042_rls_aggregate_and_access_log.sql
-- Laudon Ch.8 hardening, tier 2 (admin-only, no anon-key path at all --
-- confirmed by grepping every `.table(...)` call site in utils/*.py: neither
-- table appears outside utils/audits.py's SQLAlchemy connection as
-- app_audits_rw). Default-deny for authenticated/anon, with an explicit
-- bypass policy for app_audits_rw so enabling RLS is a behavior no-op for
-- the only role that legitimately touches these tables -- see
-- 0009_least_privilege_role.sql / 0010_access_log.sql for those GRANTs.
--
-- access_log specifically: this pairs with 0010's GRANT-scope append-only
-- guarantee (app_audits_rw has no UPDATE/DELETE grant here) to close the
-- other half of that guarantee -- previously, RLS being off meant a
-- superuser-level Postgres session could still read/write it freely with no
-- policy layer at all; RLS + this bypass doesn't change what app_audits_rw
-- can do (still governed by its GRANTs), but does mean any future role
-- added without an explicit policy is denied by default rather than
-- silently inheriting access.
alter table audit_aggregate_stats enable row level security;

create policy audit_aggregate_stats_service_bypass on audit_aggregate_stats
  for all to app_audits_rw using (true) with check (true);

alter table access_log enable row level security;

create policy access_log_service_bypass on access_log
  for all to app_audits_rw using (true) with check (true);
