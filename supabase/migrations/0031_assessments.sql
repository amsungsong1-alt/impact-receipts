-- 0031_assessments.sql
-- Laudon Ch.6, C1: resolves finding 2 -- today `audits` is the only
-- row-per-scoring-run table, and it's opt-in only, so most usage produces no
-- durable relational row at all. This table is the anchor every other new
-- Ch.6 table (criterion_scores, rules_fired, evidence_claims, indicators,
-- documents) hangs off, and is deliberately populated for EVERY scored
-- assessment, not just opted-in saves.
--
-- Hash-keyed (user_hash, not email) -- confirmed with the user: same pattern
-- as the existing assessment_links/outcome_feedback/rule_disputes tables
-- (metrics.session_hash(), one-way, never reversible to an account). No free
-- text is ever stored here or in any table that references it -- only
-- scores, enums, dates, and booleans. This is what makes a future warehouse
-- built on these tables satisfy "no PII lands in the warehouse" by
-- construction, not by a later scrubbing step.
--
-- ref_id is nullable and NOT a foreign key to audits.ref_id -- an assessment
-- row here is created whether or not the user opts into saving full audit
-- history; ref_id is only ever populated for the subset that also opted in,
-- as a soft cross-reference for debugging/support, never joined against in
-- product code.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists assessments (
  id                bigserial primary key,
  user_hash         text not null,
  ref_id            text,
  donor             text,
  sector            text,
  org_type          text,
  evaluation_type   text,
  result_level      text,
  confidence_score  numeric check (confidence_score is null or (confidence_score >= 0 and confidence_score <= 5)),
  clarity_score     numeric check (clarity_score is null or (clarity_score >= 0 and clarity_score <= 5)),
  verdict           text,
  created_at        timestamptz not null default now()
);

create index if not exists assessments_user_hash_idx on assessments(user_hash, created_at desc);
create index if not exists assessments_bucket_idx on assessments(donor, sector, org_type);

-- RLS (Laudon Ch.8 hardening, 2026): user_hash is deliberately one-way (see
-- header comment above), so row-ownership RLS is impossible here by design
-- -- there is no predicate that proves "this caller owns this row" without
-- reversing a hash that exists specifically so it can't be reversed. The
-- only real caller today is utils/audits.py's SQLAlchemy connection as
-- app_audits_rw (see 0009_least_privilege_role.sql) -- default-deny for
-- every other role, so this table isn't reachable via the anon-key REST
-- client at all, not even for insert.
alter table assessments enable row level security;

create policy assessments_service_bypass on assessments
  for all to app_audits_rw using (true) with check (true);

grant select, insert on assessments to app_audits_rw;
grant usage, select on assessments_id_seq to app_audits_rw;
-- No update/delete grant: an assessment row is a point-in-time fact, never
-- edited after insert -- matches export_verifications'/assessment_links'
-- immutable-record convention.

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists assessments;
