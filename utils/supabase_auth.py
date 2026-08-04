"""
utils/supabase_auth.py — mints a real Supabase Auth session (so auth.uid()
resolves) for a user who has already completed this app's own magic-link/
6-digit-OTP verification (see utils/auth.py). This does NOT replace that
verification or change the login UX in any way -- it runs once, invisibly,
right after utils.auth's own check succeeds, purely so the RLS policies added
from supabase/migrations/0041 onward have an auth.uid() to key off (see
0039_auth_email_function.sql).

Two separate Supabase clients are involved, matching the only supported
pattern for a server-owned OTP flow with no browser JS SDK and no password:
  - an admin (service-role) client, used ONLY to call auth.admin.generate_link
  - a throwaway anon client, used ONLY to redeem that link via auth.verify_otp
generate_link also lazily creates the auth.users row on first call for any
email that doesn't have one yet -- existing users get provisioned the next
time they log in, no bulk backfill script required for this step (a bulk
backfill is still useful to shrink the window before RLS is enforced on
audits/payments -- see supabase/migrations/0041+ notes).

Do NOT hand-sign JWTs as an alternative to this: a hand-signed HS256 token
bypasses GoTrue's own session table, can't be revoked via auth.admin.sign_out,
and doesn't participate in refresh-token rotation -- this module always goes
through GoTrue's real endpoints.

Never construct a service-role client for anything other than
generate_link, and never attach a per-user access token to utils.db's shared
module-global client (utils.db._get_client() is cached process-wide, and
Streamlit serves many browser sessions from one process -- mutating that
client's auth header would leak one user's identity into another's
concurrent request). Callers must keep the returned tokens in
st.session_state (via utils.auth.attach_auth_session/get_auth_session), and
build any session-scoped client with build_session_scoped_client() below,
never with utils.db's client.

Degrades gracefully like every other module in this codebase: any failure
(SUPABASE_SERVICE_ROLE_KEY not configured yet, network error, an SDK
response-shape mismatch across supabase-py/gotrue-py versions) returns None
rather than raising. Supabase Auth/RLS is additive -- the app's own
login_tokens/sessions flow keeps working with zero dependency on any of this.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone


def _get_secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(key) or os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def _supabase_url() -> str:
    return _get_secret("SUPABASE_URL")


def _default_expiry() -> int:
    return int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())


_admin_client = None


def _get_admin_client():
    """Cached service-role client. Safe to cache process-globally (unlike a
    per-user client) because the service-role key never carries per-request
    user identity -- every call site must pass the target email/token
    explicitly, so there is nothing for one caller to leak into another's."""
    global _admin_client
    if _admin_client is not None:
        return _admin_client
    url = _supabase_url()
    key = _get_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _admin_client = create_client(url, key)
    except Exception:
        _admin_client = None
    return _admin_client


def _session_dict(session, user) -> dict | None:
    if not session or not user:
        return None
    access_token = getattr(session, "access_token", None)
    refresh_token = getattr(session, "refresh_token", None)
    auth_user_id = getattr(user, "id", None)
    if not access_token or not refresh_token or not auth_user_id:
        return None
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "auth_user_id": auth_user_id,
        "expires_at": getattr(session, "expires_at", None) or _default_expiry(),
    }


def mint_auth_session(email: str) -> dict | None:
    """Mint a real Supabase Auth session for `email`. Returns
    {"access_token", "refresh_token", "auth_user_id", "expires_at" (epoch
    seconds)} on success, or None on any failure -- callers must treat None
    as "Supabase Auth/RLS unavailable for this login," never as a reason to
    fail the login itself, since the app's own session token already
    succeeded before this is ever called."""
    if not email:
        return None
    admin = _get_admin_client()
    if admin is None:
        return None
    url = _supabase_url()
    anon_key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        return None
    try:
        link_resp = admin.auth.admin.generate_link({"type": "magiclink", "email": email})
        props = getattr(link_resp, "properties", None)
        token_hash = getattr(props, "hashed_token", None)
        if not token_hash:
            return None
        from supabase import create_client
        redeemer = create_client(url, anon_key)
        verify_resp = redeemer.auth.verify_otp({"type": "magiclink", "token_hash": token_hash})
        return _session_dict(getattr(verify_resp, "session", None), getattr(verify_resp, "user", None))
    except Exception:
        return None


def refresh_auth_session(refresh_token: str) -> dict | None:
    """Exchange a refresh token for a new access/refresh token pair. Same
    return shape as mint_auth_session(), or None on failure. A None result
    means "keep using the app's own session as-is for this request" -- never
    treat it as a reason to log the user out; Supabase Auth is additive."""
    if not refresh_token:
        return None
    url = _supabase_url()
    anon_key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        return None
    try:
        from supabase import create_client
        client = create_client(url, anon_key)
        resp = client.auth.refresh_session(refresh_token)
        return _session_dict(getattr(resp, "session", None), getattr(resp, "user", None))
    except Exception:
        return None


def build_session_scoped_client(access_token: str):
    """A fresh Supabase client with `access_token` attached to every
    PostgREST request it makes, scoped to exactly one caller's identity.
    Build one per Streamlit session (cache it in st.session_state, never in a
    module global) -- see the module docstring for why reusing utils.db's
    shared client here would be a cross-tenant leak, not a convenience."""
    if not access_token:
        return None
    url = _supabase_url()
    anon_key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        return None
    try:
        from supabase import create_client
        client = create_client(url, anon_key)
        client.postgrest.auth(access_token)
        return client
    except Exception:
        return None
