-- 0001_users_billing_columns.sql
-- Adds subscription/plan tracking columns to the existing `users` table, and an
-- atomic increment RPC to replace the read-then-write race in utils/db.py's
-- increment_checks(). Safe to run multiple times (all guarded with IF NOT EXISTS
-- / OR REPLACE). Zero behavior change on its own -- nothing calls these columns
-- or this function until later migrations/commits land.

alter table users add column if not exists plan text not null default 'free';
-- 'free' | 'professional' | 'agency' -- the durable tier signal that previously
-- didn't exist anywhere (the old session-only `_is_agency` flag was write-once,
-- never read, and lost on every new session).

alter table users add column if not exists paystack_customer_code text;
alter table users add column if not exists paystack_subscription_code text;
alter table users add column if not exists paystack_email_token text;
-- paystack_email_token is required to call Paystack's POST /subscription/disable
-- endpoint (VERIFY exact field name against current Paystack docs before use).

alter table users add column if not exists subscription_status text;
-- 'active' | 'attention' | 'non-renewing' | 'cancelled' | null
-- null means "never subscribed / one-off pay-per-use only."

alter table users add column if not exists email_verified boolean not null default false;
-- Set true on first successful magic-link redemption or OTP verification.

-- paid_until (existing column) continues to mean "current subscription period end" --
-- no separate period-end column is introduced. is_still_paid() in utils/db.py already
-- implements the correct comparison against it.

create or replace function increment_free_checks(p_email text)
returns int
language plpgsql
security definer
as $$
declare
  new_count int;
begin
  update users
  set free_checks_used = free_checks_used + 1
  where email = p_email
  returning free_checks_used into new_count;
  return new_count;  -- null if no row matched p_email
end;
$$;
