"""
utils/auth.py — magic-link login tokens + durable session tokens.

Two distinct token types, both stored only as a sha256 hash (the raw value is
returned once, at issuance/generation, and never persisted):

  - login_tokens: single-use, ~20-minute magic-link tokens (see migration
    0002_login_tokens.sql). Verifying is non-mutating (safe for a corporate
    email scanner's pre-fetch); redeeming is mutating and single-use, and
    should only be called from an explicit user confirm-click.
  - sessions: long-lived (~60-day, slides forward on use) tokens mirrored into
    the app URL as ?session=... so a returning visitor is silently
    re-authenticated without retyping their email (see 0003_sessions.sql).

All functions degrade gracefully on DB failure (never crash the app), matching
utils/db.py's convention. Shares utils/db.py's cached Supabase client rather
than opening a second connection.
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from utils.db import _get_client, upsert_user

LOGIN_TOKEN_TTL_MINUTES = 20
SESSION_TOKEN_TTL_DAYS = 60
SESSION_REFRESH_THRESHOLD_HOURS = 24  # don't write an expiry extension more often than this

_last_token_error: str = ""


def last_token_error() -> str:
    """Reason the most recent generate_magic_link_token()/issue_session_token()
    call returned "" -- same last-error-string pattern as
    utils.paystack.last_payment_error()."""
    return _last_token_error


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Magic-link login tokens
# ---------------------------------------------------------------------------

def generate_magic_link_token(email: str) -> str:
    """Create a login_tokens row; returns the raw token (email it, never store it).

    login_tokens.email is a foreign key to users(email) (see
    0002_login_tokens.sql), so a brand-new email that has never completed
    login before has no users row yet -- upsert_user() first ensures one
    exists, the same way _complete_email_login() already does before
    issue_session_token(). Without this, the INSERT below fails its FK
    constraint and silently returns "" (caught by the except below), which
    is exactly the "Could not create a login link" bug this fixes.
    """
    global _last_token_error
    _last_token_error = ""
    if not email:
        _last_token_error = "No email provided."
        return ""
    upsert_user(email)
    raw = secrets.token_urlsafe(32)
    try:
        c = _get_client()
        if not c:
            _last_token_error = "No Supabase client (SUPABASE_URL/SUPABASE_ANON_KEY not configured, or connection failed)."
            return ""
        expires_at = (_now() + timedelta(minutes=LOGIN_TOKEN_TTL_MINUTES)).isoformat()
        c.table("login_tokens").insert({
            "token_hash": _hash_token(raw),
            "email": email,
            "expires_at": expires_at,
        }).execute()
        return raw
    except Exception as exc:
        _last_token_error = f"{type(exc).__name__}: {exc}"
        return ""


def verify_magic_link_token(raw_token: str) -> str | None:
    """Non-mutating check — safe to call from a bare page load (e.g. an email
    security scanner pre-fetching the link) since it never marks the token used."""
    if not raw_token:
        return None
    try:
        c = _get_client()
        if not c:
            return None
        res = (c.table("login_tokens").select("*")
               .eq("token_hash", _hash_token(raw_token)).execute())
        row = res.data[0] if res.data else None
        if not row or row.get("redeemed_at"):
            return None
        expires = _parse_ts(row.get("expires_at"))
        if not expires or expires < _now():
            return None
        return row.get("email")
    except Exception:
        return None


def redeem_magic_link_token(raw_token: str) -> str | None:
    """Mutating, single-use. Re-validates, then atomically marks the token
    redeemed via an UPDATE scoped to redeemed_at IS NULL, so a concurrent
    double-redeem (e.g. two tabs opening the same link) can't both succeed.
    Only call this from an explicit user confirm-click, never from a bare
    page load — verify_magic_link_token above is for that."""
    email = verify_magic_link_token(raw_token)
    if not email:
        return None
    try:
        c = _get_client()
        if not c:
            return None
        res = (c.table("login_tokens")
               .update({"redeemed_at": _now().isoformat()})
               .eq("token_hash", _hash_token(raw_token))
               .is_("redeemed_at", "null")
               .execute())
        if not res.data:
            return None  # lost the race to a concurrent redeem
        return email
    except Exception:
        return None


def send_login_email(email: str, app_base_url: str) -> tuple[bool, str, str]:
    """Generate a magic-link token + a 6-digit code, send both in one email.

    Returns (success, error_message, code) — a 3-tuple, not the 2-tuple
    convention used elsewhere in this codebase, because the caller (app.py's
    inline email gate) needs the code to store in st.session_state for its own
    comparison later. This module owns only the link-token lifecycle; the
    code-comparison flow stays exactly where it already lives, in app.py.
    """
    from utils import email_otp
    if not email:
        return False, "No email provided.", ""
    raw_token = generate_magic_link_token(email)
    if not raw_token:
        _detail = last_token_error()
        return False, f"Could not create a login link. Please try again.{' (' + _detail + ')' if _detail else ''}", ""
    code = email_otp.generate_otp()
    sep = "&" if "?" in app_base_url else "?"
    link_url = f"{app_base_url}{sep}login_token={raw_token}"
    ok, err = email_otp.send_login_email(email, link_url, code)
    return ok, err, code


# ---------------------------------------------------------------------------
# Durable session tokens
# ---------------------------------------------------------------------------

def issue_session_token(email: str, user_agent: str = "") -> str:
    """Create a sessions row; returns the raw token (mirror into ?session=...).

    sessions.email is a foreign key to users(email), same as login_tokens --
    upsert_user() first so this doesn't depend on every caller remembering
    to have done that already (see generate_magic_link_token's docstring).
    """
    global _last_token_error
    _last_token_error = ""
    if not email:
        _last_token_error = "No email provided."
        return ""
    upsert_user(email)
    raw = secrets.token_urlsafe(32)
    try:
        c = _get_client()
        if not c:
            _last_token_error = "No Supabase client (SUPABASE_URL/SUPABASE_ANON_KEY not configured, or connection failed)."
            return ""
        expires_at = (_now() + timedelta(days=SESSION_TOKEN_TTL_DAYS)).isoformat()
        c.table("sessions").insert({
            "token_hash": _hash_token(raw),
            "email": email,
            "expires_at": expires_at,
            "user_agent": (user_agent or "")[:200],
        }).execute()
        return raw
    except Exception as exc:
        _last_token_error = f"{type(exc).__name__}: {exc}"
        return ""


def verify_session_token(raw_token: str) -> str | None:
    """Returns the email for a valid, non-revoked, non-expired session token.

    Opportunistically slides expires_at/last_seen_at forward, but only writes
    if more than SESSION_REFRESH_THRESHOLD_HOURS has passed since last_seen_at
    — Streamlit reruns on every widget interaction, so writing unconditionally
    here would hammer the DB on every click a logged-in user makes.
    """
    if not raw_token:
        return None
    try:
        c = _get_client()
        if not c:
            return None
        token_hash = _hash_token(raw_token)
        res = c.table("sessions").select("*").eq("token_hash", token_hash).execute()
        row = res.data[0] if res.data else None
        if not row or row.get("revoked_at"):
            return None
        expires = _parse_ts(row.get("expires_at"))
        if not expires or expires < _now():
            return None
        last_seen = _parse_ts(row.get("last_seen_at"))
        stale = not last_seen or (_now() - last_seen) > timedelta(hours=SESSION_REFRESH_THRESHOLD_HOURS)
        if stale:
            try:
                new_expires = (_now() + timedelta(days=SESSION_TOKEN_TTL_DAYS)).isoformat()
                c.table("sessions").update({
                    "last_seen_at": _now().isoformat(),
                    "expires_at": new_expires,
                }).eq("token_hash", token_hash).execute()
            except Exception:
                pass  # extension is best-effort; a failed extension shouldn't log the user out
        return row.get("email")
    except Exception:
        return None


def list_sessions(email: str) -> list[dict]:
    """Non-revoked, non-expired sessions for the billing page's device list."""
    if not email:
        return []
    try:
        c = _get_client()
        if not c:
            return []
        res = (c.table("sessions")
               .select("token_hash,created_at,last_seen_at,expires_at,user_agent")
               .eq("email", email).is_("revoked_at", "null")
               .order("last_seen_at", desc=True).execute())
        now = _now()
        return [r for r in (res.data or []) if (_parse_ts(r.get("expires_at")) or now) > now]
    except Exception:
        return []


def revoke_session(token_hash: str, email: str) -> None:
    """'Sign out this device' — scoped by both token_hash and email so a user
    can only ever revoke their own sessions."""
    if not token_hash or not email:
        return
    try:
        c = _get_client()
        if not c:
            return
        c.table("sessions").update({"revoked_at": _now().isoformat()}) \
            .eq("token_hash", token_hash).eq("email", email).execute()
    except Exception:
        pass


def revoke_all_sessions(email: str) -> None:
    """'Sign out everywhere.'"""
    if not email:
        return
    try:
        c = _get_client()
        if not c:
            return
        c.table("sessions").update({"revoked_at": _now().isoformat()}) \
            .eq("email", email).is_("revoked_at", "null").execute()
    except Exception:
        pass
