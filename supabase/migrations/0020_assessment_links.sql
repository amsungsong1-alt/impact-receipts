-- 0020_assessment_links.sql
-- Laudon Ch.12 Implementation-stage tracking (D3): links a scoring run to the
-- prior run it's an explicit revision of, so a before/after delta can be shown
-- -- "did the fix actually raise the score?" Nothing today answers that;
-- summarize_monthly_trend() shows a coarse monthly aggregate, and
-- outcome_feedback (0016) tracks the ultimate donor decision, but neither
-- links two specific scoring runs together.
--
-- Must work for every user, not just those who opt into utils/audits.py's
-- saved-history feature (confirmed with product) -- so this can't extend the
-- opt-in, encrypted, plaintext-email-owned `audits` table. Instead it follows
-- the same discipline as outcome_feedback (0016) and export_verifications
-- (0019), the two existing tables that already work for every user regardless
-- of opt-in: user_hash is a one-way sha256 hash (metrics.session_hash(),
-- reused directly, never the email itself), and no raw submission content
-- (result statement, evidence description) is ever stored here -- only scores
-- and which of the 8 criteria was weakest at that point in time.
create table if not exists assessment_links (
  id                    bigserial primary key,
  assessment_id         text not null,
  -- generated at evaluation time (Screen 2), independent of export -- today
  -- ref_ids only exist for exported documents (export_verifications, 0019),
  -- so a user who never downloads anything still needs an id to link against.
  parent_assessment_id  text,
  -- null unless the user explicitly selected "this is a revision of..."; no
  -- automatic content-hash matching in this pass (see plan doc -- risk of
  -- false-positive links between unrelated results).
  user_hash             text not null,
  confidence_score      double precision,
  clarity_score         double precision,
  weakest_dimension     text,
  created_at            timestamptz not null default now()
);

create index if not exists assessment_links_user_hash_idx on assessment_links(user_hash, created_at);
create index if not exists assessment_links_assessment_id_idx on assessment_links(assessment_id);

alter table assessment_links disable row level security;

grant select, insert on assessment_links to app_audits_rw;
grant usage, select on assessment_links_id_seq to app_audits_rw;
-- No update/delete grant: rows are never edited after insert, matching
-- export_verifications' immutable-record convention.
