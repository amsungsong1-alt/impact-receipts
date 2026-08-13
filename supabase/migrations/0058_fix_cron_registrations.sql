-- 0058_fix_cron_registrations.sql
-- Fixes two real production bugs discovered during a 2026-08-13 audit:
--
-- 1. customer-profile-refresh-hourly was registered (0025) but had been
--    firing every hour since 2026-07-27 and failing every single time --
--    "invalid URL ... Bad hostname" -- because whoever ran 0025 by hand kept
--    the literal angle brackets from the <PROJECT_REF> placeholder instead
--    of substituting the real value (url was
--    'https://<mikgzzsphsyveeaelpap>.supabase.co/...', brackets included).
--    Net effect: customer_profiles.computed_at was frozen at the one manual
--    invocation from that original deploy session and never advanced again,
--    so every downstream feature reading customer_profiles (the Ch.9
--    behavioural CRM dashboard, churn/CLTV, lifecycle triggers) was reading
--    a 17-day-stale snapshot despite real usage continuing.
--
-- 2. onboarding-drip-hourly (0014) was never registered in cron.job at all
--    -- the day-3/day-7 onboarding emails have never sent to anyone.
--
-- Both re-registered here with the correct (bracket-free) URL. Same
-- by-hand-substitution requirement as 0014/0025 -- replace <PROJECT_REF> and
-- <CRON_SECRET> in the SQL editor before running; never commit the real
-- secret value to this file. A fresh CRON_SECRET was generated and set via
-- `supabase secrets set` as part of this fix, since there was no way to
-- confirm the old value was still correct.

select cron.unschedule('customer-profile-refresh-hourly');

select cron.schedule(
  'customer-profile-refresh-hourly',
  '15 * * * *',
  $$
  select net.http_post(
    url := 'https://<PROJECT_REF>.supabase.co/functions/v1/customer-profile-refresh',
    headers := jsonb_build_object('Authorization', 'Bearer <CRON_SECRET>', 'Content-Type', 'application/json'),
    body := '{}'::jsonb
  );
  $$
);

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

-- Verification query, safe to re-run any time (no secret exposure):
--   select jobname, schedule, active from cron.job;
-- should show BOTH jobs, active = true. Check for actual successful runs
-- (not just registration) via:
--   select j.jobname, jrd.status, jrd.start_time
--   from cron.job_run_details jrd join cron.job j on j.jobid = jrd.jobid
--   order by jrd.start_time desc limit 20;

-- DOWN (manual rollback, run by hand if ever needed):
-- select cron.unschedule('customer-profile-refresh-hourly');
-- select cron.unschedule('onboarding-drip-hourly');
-- (then re-run 0025's/0014's original cron.schedule() blocks if reverting
-- to the pre-fix state is genuinely desired, which it never should be)
