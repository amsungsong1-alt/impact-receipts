-- 0026_api_usage_log.sql
-- Laudon Ch.9 CRM, C4: real per-assessment Anthropic API token/cost logging.
-- Before this, no call site anywhere read `.usage` off an Anthropic response
-- (confirmed by grep during the Phase 1 audit) -- CLTV had no real cost
-- floor. See utils/api_pricing.py::log_api_usage()/compute_cost_pesewas()
-- for the single write/read path; knowledge/model_pricing.yaml for the
-- (explicitly placeholder, not verified) per-model rates.
create table if not exists api_usage_log (
  id                       bigserial primary key,
  email                    text references users(email) on delete set null,
  model                    text not null,
  call_site                text not null,
  -- 'irc_extraction' | 'batch_extraction' | 'score_explanation_chat' |
  -- 'council_haiku' | other future call sites -- see utils/api_pricing.py's
  -- ASSESSMENT_CALL_SITES for which ones gate a scored assessment.
  input_tokens             int not null default 0,
  output_tokens            int not null default 0,
  estimated_cost_pesewas   double precision not null default 0,
  created_at               timestamptz not null default now()
);

create index if not exists api_usage_log_email_created_idx on api_usage_log(email, created_at desc);
create index if not exists api_usage_log_call_site_idx on api_usage_log(call_site);

alter table api_usage_log disable row level security;

grant select, insert on api_usage_log to app_audits_rw;
grant usage, select on api_usage_log_id_seq to app_audits_rw;
