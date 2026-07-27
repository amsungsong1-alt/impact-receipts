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

alter table criterion_scores disable row level security;

grant select, insert on criterion_scores to app_audits_rw;
grant usage, select on criterion_scores_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists criterion_scores;
