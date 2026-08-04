-- 0047_rls_payments.sql
-- Laudon Ch.8 hardening, tier 6b (payments).
--
-- *** Same caveat as 0046_rls_users.sql: DO NOT APPLY until
-- utils.db.get_payment_history() is routed through a per-user Supabase Auth
-- JWT -- it currently queries via the plain anon-key client, which carries
-- no auth.uid(), so this policy would return zero rows for everyone's
-- billing history page today. ***
--
-- Payments are only ever written by supabase/functions/paystack-webhook
-- (service-role key, bypasses RLS automatically by platform design -- no
-- INSERT/UPDATE policy needed for that path). The only anon-key access is
-- utils.db.get_payment_history(), a read of the caller's own rows for the
-- billing settings page.
alter table payments enable row level security;

create policy payments_owner_select on payments
  for select to authenticated
  using (email = auth_email());
