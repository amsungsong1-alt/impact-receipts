-- 0018_stripe_and_currency_fields.sql
-- Multi-currency pricing/ROI internationalization. The Paystack merchant
-- account is Ghana-only (GHS), so real charges in NGN/KES/ZAR are never
-- attempted -- those three fall back to a GHS charge at checkout, shown
-- with a converted-price disclaimer. USD/GBP/EUR route to Stripe instead.
--
-- preferred_currency persists a signed-in user's currency choice across
-- devices/sessions (session_state/query-param alone don't survive a
-- device switch). payments.currency (0004_payments.sql) already exists
-- and keeps recording what was ACTUALLY charged (always GHS for the
-- Paystack path, real currency for the Stripe path); the new
-- displayed_currency records what the user was BROWSING in at purchase
-- time -- the two differ for NGN/KES/ZAR GHS-fallback charges.
alter table users add column if not exists stripe_customer_id text;
alter table users add column if not exists stripe_subscription_id text;
alter table users add column if not exists preferred_currency text;
alter table payments add column if not exists displayed_currency text;
