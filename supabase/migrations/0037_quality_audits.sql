-- 0037_quality_audits.sql
-- Laudon Ch.6, C3: storage for scripts/quality_audit.py's findings -- one
-- row per (dimension, table, column) finding on each run, so a run's
-- results are queryable/comparable over time, not just printed and
-- discarded. Ch.12's seven-dimension table (completeness, consistency,
-- uniqueness, validity, timeliness, accuracy, accessibility) is what this
-- chapter operationalises against ImpactProof's own data.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists quality_audits (
  id            bigserial primary key,
  run_at        timestamptz not null default now(),
  dimension     text not null check (dimension in (
    'completeness', 'consistency', 'uniqueness', 'validity', 'timeliness'
  )),
  -- 'accuracy'/'accessibility' are intentionally excluded from this CHECK --
  -- Laudon's own remaining two of seven dimensions require ground truth or
  -- an end-user perception survey ImpactProof doesn't have; the audit
  -- script documents this as "not automatable," never writes a row that
  -- pretends otherwise.
  table_name    text not null,
  column_name   text,
  finding       text not null,
  severity      text not null check (severity in ('info', 'warning', 'critical')),
  sample_count  int
);

create index if not exists quality_audits_run_idx on quality_audits(run_at desc);
create index if not exists quality_audits_table_idx on quality_audits(table_name, dimension);

-- RLS (Laudon Ch.8 hardening, 2026): system-level findings, not per-user
-- data. Only app_audits_rw (the internal audit script's connection) ever
-- touches this table; default-deny for every other role.
alter table quality_audits enable row level security;

create policy quality_audits_service_bypass on quality_audits
  for all to app_audits_rw using (true) with check (true);

grant select, insert on quality_audits to app_audits_rw;
grant usage, select on quality_audits_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists quality_audits;
