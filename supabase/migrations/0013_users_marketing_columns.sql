-- 0013_users_marketing_columns.sql
-- Columns for the 3-email onboarding drip (day-3 case study, day-7 upgrade
-- offer) sent by the new onboarding-drip Edge Function on a pg_cron
-- schedule (see 0014). day3_email_sent_at/day7_email_sent_at let that
-- function query "who's due and hasn't been sent yet" idempotently, and
-- retry on its next hourly run if a send failed (the column stays null).
alter table users add column if not exists marketing_opt_out boolean not null default false;
alter table users add column if not exists day3_email_sent_at timestamptz;
alter table users add column if not exists day7_email_sent_at timestamptz;

-- VERIFY: gen_random_bytes() requires the pgcrypto extension. Most Supabase
-- projects have it enabled by default, but confirm before relying on the
-- column default below -- if it errors, enable it via Dashboard -> Database
-- -> Extensions -> pgcrypto, or run `create extension if not exists pgcrypto;`
-- in the SQL editor first, then re-run this ALTER.
alter table users add column if not exists unsubscribe_token text
  not null default encode(gen_random_bytes(16), 'hex');

-- No RLS-disable statement needed -- users' RLS was already disabled in
-- 0005; this migration only adds columns to an existing table.
