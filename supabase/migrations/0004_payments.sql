-- 0004_payments.sql
-- Durable invoice/payment history, populated from two independent paths: the
-- existing redirect-verify flow in app.py's Paystack callback handler, and the
-- new paystack-webhook Edge Function. Both paths must upsert on
-- (on_conflict="paystack_reference") rather than raw-insert, since either one
-- may see a given transaction reference first.

create table if not exists payments (
  id                  bigserial primary key,
  email               text not null references users(email) on delete cascade,
  paystack_reference  text not null unique,
  amount_pesewas      int not null,
  currency            text not null default 'GHS',
  plan                text,             -- 'per_use' | 'monthly' | 'annual' | 'agency'
                                         -- (our label, not Paystack's plan_code)
  status              text not null,    -- 'success' | 'failed'
  source              text not null,    -- 'redirect_verify' | 'webhook'
  paystack_event       text,            -- e.g. 'charge.success' when source='webhook';
                                         -- null when source='redirect_verify'
  created_at          timestamptz not null default now()
);

create index if not exists payments_email_idx on payments(email, created_at desc);
