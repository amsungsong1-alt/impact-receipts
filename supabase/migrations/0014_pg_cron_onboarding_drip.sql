-- 0014_pg_cron_onboarding_drip.sql
-- Schedules the onboarding-drip Edge Function (supabase/functions/onboarding-drip)
-- to run hourly, checking for accounts due their day-3/day-7 email. This is
-- the only scheduling mechanism in this stack that reaches signups from
-- BOTH deployment paths (Streamlit Cloud and the self-hosted VPS) since it
-- lives entirely in Supabase, rather than a host crontab tied to one
-- deployment (see README.md's existing TLS-renewal crontab, which is
-- VPS-only for comparison).
--
-- VERIFY AGAINST CURRENT SUPABASE DOCS: pg_cron/pg_net extension enablement
-- may require the Dashboard's Database -> Extensions UI rather than a
-- migration/SQL editor CREATE EXTENSION statement on some hosted plans --
-- same caveat as 0009's CREATE ROLE. If either statement below fails with a
-- permission error, enable both extensions via that UI instead, then run
-- only the cron.schedule() call below by hand in the SQL editor.
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Replace <PROJECT_REF> and <CRON_SECRET> by hand in the SQL editor before
-- running this statement -- never commit the real CRON_SECRET value to this
-- file (same posture as 0009's "password is NOT set here" note). CRON_SECRET
-- must match the value set via `supabase secrets set CRON_SECRET=...` for
-- the onboarding-drip function.
select cron.schedule(
  'onboarding-drip-hourly',
  '0 * * * *',
  $$
  select net.http_post(
    url := 'https://<PROJECT_REF>.supabase.co/functions/v1/onboarding-drip',
    headers := jsonb_build_object('Authorization', 'Bearer <CRON_SECRET>', 'Content-Type', 'application/json'),
    body := '{}'::jsonb
  );
  $$
);
