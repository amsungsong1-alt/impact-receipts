-- 0006_audits.sql
-- Opt-in, per-account saved audit history. One row per submission-run (not per
-- individual result): app.py's evaluations/submissions_snapshot are always
-- built and life-cycled together as parallel lists of 1-3 items per run, and
-- the primary downloadable Readiness Card is always built from result #1 of
-- the run -- so "one audit" = "one run" is the natural grain here.
--
-- Populated only when a logged-in user explicitly checks "Save this audit to
-- my private history" on Screen 2 (utils/audits.py:save_audit). Nothing here
-- changes behavior for a user who never opts in.
create table if not exists audits (
  id                      bigserial primary key,
  email                   text not null references users(email) on delete cascade,
  ref_id                  text not null unique,
  created_at              timestamptz not null default now(),
  active_slots            int not null,
  submissions_json        jsonb not null,
  evaluations_json        jsonb not null,
  donor_framework         text,
  sector                  text,
  org_type                text,
  primary_confidence_score double precision,
  primary_clarity_score    double precision,
  primary_verdict         text
);

create index if not exists audits_email_idx on audits(email, created_at desc);
create index if not exists audits_bucket_idx on audits(donor_framework, sector, org_type);

-- This app has no Supabase Auth integration -- access is enforced in
-- application code (utils/audits.py scopes every query by email), not RLS.
-- See 0005_disable_rls.sql for why this must be explicit on every new table.
alter table audits disable row level security;
