-- 0016_outcome_feedback.sql
-- Outcome feedback loop: after a user downloads a Readiness Card or an Audit
-- My Report Excel workbook, we ask on their next visit whether the donor
-- accepted it. Deliberately NOT owned by email like audits/clients/crm_events
-- -- user_hash is a one-way sha256 hash (same technique as metrics.py's
-- session_hash(), reused directly rather than duplicated), so this table can
-- never be joined back to a specific account even by someone with full DB
-- access. No `references users(email)` FK is possible or intended here.
--
-- score_band/confidence_score/clarity_score are captured AT EXPORT TIME, not
-- joined from the `audits` table later -- saved-audit history is opt-in-only
-- (see 0006_audits.sql), so relying on it here would silently miss every
-- download from a user who never opted into saving. This table is meant to
-- work for every download, regardless of that separate opt-in.
create table if not exists outcome_feedback (
  id               bigserial primary key,
  ref_id           text not null,
  user_hash        text not null,
  export_type      text not null,
  -- 'readiness_card' | 'audit_excel'
  status           text not null default 'pending',
  -- 'pending' | 'answered' | 'skipped'
  response         text,
  -- 'Accepted' | 'Revisions requested' | 'Rejected' | 'Not yet submitted'
  score_band       text,
  -- confidence_label at export time: 'Strong' | 'Acceptable' | 'Weak' | 'High Risk'
  confidence_score double precision,
  clarity_score    double precision,
  created_at       timestamptz not null default now(),
  responded_at     timestamptz
);

create index if not exists outcome_feedback_hash_status_idx on outcome_feedback(user_hash, status, created_at);
create index if not exists outcome_feedback_ref_id_idx on outcome_feedback(ref_id);

alter table outcome_feedback disable row level security;

grant select, insert, update on outcome_feedback to app_audits_rw;
grant usage, select on outcome_feedback_id_seq to app_audits_rw;
-- No delete grant: nothing in the app ever deletes a response row (there's no
-- plaintext email to purge on an "erase my history" request -- the hash
-- alone isn't reversible to an account, so this table is out of scope for
-- purge_account_audit_content()/purge_account_crm_events(), unlike audits/
-- clients/crm_events which are all owned by a real email).
