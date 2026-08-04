-- 0044_rls_crm_and_internal_tables.sql
-- Laudon Ch.8 hardening, tier 4: email-keyed CRM/internal tables. All seven
-- are reached exclusively via utils/*.py's SQLAlchemy connection as
-- app_audits_rw (confirmed via grep of every `.table(...)` call site --
-- none of these names appear against the anon-key REST client) -- an
-- end user never reads/writes these directly, only server-side batch jobs
-- and the admin CRM dashboard (which itself goes through app_audits_rw, not
-- a per-user identity). Default-deny for authenticated/anon plus an
-- app_audits_rw bypass, matching tiers 2-3: a behavior no-op for the only
-- role that legitimately touches these tables.
alter table clients enable row level security;
create policy clients_service_bypass on clients
  for all to app_audits_rw using (true) with check (true);

alter table customer_profiles enable row level security;
create policy customer_profiles_service_bypass on customer_profiles
  for all to app_audits_rw using (true) with check (true);

alter table customer_segment_history enable row level security;
create policy customer_segment_history_service_bypass on customer_segment_history
  for all to app_audits_rw using (true) with check (true);

alter table crm_events enable row level security;
create policy crm_events_service_bypass on crm_events
  for all to app_audits_rw using (true) with check (true);

alter table api_usage_log enable row level security;
create policy api_usage_log_service_bypass on api_usage_log
  for all to app_audits_rw using (true) with check (true);

alter table lifecycle_triggers_log enable row level security;
create policy lifecycle_triggers_log_service_bypass on lifecycle_triggers_log
  for all to app_audits_rw using (true) with check (true);

alter table cross_sell_recommendations enable row level security;
create policy cross_sell_recommendations_service_bypass on cross_sell_recommendations
  for all to app_audits_rw using (true) with check (true);
