-- 0055_warehouse_star_schema.sql
-- Laudon Ch.6 Phase 2, C4: a physically separate, denormalized-by-design
-- fact/dimension warehouse layer on top of Phase 1's OLTP-shaped
-- assessments/criterion_scores tables (0030-0037) -- a Kimball star schema
-- for C5's OLAP slice/dice queries, not a replacement for those tables,
-- which remain the write-path source of truth. Populated by
-- scripts/populate_warehouse.py; the app never writes to these tables
-- directly.
--
-- Depends on assessments/criterion_scores already existing, so this cannot
-- be applied before 0030-0037 are. Same status as those: NOT APPLIED TO
-- PRODUCTION -- written and reviewed only.

create table if not exists dim_donor (
  id     bigserial primary key,
  donor  text not null unique
);

create table if not exists dim_sector (
  id      bigserial primary key,
  sector  text not null unique
);

create table if not exists dim_org_type (
  id        bigserial primary key,
  org_type  text not null unique
);

-- A conventional Kimball date dimension -- populated incrementally by the
-- ETL script for the dates it actually encounters, not pre-seeded for
-- decades of unused rows.
create table if not exists dim_date (
  date_key    date primary key,
  year        int not null,
  quarter     int not null,
  month       int not null,
  month_name  text not null
);

-- Grain: one row per assessment. Dimension keys are denormalized directly
-- onto the fact row -- the point of a star schema is that OLAP queries
-- filter/group on these without joining back through assessments.
create table if not exists fact_assessment (
  id                      bigserial primary key,
  assessment_id           bigint not null unique references assessments(id) on delete cascade,
  donor_id                bigint references dim_donor(id),
  sector_id               bigint references dim_sector(id),
  org_type_id             bigint references dim_org_type(id),
  date_key                date references dim_date(date_key),
  confidence_score        numeric,
  clarity_score           numeric,
  verdict                 text,
  criteria_passed_count   int,
  criteria_failed_count   int,
  loaded_at               timestamptz not null default now()
);

create index if not exists fact_assessment_donor_idx on fact_assessment(donor_id);
create index if not exists fact_assessment_sector_idx on fact_assessment(sector_id);
create index if not exists fact_assessment_org_type_idx on fact_assessment(org_type_id);
create index if not exists fact_assessment_date_idx on fact_assessment(date_key);

-- RLS (Laudon Ch.8 hardening convention, applied consistently even though
-- this table hasn't shipped): system-level aggregate content, no per-user
-- tenant column -- only app_audits_rw (scripts/populate_warehouse.py's own
-- connection) ever touches these tables; default-deny for every other role.
alter table dim_donor enable row level security;
create policy dim_donor_service_bypass on dim_donor for all to app_audits_rw using (true) with check (true);
grant select, insert on dim_donor to app_audits_rw;
grant usage, select on dim_donor_id_seq to app_audits_rw;

alter table dim_sector enable row level security;
create policy dim_sector_service_bypass on dim_sector for all to app_audits_rw using (true) with check (true);
grant select, insert on dim_sector to app_audits_rw;
grant usage, select on dim_sector_id_seq to app_audits_rw;

alter table dim_org_type enable row level security;
create policy dim_org_type_service_bypass on dim_org_type for all to app_audits_rw using (true) with check (true);
grant select, insert on dim_org_type to app_audits_rw;
grant usage, select on dim_org_type_id_seq to app_audits_rw;

alter table dim_date enable row level security;
create policy dim_date_service_bypass on dim_date for all to app_audits_rw using (true) with check (true);
grant select, insert on dim_date to app_audits_rw;

alter table fact_assessment enable row level security;
create policy fact_assessment_service_bypass on fact_assessment for all to app_audits_rw using (true) with check (true);
grant select, insert on fact_assessment to app_audits_rw;
grant usage, select on fact_assessment_id_seq to app_audits_rw;

-- ============================================================
-- DOWN (manual rollback -- this repo has no down-migration tooling; run by
-- hand in the SQL editor if this migration needs to be reverted)
-- ============================================================
-- drop table if exists fact_assessment;
-- drop table if exists dim_date;
-- drop table if exists dim_org_type;
-- drop table if exists dim_sector;
-- drop table if exists dim_donor;
