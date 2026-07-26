-- 0028_lifecycle_triggers_log.sql
-- Laudon Ch.9 CRM, C6: deterministic, rule-based lifecycle triggers --
-- dedup/cooldown ledger so a trigger doesn't refire every page load.
-- Written from two places: utils/lifecycle_triggers.py (4 of the 5
-- triggers, fired live during a page load) and the customer-profile-refresh
-- Edge Function (the 5th, at_risk_reengagement, which by definition needs
-- to reach an account that isn't currently visiting -- see that function's
-- own comment for why this is the one deliberate exception to "assembly
-- logic lives in Python only").
create table if not exists lifecycle_triggers_log (
  id            bigserial primary key,
  email         text not null references users(email) on delete cascade,
  trigger_name  text not null,
  -- 'first_assessment_no_engagement' | 'org_emergent_detected' |
  -- 'payment_recovery' | 'testimonial_ask' | 'at_risk_reengagement'
  fired_at      timestamptz not null default now()
);

create index if not exists lifecycle_triggers_log_email_trigger_idx
  on lifecycle_triggers_log(email, trigger_name, fired_at desc);

alter table lifecycle_triggers_log disable row level security;

grant select, insert on lifecycle_triggers_log to app_audits_rw;
grant usage, select on lifecycle_triggers_log_id_seq to app_audits_rw;
