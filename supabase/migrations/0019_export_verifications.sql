-- 0019_export_verifications.sql
-- Reference-ID verification lookup for exported documents (Readiness Card,
-- Audit My Report Excel, Framework Crosswalk, Portfolio Readiness Report).
-- Every export already prints a "Ref: IMP-..." style ID and told the reader
-- to "cite this reference ID" -- but nothing behind that ID was ever
-- checkable. This table is what a public ?verify=<ref_id> landing page
-- (utils/verification.py's verify_ref_id()) reads from.
--
-- Deliberately NOT the same table as outcome_feedback (0016): that table
-- drives a different feature (the donor-acceptance-followup banner) with a
-- fixed export-type allowlist and a pending/answered/skipped lifecycle that
-- doesn't apply to an immutable proof record -- reusing it would silently
-- expand that banner's scope. No user_hash/email here either: a verify
-- lookup is meant to work for anyone holding the printed ref_id, not just
-- the account that generated it.
--
-- content_hash is a SHA-256 digest of the normalized result statement +
-- evidence description/type + both scores -- never the raw text itself.
-- Re-hash-and-compare against a pasted document is explicitly out of scope
-- for v1 (fragile against copy-paste whitespace, risks false non-matches
-- undermining trust); the hash is stored now regardless so a v2 can add
-- that comparison without a second migration.
create table if not exists export_verifications (
  id               bigserial primary key,
  ref_id           text not null,
  export_type      text not null,
  -- 'readiness_card' | 'audit_excel' | 'framework_crosswalk' | 'portfolio_report'
  content_hash     text not null,
  confidence_score double precision,
  clarity_score    double precision,
  score_band       text,
  generated_at     timestamptz not null default now()
);

create index if not exists export_verifications_ref_id_idx on export_verifications(ref_id);

alter table export_verifications disable row level security;

grant select, insert on export_verifications to app_audits_rw;
grant usage, select on export_verifications_id_seq to app_audits_rw;
-- No update/delete grant: an immutable proof record -- nothing in the app
-- ever needs to change or remove a row here once written.
