-- 0054_auth_email_revoke_anon.sql
-- 0053's `revoke execute on function public.auth_email() from public;` did
-- not actually remove anon's access -- verified directly via
-- has_function_privilege('anon', 'public.auth_email()', 'EXECUTE') still
-- returning true immediately after that migration applied, not just an
-- advisor-cache artifact. Reason: Supabase provisions new functions in the
-- public schema with EXECUTE granted directly to anon/authenticated/
-- service_role as part of its own default-privileges setup, independent of
-- (and in addition to) the standard Postgres "grant to PUBLIC on create"
-- behavior -- revoking from PUBLIC alone doesn't touch a separate direct
-- grant. The fix that actually worked for refresh_customer_profiles (0052)
-- named anon/authenticated explicitly; this does the same for auth_email(),
-- and should be the template for any future function-privilege tightening
-- in this schema -- always revoke from the named roles directly, never
-- rely on a PUBLIC-only revoke.
revoke execute on function public.auth_email() from anon, authenticated;
grant execute on function public.auth_email() to authenticated;
