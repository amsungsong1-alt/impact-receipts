-- 0010_access_log.sql
-- Append-only audit trail for every read/write utils/audits.py performs, plus
-- the data-deletion feature's own entry point. "Append-only" is enforced by
-- GRANT scope only (0009's app_audits_rw role gets select+insert here and
-- nothing else) -- deliberately not RLS, consistent with 0005's decision
-- that this app has no Supabase-Auth concept to key RLS policies off. A
-- superuser role could still bypass this; that is exactly why 0009's
-- least-privilege role is a hard prerequisite for this table to mean
-- anything, not a nice-to-have.
create table if not exists access_log (
  id            bigserial primary key,
  email         text not null,
  action        text not null,      -- e.g. 'save_audit', 'delete_audit', 'account_purge'
  resource_type text,               -- 'audit' | 'logframe_library' | 'account'
  resource_id   text,               -- stringified id, or null for account-level actions
  ip_address    text,               -- from Nginx-forwarded X-Forwarded-For; null pre-Docker deploy
  created_at    timestamptz not null default now()
);

create index if not exists access_log_email_action_idx on access_log(email, action, created_at desc);

alter table access_log disable row level security;

grant select, insert on access_log to app_audits_rw;
grant usage, select on access_log_id_seq to app_audits_rw;
-- No update/delete/truncate grant to any non-superuser role, by omission --
-- Postgres privileges are default-deny, so this alone makes the table
-- effectively append-only for anything connecting as app_audits_rw.
