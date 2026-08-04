-- 0039_auth_email_function.sql
-- Maps the calling request's auth.uid() (set by PostgREST from the JWT
-- utils/supabase_auth.py mints for a user after this app's own OTP check
-- succeeds) to the app's real tenant key, users.email. RLS policies added in
-- 0041+ call this inside USING/WITH CHECK instead of each of the ~22
-- tenant-scoped tables needing its own auth_user_id column -- one function,
-- one place to get the mapping right.
--
-- security definer + a pinned search_path: without both, this function would
-- run with the calling (possibly very restricted) role's own grants and
-- could be search-path-hijacked by a same-named object in another schema.
-- Its owner (the migration-running role) can read `users` regardless of RLS
-- on that table, so this keeps working even after 0043 enables RLS on users
-- itself -- do NOT add `force row level security` to `users`, or this breaks.
create or replace function auth_email() returns text
language sql stable security definer set search_path = public
as $$
  select email from users where auth_user_id = auth.uid()
$$;

grant execute on function auth_email() to authenticated;
