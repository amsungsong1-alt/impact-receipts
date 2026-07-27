-- 0034_evidence_claims.sql
-- Laudon Ch.6, C1: the evidence half of finding 4. Today the evidence array
-- (type/description/verified_by/recency) lives inside the same encrypted
-- blob as the free-text fields it's bundled with, indistinguishable at the
-- SQL level. This table promotes only the STRUCTURAL fields -- evidence
-- type, whether it was independently verified, and the recency date --
-- never the free-text description, which stays exactly where it is today
-- (encrypted, inside audits.submissions_json, opt-in only). A description
-- can contain beneficiary-specific detail; an evidence TYPE ("Attendance
-- sheets / participant registers") cannot.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists evidence_claims (
  id             bigserial primary key,
  assessment_id  bigint not null references assessments(id) on delete cascade,
  evidence_type  text,
  verified       boolean,
  recency_date   date,
  created_at     timestamptz not null default now()
);

create index if not exists evidence_claims_assessment_idx on evidence_claims(assessment_id);

alter table evidence_claims disable row level security;

grant select, insert on evidence_claims to app_audits_rw;
grant usage, select on evidence_claims_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists evidence_claims;
