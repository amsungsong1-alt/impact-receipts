-- 0003_sessions.sql
-- Long-lived, bookmarkable session tokens mirrored into the app URL as
-- ?session=<raw_token>, so a returning user is silently re-authenticated without
-- retyping their email. A table (not columns on `users`) because a user can have
-- multiple concurrent sessions (multiple devices/browsers), each independently
-- revocable ("sign out this device" vs. "sign out everywhere").

create table if not exists sessions (
  token_hash    text primary key,       -- sha256(raw_token) hex -- raw value is
                                         -- never persisted, only returned once at
                                         -- issuance
  email         text not null references users(email) on delete cascade,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  expires_at    timestamptz not null,   -- created_at + 60 days; slides forward on
                                         -- use (see utils/auth.verify_session_token),
                                         -- throttled to avoid a DB write on every
                                         -- Streamlit rerun
  revoked_at    timestamptz,            -- null = valid; set = user signed out this
                                         -- device (or all devices, via a bulk update)
  user_agent    text                    -- optional, lets the billing page's device
                                         -- list show e.g. "Chrome on Windows"
);

create index if not exists sessions_email_idx on sessions(email);
