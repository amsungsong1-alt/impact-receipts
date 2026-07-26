-- 0029_cross_sell_recommendations.sql
-- Laudon Ch.9 CRM, C7: cross-sell logging. Recommendations are logged, not
-- auto-sent -- "log every recommendation and its outcome so the logic can
-- be evaluated rather than believed" (the build prompt's own framing).
-- Surfaced primarily as a "who to call" list on the admin dashboard
-- (utils/cross_sell.py), matching the prompt's own out-of-scope note that
-- founder-led sales beats automation at this volume.
create table if not exists cross_sell_recommendations (
  id                     bigserial primary key,
  email                  text not null references users(email) on delete cascade,
  recommendation_type    text not null,
  -- 'upgrade_to_subscription' | 'upgrade_to_org_plan' | 'training_or_template_product'
  shown_at               timestamptz not null default now(),
  outcome                text,
  -- null (undecided) | 'converted' | 'declined' | 'expired'
  resolved_at            timestamptz
);

create index if not exists cross_sell_recommendations_email_type_idx
  on cross_sell_recommendations(email, recommendation_type, shown_at desc);

alter table cross_sell_recommendations disable row level security;

grant select, insert, update on cross_sell_recommendations to app_audits_rw;
grant usage, select on cross_sell_recommendations_id_seq to app_audits_rw;
