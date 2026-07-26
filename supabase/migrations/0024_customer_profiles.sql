-- 0024_customer_profiles.sql
-- Laudon Ch.9 (CRM, C1): consolidates every touch point this app actually has
-- (crm_events, payments, wa_conversations, users) into one materialized
-- customer_profiles row per account, plus an append-only
-- customer_segment_history log for tracking behavioural-segment transitions
-- over time (utils/crm.py::build_behavioral_segments()/record_segment_transition()).
--
-- Deliberately NOT computed ad hoc by the Python app: refresh_customer_profiles()
-- below is the single assembly path (Section D's acceptance criterion), invoked
-- on a schedule by the customer-profile-refresh Edge Function (see
-- supabase/functions/customer-profile-refresh/ and 0025's pg_cron schedule) --
-- same reasoning as the existing onboarding-drip Edge Function: Streamlit Cloud
-- and the self-hosted VPS have no built-in job scheduler, and putting the
-- actual multi-table join/aggregation logic in one SQL function (rather than
-- hand-written TypeScript) avoids a second copy of this logic to keep in sync
-- by hand -- the exact pain point CLAUDE.md already flags for onboarding-drip's
-- duplicated HTML templates.
--
-- Python (utils/customer_profiles.py) only ever SELECTs from customer_profiles
-- -- it never recomputes anything itself, so there is exactly one place this
-- consolidation logic lives.

create table if not exists customer_profiles (
  email                                   text primary key references users(email) on delete cascade,
  plan                                    text,
  subscription_status                     text,
  signup_at                               timestamptz,
  last_active_at                          timestamptz,
  -- "activity" here matches utils/crm.py's existing _last_active_by_email()
  -- semantics: MAX(created_at) across ALL crm_events, not just audit_run.
  total_assessments                       int not null default 0,
  assessments_last_30d                    int not null default 0,
  revision_count_last_30d                 int not null default 0,
  lifetime_payment_count                  int not null default 0,
  lifetime_revenue_pesewas                bigint not null default 0,
  last_payment_status                     text,
  last_payment_at                         timestamptz,
  wa_conversation_count                   int not null default 0,
  last_wa_at                              timestamptz,
  email_domain                            text,
  domain_user_count                       int not null default 1,
  distinct_donor_count_30d                int not null default 0,
  -- Feeds the "dormant_seasonal" behavioural segment: true if this account
  -- had ANY crm_events activity in this same calendar month one year ago --
  -- an approximate proxy for "active in this reporting season last cycle."
  active_in_equivalent_window_last_cycle  boolean not null default false,
  computed_at                             timestamptz
);

create index if not exists customer_profiles_domain_idx on customer_profiles(email_domain);

alter table customer_profiles disable row level security;

-- SELECT only -- the Python app never writes this table; only
-- refresh_customer_profiles() (via the service-role Edge Function) does.
grant select on customer_profiles to app_audits_rw;


create table if not exists customer_segment_history (
  id           bigserial primary key,
  email        text not null references users(email) on delete cascade,
  segment      text not null,
  computed_at  timestamptz not null default now()
);

create index if not exists customer_segment_history_email_computed_idx
  on customer_segment_history(email, computed_at desc);

alter table customer_segment_history disable row level security;

-- Append-only, same convention as rule_disputes/access_log -- a segment
-- transition is never edited or deleted after being recorded.
grant select, insert on customer_segment_history to app_audits_rw;
grant usage, select on customer_segment_history_id_seq to app_audits_rw;


-- The single CustomerProfile assembly path. security definer so the
-- Edge Function's service-role invocation (which bypasses RLS/grants
-- entirely) and any future SQL-editor manual run both work identically.
create or replace function refresh_customer_profiles()
returns int
language plpgsql
security definer
as $$
declare
  affected int;
begin
  with crm_agg as (
    select
      email,
      max(created_at) as last_active_at,
      count(*) filter (where event_type = 'audit_run') as total_assessments,
      count(*) filter (
        where event_type = 'audit_run' and created_at >= now() - interval '30 days'
      ) as assessments_last_30d,
      count(*) filter (
        where event_type = 'revision_run' and created_at >= now() - interval '30 days'
      ) as revision_count_last_30d,
      count(distinct (metadata->>'donor')) filter (
        where event_type = 'framework_used' and created_at >= now() - interval '30 days'
      ) as distinct_donor_count_30d,
      bool_or(
        extract(month from created_at) = extract(month from now())
        and extract(year from created_at) = extract(year from now()) - 1
      ) as active_in_equivalent_window_last_cycle
    from crm_events
    group by email
  ),
  pay_agg as (
    select
      email,
      count(*) as lifetime_payment_count,
      coalesce(sum(amount_pesewas) filter (where status = 'success'), 0) as lifetime_revenue_pesewas,
      max(created_at) as last_payment_at
    from payments
    group by email
  ),
  pay_last_status as (
    select distinct on (email) email, status as last_payment_status
    from payments
    order by email, created_at desc
  ),
  wa_agg as (
    select
      user_email as email,
      count(*) as wa_conversation_count,
      max(created_at) as last_wa_at
    from wa_conversations
    where user_email is not null and user_email <> ''
    group by user_email
  ),
  domain_counts as (
    select
      lower(split_part(email, '@', 2)) as email_domain,
      count(distinct email) as domain_user_count
    from users
    group by lower(split_part(email, '@', 2))
  )
  insert into customer_profiles (
    email, plan, subscription_status, signup_at, last_active_at,
    total_assessments, assessments_last_30d, revision_count_last_30d,
    lifetime_payment_count, lifetime_revenue_pesewas, last_payment_status, last_payment_at,
    wa_conversation_count, last_wa_at, email_domain, domain_user_count,
    distinct_donor_count_30d, active_in_equivalent_window_last_cycle, computed_at
  )
  select
    u.email,
    u.plan,
    u.subscription_status,
    u.created_at,
    crm_agg.last_active_at,
    coalesce(crm_agg.total_assessments, 0),
    coalesce(crm_agg.assessments_last_30d, 0),
    coalesce(crm_agg.revision_count_last_30d, 0),
    coalesce(pay_agg.lifetime_payment_count, 0),
    coalesce(pay_agg.lifetime_revenue_pesewas, 0),
    pay_last_status.last_payment_status,
    pay_agg.last_payment_at,
    coalesce(wa_agg.wa_conversation_count, 0),
    wa_agg.last_wa_at,
    lower(split_part(u.email, '@', 2)),
    coalesce(domain_counts.domain_user_count, 1),
    coalesce(crm_agg.distinct_donor_count_30d, 0),
    coalesce(crm_agg.active_in_equivalent_window_last_cycle, false),
    now()
  from users u
  left join crm_agg on crm_agg.email = u.email
  left join pay_agg on pay_agg.email = u.email
  left join pay_last_status on pay_last_status.email = u.email
  left join wa_agg on wa_agg.email = u.email
  left join domain_counts on domain_counts.email_domain = lower(split_part(u.email, '@', 2))
  on conflict (email) do update set
    plan = excluded.plan,
    subscription_status = excluded.subscription_status,
    signup_at = excluded.signup_at,
    last_active_at = excluded.last_active_at,
    total_assessments = excluded.total_assessments,
    assessments_last_30d = excluded.assessments_last_30d,
    revision_count_last_30d = excluded.revision_count_last_30d,
    lifetime_payment_count = excluded.lifetime_payment_count,
    lifetime_revenue_pesewas = excluded.lifetime_revenue_pesewas,
    last_payment_status = excluded.last_payment_status,
    last_payment_at = excluded.last_payment_at,
    wa_conversation_count = excluded.wa_conversation_count,
    last_wa_at = excluded.last_wa_at,
    email_domain = excluded.email_domain,
    domain_user_count = excluded.domain_user_count,
    distinct_donor_count_30d = excluded.distinct_donor_count_30d,
    active_in_equivalent_window_last_cycle = excluded.active_in_equivalent_window_last_cycle,
    computed_at = excluded.computed_at;

  get diagnostics affected = row_count;
  return affected;
end;
$$;

grant execute on function refresh_customer_profiles() to app_audits_rw;
