-- 0012_crm_events.sql
-- Per-account CRM/growth analytics events (signup, audit_run, framework_used,
-- tier_change, upgrade_prompt_shown/_clicked, whatsapp_click) -- deliberately
-- a NEW table, not an extension of 0010's access_log. access_log is a
-- permanent security-audit trail scoped to 5 narrow data-access actions and
-- is explicitly excluded from the account-deletion purge flow; this table
-- is high-volume marketing/growth data that SHOULD be purgeable on request
-- (see utils/crm.py's purge_account_crm_events, wired into the same "erase
-- my history" flow as utils/audits.py's purge_account_audit_content).
create table if not exists crm_events (
  id            bigserial primary key,
  email         text not null references users(email) on delete cascade,
  event_type    text not null,
  -- 'signup' | 'audit_run' | 'framework_used' | 'tier_change' |
  -- 'upgrade_prompt_shown' | 'upgrade_prompt_clicked' | 'whatsapp_click'
  metadata      jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists crm_events_email_created_idx on crm_events(email, created_at desc);
create index if not exists crm_events_type_created_idx on crm_events(event_type, created_at desc);

alter table crm_events disable row level security;

grant select, insert, delete on crm_events to app_audits_rw;
grant usage, select on crm_events_id_seq to app_audits_rw;
-- Unlike 0010's access_log (select+insert only, enforced append-only), this
-- table also gets delete -- specifically so purge_account_crm_events() can
-- run through app_audits_rw on the same SQLAlchemy connection as
-- utils.audits.purge_account_audit_content(), rather than needing a second
-- DB role/connection just for this one operation. The app itself never
-- issues an UPDATE/DELETE against this table outside that one purge path.
