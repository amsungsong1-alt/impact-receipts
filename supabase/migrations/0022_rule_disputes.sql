-- 0022_rule_disputes.sql
-- Laudon Ch.11 organisational learning loop (C6): when a user or reviewer
-- disputes one of the expert-system rule base's firings (knowledge/rules/*.yaml,
-- utils/inference.py), capture the dispute against the rule id so a MEL
-- specialist can review disputed rules and edit the YAML by hand -- codified
-- judgement stays human-owned; nothing here auto-tunes a rule from dispute
-- volume.
--
-- Anonymized (hashed email via metrics.session_hash(), same as
-- outcome_feedback/assessment_links) -- a dispute doesn't need row-ownership-
-- checked mutation, only insert + aggregate read for the admin ranking view,
-- so there's no reason to carry a plaintext email into a fourth
-- account-identified table alongside audits/clients/crm_events.
create table if not exists rule_disputes (
  id                 bigserial primary key,
  rule_id            text not null,
  rule_base_version  text,
  user_hash          text not null,
  reason             text,
  created_at         timestamptz not null default now()
);

create index if not exists rule_disputes_rule_id_idx on rule_disputes(rule_id);

alter table rule_disputes disable row level security;

grant select, insert on rule_disputes to app_audits_rw;
grant usage, select on rule_disputes_id_seq to app_audits_rw;
-- No update/delete grant: a dispute record is never edited after insert,
-- matching export_verifications'/outcome_feedback's append-only convention.
