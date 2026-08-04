-- 0035_indicators.sql
-- Laudon Ch.6, C1: the indicator half of finding 4. logframe_library_items
-- (0007) is a structurally similar but ENTIRELY DISCONNECTED table -- a
-- saved library item has no FK to any assessment that used it, and an
-- assessment's actual logframe fields (today, inside the encrypted
-- submissions_json blob) have no FK to the library item they may have come
-- from. This table is the assessment side of that gap -- deliberately not
-- merged with logframe_library_items, which serves a different purpose
-- (a reusable, user-curated list independent of any one assessment).
--
-- The check constraint below is the literal fix for the date-sanity half of
-- finding 7 ("no endline before baseline") -- impossible to enforce today
-- since these fields aren't even typed as dates, let alone columns.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists indicators (
  id                     bigserial primary key,
  assessment_id          bigint not null references assessments(id) on delete cascade,
  indicator_name         text,
  logframe_target        text,
  logframe_baseline      text,
  logframe_achievement   text,
  baseline_date          date,
  endline_date           date,
  data_forthcoming       boolean not null default false,
  created_at             timestamptz not null default now(),
  check (endline_date is null or baseline_date is null or endline_date >= baseline_date)
);

create index if not exists indicators_assessment_idx on indicators(assessment_id);

-- RLS (Laudon Ch.8 hardening, 2026): ownership flows through
-- assessments.user_hash (one-way, see 0031_assessments.sql). Only
-- app_audits_rw ever touches this table; default-deny for every other role.
alter table indicators enable row level security;

create policy indicators_service_bypass on indicators
  for all to app_audits_rw using (true) with check (true);

grant select, insert on indicators to app_audits_rw;
grant usage, select on indicators_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists indicators;
