-- 0002_login_tokens.sql
-- Single-use, short-lived magic-link login tokens. Distinct from the long-lived
-- session tokens in 0003_sessions.sql: a login token proves "you clicked the link
-- we emailed you" once, and is then exchanged for a session token.

create table if not exists login_tokens (
  token_hash   text primary key,        -- sha256(raw_token) hex -- the raw value is
                                         -- never persisted, only ever returned once
                                         -- at generation time
  email        text not null references users(email) on delete cascade,
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null,    -- created_at + 20 minutes
  redeemed_at  timestamptz,             -- null = unused; set = consumed (enforces
                                         -- single-use; a concurrent double-redeem
                                         -- attempt must lose the race via an
                                         -- UPDATE ... WHERE redeemed_at IS NULL)
  request_ip   text                     -- optional, abuse-detection only
);

create index if not exists login_tokens_email_idx on login_tokens(email);
