-- 0033_rules_fired.sql
-- Laudon Ch.6, C1: the fix for finding 5. rule_trace (utils/inference.py's
-- apply_rules() output) is computed fresh every evaluation and, when
-- persisted at all, lives only inside the encrypted evaluations_json blob.
-- rule_disputes.rule_id reads like a foreign key to a specific firing event,
-- but there has never been a firings table for it to actually reference --
-- it's just a string matching whatever the YAML rule base currently calls
-- that rule, with zero integrity tying a dispute to the run that fired it.
--
-- Only fired rules are written here (not the full trace of fired+unfired
-- rules apply_rules() returns) -- "reconstructable from stored data alone"
-- for a firing event only needs the firings that actually happened; the
-- full trace (including what was checked but didn't fire) stays a live,
-- recomputed-per-request view, same as it is today.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists rules_fired (
  id                 bigserial primary key,
  assessment_id      bigint not null references assessments(id) on delete cascade,
  rule_id            text not null,
  criterion          text not null check (criterion in (
    'Directness', 'Verification', 'Recency',
    'Definition', 'Measurement', 'Integrity', 'Scope', 'Governance'
  )),
  rule_base_version  text,
  created_at         timestamptz not null default now()
);

create index if not exists rules_fired_assessment_idx on rules_fired(assessment_id);
create index if not exists rules_fired_rule_id_idx on rules_fired(rule_id);

alter table rules_fired disable row level security;

grant select, insert on rules_fired to app_audits_rw;
grant usage, select on rules_fired_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists rules_fired;
