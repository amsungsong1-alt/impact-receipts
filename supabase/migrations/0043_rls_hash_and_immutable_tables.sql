-- 0043_rls_hash_and_immutable_tables.sql
-- Laudon Ch.8 hardening, tier 3: outcome_feedback, assessment_links, and
-- rule_disputes are all keyed by metrics.session_hash() -- deliberately
-- one-way, never reversible to an account (see each table's own migration
-- comment, e.g. 0016_outcome_feedback.sql). export_verifications has no
-- tenant column at all by design (a public ?verify=<ref_id> lookup is meant
-- to work for anyone holding the printed ref_id). Row-ownership RLS is
-- impossible for any of these by construction, and none of the four appear
-- outside utils/*.py's SQLAlchemy connection as app_audits_rw (confirmed via
-- grep of every `.table(...)` call site) -- so, same as tier 2, the correct
-- policy is default-deny for authenticated/anon plus an app_audits_rw
-- bypass, which changes nothing about what that role can already do.
alter table outcome_feedback enable row level security;
create policy outcome_feedback_service_bypass on outcome_feedback
  for all to app_audits_rw using (true) with check (true);

alter table assessment_links enable row level security;
create policy assessment_links_service_bypass on assessment_links
  for all to app_audits_rw using (true) with check (true);

alter table rule_disputes enable row level security;
create policy rule_disputes_service_bypass on rule_disputes
  for all to app_audits_rw using (true) with check (true);

alter table export_verifications enable row level security;
create policy export_verifications_service_bypass on export_verifications
  for all to app_audits_rw using (true) with check (true);
