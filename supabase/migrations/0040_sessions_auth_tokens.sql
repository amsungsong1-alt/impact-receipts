-- 0040_sessions_auth_tokens.sql
-- Storage for the Supabase Auth session minted alongside this app's own
-- session token (see utils/supabase_auth.py, utils/auth.py::attach_auth_session).
-- Unlike sessions.token_hash (a SHA-256 hash -- useless to a leaker without
-- the raw value), these two columns must be presentable in raw form to
-- PostgREST/GoTrue, so a database dump would otherwise hand out live
-- authenticated sessions directly. The application encrypts both columns
-- with utils/crypto.py's Fernet key (AUDIT_ENCRYPTION_KEY) before writing --
-- this migration only widens the schema; it does not encrypt anything
-- itself, same convention as 0011_encrypt_audit_columns.sql.
alter table sessions
  add column if not exists auth_access_token text,
  add column if not exists auth_refresh_token text,
  add column if not exists auth_access_token_expires_at timestamptz;
