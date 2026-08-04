-- 0048_rls_wa_conversations.sql
-- Laudon Ch.8 hardening, tier 6c (wa_conversations).
--
-- INSERT is left permissive for both anon and authenticated, matching
-- today's actual behavior with RLS off: utils.db.log_wa_event() logs
-- inbound/outbound WhatsApp messages and may run without a Streamlit
-- session at all -- so enabling this table's RLS is safe to apply today,
-- unlike 0046/0047.
--
-- The DELETE policy is forward-looking, same caveat as 0046/0047: DO NOT
-- rely on it being enforced until utils.db.delete_wa_conversations() (used
-- by the account "erase my history" purge flow) is routed through a
-- per-user Supabase Auth JWT -- it currently queries via the plain anon-key
-- client, which carries no auth.uid(), so this policy would silently no-op
-- that delete today rather than erasing the rows the user asked to erase.
alter table wa_conversations enable row level security;

create policy wa_conversations_insert_all on wa_conversations
  for insert to authenticated, anon with check (true);

create policy wa_conversations_owner_delete on wa_conversations
  for delete to authenticated
  using (user_email = auth_email());
