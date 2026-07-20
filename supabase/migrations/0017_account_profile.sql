-- 0017_account_profile.sql
-- Lightweight personalization profile, captured once per account: sector,
-- primary donors, country. Feeds (a) sample-scenario/donor-framework
-- preselection, (b) sector-tailored fix-list language, (c) the monthly
-- evidence-quality-trends view -- all of which gracefully fall back to
-- today's generic behavior when this profile is absent (anonymous users,
-- or an account that skipped the capture prompt).
--
-- account_sector is a DIFFERENT, coarser taxonomy than the existing
-- per-submission `sector` field (see app.py's SECTOR_OPTIONS, which already
-- feeds the anonymized benchmark's (donor, sector, org_type) bucketing) --
-- deliberately not reusing that finer list here; the two serve different
-- purposes (coarse personalization vs. fine-grained benchmark bucketing).
alter table users add column if not exists account_sector text;
alter table users add column if not exists primary_donors text[];
alter table users add column if not exists country text;
alter table users add column if not exists profile_completed_at timestamptz;
alter table users add column if not exists profile_skipped boolean not null default false;
