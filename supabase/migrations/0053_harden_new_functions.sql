-- 0053_harden_new_functions.sql
-- Follow-up fix for two things Supabase's own advisor caught immediately
-- after applying 0038-0052/0051 (2026-08-03) that this pass's own new code
-- introduced:
--
-- 1. access_log_set_hash_chain() (0051) had no pinned search_path -- the
--    same function_search_path_mutable class of finding 0052 fixed for two
--    PRE-EXISTING functions, just missed on this NEW one written in the
--    same pass. Same fix, same reasoning.
--
-- 2. refresh_customer_profiles() (0052's revoke) is STILL flagged as
--    executable by anon/authenticated after that migration's explicit
--    `revoke execute ... from anon, authenticated`. Reason: Postgres grants
--    EXECUTE on a newly created function to the PUBLIC pseudo-role by
--    default, and every role (including anon/authenticated) is implicitly
--    a member of PUBLIC -- revoking from the two named roles directly does
--    nothing if the grant is actually coming from their PUBLIC membership.
--    `revoke ... from public` is the statement that actually closes this.
--    Re-verified against the live advisor after this migration, not just
--    assumed fixed.
--
-- Also tightens auth_email() (0039) the same way: it only ever needs to be
-- called by `authenticated` (RLS policies call it internally; a direct
-- authenticated caller gets back only their own email, not a leak) -- anon
-- has no auth.uid() and would only ever get NULL back, so there's no
-- functional loss in closing this, only removing unnecessary public surface.
alter function public.access_log_set_hash_chain() set search_path = public;

revoke execute on function public.refresh_customer_profiles() from public;
revoke execute on function public.auth_email() from public;
grant execute on function public.auth_email() to authenticated;
