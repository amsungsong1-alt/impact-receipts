-- 0025_customer_profile_refresh_cron.sql
-- Schedules the customer-profile-refresh Edge Function (see
-- supabase/functions/customer-profile-refresh) to run hourly -- identical
-- pattern to 0014_pg_cron_onboarding_drip.sql. pg_cron/pg_net are already
-- enabled by that migration; this one just adds a second schedule entry.
--
-- Replace <PROJECT_REF> and <CRON_SECRET> by hand in the SQL editor before
-- running this statement -- never commit the real CRON_SECRET value to this
-- file. CRON_SECRET must match the value set via
-- `supabase secrets set CRON_SECRET=...` for the customer-profile-refresh
-- function (can reuse the same secret value as onboarding-drip's, or a
-- distinct one -- either works since each function checks its own env var).
select cron.schedule(
  'customer-profile-refresh-hourly',
  '15 * * * *',
  -- Offset 15 minutes past the hour, not on the hour like onboarding-drip's
  -- '0 * * * *' -- avoids both scheduled jobs' Postgres load landing in the
  -- same minute for no reason.
  $$
  select net.http_post(
    url := 'https://<PROJECT_REF>.supabase.co/functions/v1/customer-profile-refresh',
    headers := jsonb_build_object('Authorization', 'Bearer <CRON_SECRET>', 'Content-Type', 'application/json'),
    body := '{}'::jsonb
  );
  $$
);
