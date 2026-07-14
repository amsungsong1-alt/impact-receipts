-- 0008_aggregate_stats.sql
-- Anonymized aggregate score distributions powering the "How you compare"
-- benchmark. One row per (donor, sector, org_type) bucket -- donor is the
-- submission's actual donor identity (audits.donor, e.g. USAID/FCDO/GIZ/
-- World Bank -- from app.py's donor_selected field), not the app's separate
-- donor_framework crosswalk-display selector, which most submissions leave
-- at its "Generic" default and isn't a meaningful comparison axis. org_type
-- is included because it changes the actual pass/fail threshold used for
-- scoring (3.5 CBO/Government, 3.75 National NGO, 4.0 INGO; see evaluator.py),
-- so bucketing by donor+sector alone would compare submissions scored against
-- different bars. confidence_scores/clarity_scores hold raw score numbers
-- only -- no submission content, no free text -- so an exact empirical
-- percentile can be computed at read time without storing anything
-- identifying. Recomputed synchronously by utils/audits.py immediately after
-- each opt-in audit save; no scheduled job needed given the low write volume.
create table if not exists audit_aggregate_stats (
  donor            text not null,
  sector           text not null,
  org_type         text not null,
  sample_size      int not null default 0,
  confidence_scores jsonb not null default '[]',
  clarity_scores    jsonb not null default '[]',
  updated_at       timestamptz not null default now(),
  primary key (donor, sector, org_type)
);

alter table audit_aggregate_stats disable row level security;
