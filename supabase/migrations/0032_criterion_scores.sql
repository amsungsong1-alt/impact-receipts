-- 0032_criterion_scores.sql
-- Laudon Ch.6, C1: the literal fix for finding 1, the headline violation --
-- all 8 criteria's scores (evaluator.py's DIMENSION_MAP: Directness/
-- Verification/Recency/Definition/Measurement/Integrity/Scope/Governance)
-- exist today only as dict keys inside the encrypted evaluations_json blob.
-- Rows, not columns -- adding a 9th criterion is an INSERT pattern change,
-- never a schema migration.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists criterion_scores (
  id             bigserial primary key,
  assessment_id  bigint not null references assessments(id) on delete cascade,
  criterion      text not null check (criterion in (
    'Directness', 'Verification', 'Recency',
    'Definition', 'Measurement', 'Integrity', 'Scope', 'Governance'
  )),
  level          int,
  score          numeric,
  unique (assessment_id, criterion)
);

create index if not exists criterion_scores_assessment_idx on criterion_scores(assessment_id);
create index if not exists criterion_scores_criterion_idx on criterion_scores(criterion);

-- RLS (Laudon Ch.8 hardening, 2026): a criterion_scores row has no direct
-- tenant column -- ownership flows through assessments.user_hash, which is
-- deliberately one-way (see 0031_assessments.sql). Only app_audits_rw ever
-- touches this table; default-deny for every other role.
alter table criterion_scores enable row level security;

create policy criterion_scores_service_bypass on criterion_scores
  for all to app_audits_rw using (true) with check (true);

grant select, insert on criterion_scores to app_audits_rw;
grant usage, select on criterion_scores_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists criterion_scores;
