-- 0030_organisations.sql
-- Laudon Ch.6, C1: resolves an unresolved many-to-many hiding as string
-- matching (see the Ch.6 audit's finding 3). Multiple `users` can belong to
-- one real-world organisation (same email domain) -- Ch.9's
-- customer_profiles.domain_user_count/org_emergent segment already DETECTS
-- this via split_part(email,'@',2) at query time, but there has never been
-- an organisations table with its own primary key for users to actually
-- foreign-key into.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only, per the Ch.6
-- prompt's explicit instruction. Apply only to a disposable branch/local
-- database first.
create table if not exists organisations (
  id          bigserial primary key,
  domain      text not null unique,
  name        text,
  created_at  timestamptz not null default now()
);

alter table organisations disable row level security;

grant select, insert, update on organisations to app_audits_rw;
grant usage, select on organisations_id_seq to app_audits_rw;

alter table users add column if not exists organisation_id bigint references organisations(id) on delete set null;

create index if not exists users_organisation_idx on users(organisation_id);

-- Backfill is deliberately conservative -- only domains with 2+ EXISTING
-- users get an organisations row and a users.organisation_id link; every
-- other account is left null rather than guessed. Known free-mail/personal
-- domains are excluded even if 2+ accounts happen to share one, since that
-- almost certainly means "two different people at two different orgs who
-- both use Gmail," not one organisation.
--
-- VERIFY the free-mail exclusion list below against real signup data before
-- relying on this backfill -- it's a reasonable starting list, not a
-- researched-complete one.
with shared_domains as (
  select lower(split_part(email, '@', 2)) as domain, count(*) as user_count
  from users
  where lower(split_part(email, '@', 2)) not in (
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com', 'aol.com'
  )
  group by lower(split_part(email, '@', 2))
  having count(*) >= 2
),
inserted as (
  insert into organisations (domain)
  select domain from shared_domains
  on conflict (domain) do nothing
  returning id, domain
)
update users
set organisation_id = inserted.id
from inserted
where lower(split_part(users.email, '@', 2)) = inserted.domain;

-- ============================================================
-- DOWN (manual rollback -- this repo has no down-migration tooling; run by
-- hand in the SQL editor if this migration needs to be reverted)
-- ============================================================
-- alter table users drop column if exists organisation_id;
-- drop table if exists organisations;
