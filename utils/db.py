"""
Supabase persistence layer — users table + examples table.
All functions degrade gracefully on DB failure (never crash the app).

Schema (users/login_tokens/sessions/payments columns and tables, plus the
increment_free_checks RPC used by increment_checks below) is tracked in
supabase/migrations/ -- apply new migration files in order (`supabase db push`,
or paste each file's SQL into the Supabase SQL editor) rather than hand-writing
ALTER TABLE statements against a running project.
"""
from __future__ import annotations
import os
from datetime import date, datetime, timedelta, timezone

_client = None

def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        import streamlit as st
        url  = st.secrets.get("SUPABASE_URL")  or os.environ.get("SUPABASE_URL", "")
        key  = st.secrets.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    except Exception:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
    except Exception:
        _client = None
    return _client


_service_client = None


def _get_service_client():
    """Service-role client -- bypasses RLS and every GRANT/REVOKE check by
    Supabase platform design (same key utils/supabase_auth.py uses to mint
    Auth sessions -- SUPABASE_SERVICE_ROLE_KEY). Use ONLY for genuinely
    system/admin operations that are not "the logged-in user acting on their
    own row" -- e.g. the admin CRM dashboard's list_all_users() (reads every
    account) or an unsubscribe-by-token lookup (no logged-in session at all,
    identified by token instead of by the caller's own identity). Never use
    this as a fallback for an ordinary user request just because a JWT wasn't
    available -- that would make RLS provide no protection at all for that
    call site. Falls back to _get_client() (today's plain anon-key behavior)
    if SUPABASE_SERVICE_ROLE_KEY isn't configured yet, so this is additive
    and never a regression for an environment that hasn't set it."""
    global _service_client
    if _service_client is not None:
        return _service_client
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    except Exception:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _service_client = create_client(url, key)
    except Exception:
        _service_client = None
    return _service_client


def _get_authed_client():
    """Session-scoped client carrying the CURRENT Streamlit session's minted
    Supabase Auth access token (see utils/supabase_auth.py,
    utils/auth.py::ensure_auth_session, app.py's login/session-restore
    paths), so auth.uid() resolves and RLS's authenticated-role policies
    (0046_rls_users.sql, 0047_rls_payments.sql, 0048's owner-delete policy)
    actually apply to this call instead of being evaluated with no identity
    at all.

    Falls back to _get_client() (the plain anon-key client, today's
    behavior) if no token is available -- e.g. Supabase Auth isn't
    configured in this environment, or this particular session hasn't
    completed the mint/refresh step yet. That fallback is a correctness
    no-op everywhere RLS isn't enforced yet, and a graceful "can't see my
    own data this one request" degradation (never a crash, never someone
    else's data) anywhere it is.

    Deliberately NOT cached across calls the way _get_client()/
    _get_service_client() are -- caching a per-user token on a module
    global would leak one Streamlit session's identity into another
    concurrent session's request, since this module serves every browser
    session from one process (see utils/supabase_auth.py's own docstring
    for the same warning)."""
    try:
        import streamlit as st
        token = st.session_state.get("_supabase_auth_access_token")
    except Exception:
        token = None
    if token:
        try:
            from utils.supabase_auth import build_session_scoped_client
            client = build_session_scoped_client(token)
            if client:
                return client
        except Exception:
            pass
    return _get_client()


def get_user(email: str) -> dict | None:
    """Return the CALLER's OWN user row (or None), via the session-scoped
    authenticated client when one is available -- see _get_authed_client().
    This is the "logged-in user reading their own data" path; do not use
    this for a system-level/pre-auth check (e.g. "does this email already
    have an account, before this login attempt has minted anything yet") --
    use get_user_privileged() for that instead, or it will incorrectly see
    nothing once RLS is enforced on users."""
    if not email:
        return None
    try:
        c = _get_authed_client()
        if not c:
            return None
        res = c.table("users").select("*").eq("email", email).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def get_user_privileged(email: str) -> dict | None:
    """Same shape as get_user(), but via the service-role client -- for
    system-level checks that must work correctly regardless of whether a
    per-user Supabase Auth session has been minted yet (e.g. upsert_user()'s
    own existence check, and _complete_email_login()'s new-vs-returning-user
    check, both of which run before this session has necessarily minted
    anything). Never use this in an ordinary "show the logged-in user their
    own data" call site in place of get_user() -- that would silently
    bypass RLS's defense-in-depth for no reason."""
    if not email:
        return None
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return None
        res = c.table("users").select("*").eq("email", email).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def link_auth_user_id(email: str, auth_user_id: str) -> None:
    """One-time-per-mint backfill: writes the auth.users.id minted for this
    email (utils/supabase_auth.py::mint_auth_session) onto
    users.auth_user_id (0038_users_auth_link.sql), which is what
    auth_email() (0039) resolves auth.uid() through for every RLS policy
    keyed on it. Without this call, auth_email() returns NULL for every
    account forever, and 0046/0047's policies never match anyone -- this is
    not an optional convenience, it's the missing link the whole RLS design
    depends on.

    Must use the service-role client, not the session-scoped one: at the
    moment this needs to run, auth_user_id isn't set yet, so auth_email()
    can't resolve yet either -- the authenticated-role UPDATE policy on
    users couldn't be satisfied even by the caller's own valid JWT.
    Idempotent -- safe to call on every login, not just the first."""
    if not email or not auth_user_id:
        return
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return
        c.table("users").update({"auth_user_id": auth_user_id}).eq("email", email).execute()
    except Exception:
        pass


def upsert_user(email: str) -> dict | None:
    """Create user if not exists; return row.

    Uses the service-role client (falling back to the plain anon client if
    service-role isn't configured), not the session-scoped authenticated
    client: this is called from utils/auth.py's token-generation functions
    (generate_magic_link_token/issue_session_token), which run BEFORE this
    login attempt's OTP check has even succeeded -- there is no per-user JWT
    to use yet at that point, and treating this as anything other than a
    system-level "ensure this row exists" operation would make the
    existence check below always report "new" for a returning user once RLS
    is enforced (anon/no-JWT can't SELECT), attempting a duplicate INSERT
    every time."""
    if not email:
        return None
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return None
        existing = get_user_privileged(email)
        if existing:
            return existing
        c.table("users").insert({"email": email, "free_checks_used": 0,
                                  "is_paid": False}).execute()
        return get_user_privileged(email)
    except Exception:
        return None


def increment_checks(email: str) -> None:
    """Increment free_checks_used by 1, atomically.

    Tries the increment_free_checks Postgres RPC first (see
    supabase/migrations/0001_users_billing_columns.sql), which does the
    read-modify-write as a single statement and is safe under concurrent
    calls. Falls back to the previous read-then-upsert behaviour if the RPC
    isn't available yet (e.g. the migration hasn't been applied in some
    environment) -- never crashes, only un-atomically races until migrated.

    Uses the plain anon-key client for the RPC path deliberately --
    increment_free_checks is a SECURITY DEFINER function explicitly granted
    to anon (0052_harden_function_grants.sql), the app's normal calling
    pattern for this counter. The upsert fallback path, though, writes
    free_checks_used directly -- a column authenticated is NOT granted
    (0046_rls_users.sql only grants profile fields) -- so that path needs
    the service-role client, same reasoning as mark_paid/set_user_plan
    below, not the session-scoped authenticated client.
    """
    if not email:
        return
    try:
        c = _get_client()
        if not c:
            return
        try:
            c.rpc("increment_free_checks", {"p_email": email}).execute()
            return
        except Exception:
            pass  # RPC not available yet -- fall back below
        privileged = _get_service_client() or c
        user = get_user_privileged(email)
        current = (user or {}).get("free_checks_used", 0)
        privileged.table("users").upsert({"email": email, "free_checks_used": current + 1}).execute()
    except Exception:
        pass


def mark_paid(email: str, days: int = 30) -> None:
    """Set is_paid=True, paid_until = today + days.

    Uses the service-role client: is_paid/paid_until are not in
    authenticated's column-UPDATE grant (0046_rls_users.sql) by design --
    a user must never be able to self-grant paid status via their own JWT,
    only the app's own payment-verification code path (here, and the
    Paystack webhook, which already uses service-role) may write it."""
    if not email:
        return
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return
        until = (date.today() + timedelta(days=days)).isoformat()
        c.table("users").upsert({"email": email, "is_paid": True,
                                  "paid_until": until}).execute()
    except Exception:
        pass


def set_user_plan(email: str, plan: str) -> None:
    """Upsert users.plan. Values: 'free' | 'professional' | 'agency' --
    anything else is a no-op. Mirrors labelToTier() in
    supabase/functions/paystack-webhook/index.ts, so the two Python in-app
    payment-success paths (app.py's _complete_email_login and the
    redirect-verify handler in main()) persist plan exactly like the webhook
    does. Callers must not pass "per_use" or any other Paystack plan label
    here -- a one-off payment must never change the account's subscription
    tier; derive the tier from the label yourself and simply don't call this
    function for "per_use", rather than relying on this function to ignore it.

    Uses the service-role client, same reasoning as mark_paid() -- plan is
    not in authenticated's column-UPDATE grant."""
    if not email or plan not in ("free", "professional", "agency"):
        return
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return
        c.table("users").upsert({"email": email, "plan": plan}).execute()
    except Exception:
        pass


def set_user_totp(email: str, encrypted_secret: str, enabled: bool) -> None:
    """Store a user's TOTP secret (already Fernet-encrypted by the caller --
    see utils/crypto.py -- never pass a plaintext secret here) and enrollment
    flag (Laudon Ch.8, C3 -- mandatory 2FA for admin/owner). This function
    only writes to users; it has no opinion on WHO may call it -- app.py's
    admin-gate UI is the enforcement point, same separation of concerns as
    every other utils/db.py setter here.

    Uses the service-role client: totp_secret/totp_enabled are not in
    authenticated's column-UPDATE grant (0046_rls_users.sql) -- the app
    itself verifies the TOTP code server-side before ever calling this, so
    this is the app asserting a fact, not the user editing their own row
    directly."""
    if not email:
        return
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return
        c.table("users").update({
            "totp_secret": encrypted_secret, "totp_enabled": bool(enabled),
        }).eq("email", email).execute()
    except Exception:
        pass


# Same two org-type strings app.py's own Screen 1 org-type selectbox uses --
# concessional pricing is scoped to CBO/Government for now (see
# supabase/migrations/0056's header for why National NGO's already-modeled
# 30%-off tier is deliberately deferred, not overlooked).
CONCESSIONAL_ORG_TYPES = (
    "Community-Based Organisation (CBO)", "Government department / local authority",
)


def request_concessional_pricing(email: str, org_type: str, note: str = "") -> bool:
    """User-initiated (Billing page 'Request discounted pricing' form), but
    still routed through the service-role client like set_user_totp() above:
    concessional_status/concessional_org_type/concessional_note/
    concessional_requested_at are deliberately NOT in authenticated's
    column-UPDATE grant (0056_users_concessional_pricing.sql) -- an
    authenticated-client write would simply fail. app.py's form validates
    org_type against CONCESSIONAL_ORG_TYPES server-side before calling this,
    so this is the app recording a user-initiated request as a fact, not
    the user editing their own row directly.

    No-ops (returns False) on an invalid org_type or an account that
    already has a request on file (status != 'none') -- callers should
    check get_user(email)['concessional_status'] first to show the right
    UI state, not rely on this to silently correct a stale render."""
    if not email or org_type not in CONCESSIONAL_ORG_TYPES:
        return False
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return False
        c.table("users").update({
            "concessional_status": "requested",
            "concessional_org_type": org_type,
            "concessional_note": (note or "").strip()[:500],
            "concessional_requested_at": datetime.now(timezone.utc).isoformat(),
        }).eq("email", email).eq("concessional_status", "none").execute()
        return True
    except Exception:
        return False


def set_user_concessional_status(email: str, status: str, approved_by: str = "") -> bool:
    """Admin approve/deny action (app.py's ?admin=1 dashboard is the only
    caller) -- the sole way concessional_status ever moves to 'approved' or
    'denied'. Service-role client, same reasoning as set_user_totp() above.
    approved_by is the acting admin's own email, a lightweight
    accountability trail, not an authorization check itself (the admin RBAC
    gate at the call site is what actually authorizes this)."""
    if not email or status not in ("approved", "denied"):
        return False
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return False
        c.table("users").update({
            "concessional_status": status,
            "concessional_approved_at": datetime.now(timezone.utc).isoformat(),
            "concessional_approved_by": approved_by or "",
        }).eq("email", email).execute()
        return True
    except Exception:
        return False


def list_pending_concessional_requests() -> list[dict]:
    """Every account with concessional_status='requested', for the
    ?admin=1 dashboard's approval queue. Service-role client (reads across
    every account, same reasoning as list_all_users() above -- there's no
    single "owner" row here). [] on any failure, same convention as every
    other admin-facing list function in this file."""
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return []
        res = c.table("users").select(
            "email, concessional_org_type, concessional_note, concessional_requested_at"
        ).eq("concessional_status", "requested").execute()
        return res.data or []
    except Exception:
        return []


# Duplicated (not imported from app.py) to avoid a utils -> app import cycle --
# app.py's ACCOUNT_SECTOR_OPTIONS is the UI-facing copy of this same list; keep
# both in sync by hand if it ever changes.
ACCOUNT_SECTOR_OPTIONS = ("Health", "Agriculture", "Education", "WASH", "Governance", "Other")


def set_user_profile(email: str, account_sector: str, primary_donors: list, country: str) -> None:
    """Upsert the personalization profile captured once per account (see
    supabase/migrations/0017). account_sector must be one of
    ACCOUNT_SECTOR_OPTIONS -- an invalid value is a no-op (nothing is stored)
    rather than persisting garbage that later personalization code would have
    to defend against. primary_donors/country are stored as-is (already
    constrained to a fixed list / free text respectively at the UI layer)."""
    if not email or account_sector not in ACCOUNT_SECTOR_OPTIONS:
        return
    try:
        c = _get_authed_client()
        if not c:
            return
        c.table("users").upsert({
            "email": email,
            "account_sector": account_sector,
            "primary_donors": list(primary_donors or []),
            "country": (country or "").strip(),
            "profile_completed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass


def set_user_currency(email: str, currency: str) -> None:
    """Upsert users.preferred_currency (see supabase/migrations/0018) so a
    signed-in user's currency choice survives a device switch, not just a
    browser session/query-param. currency must be one of
    utils.exchange_rates.SUPPORTED_CURRENCIES -- an invalid value is a
    no-op."""
    from utils.exchange_rates import SUPPORTED_CURRENCIES
    if not email or currency not in SUPPORTED_CURRENCIES:
        return
    try:
        c = _get_authed_client()
        if not c:
            return
        c.table("users").upsert({"email": email, "preferred_currency": currency}).execute()
    except Exception:
        pass


def skip_profile_capture(email: str) -> None:
    """Permanently dismisses the profile-capture prompt without storing any
    profile fields -- personalization stays at today's generic defaults for
    this account, matching the "gracefully fall back" requirement."""
    if not email:
        return
    try:
        c = _get_authed_client()
        if not c:
            return
        c.table("users").upsert({"email": email, "profile_skipped": True}).execute()
    except Exception:
        pass


def is_still_paid(user: dict | None) -> bool:
    """Return True if user is paid AND paid_until is in the future (or None)."""
    if not user or not user.get("is_paid"):
        return False
    until = user.get("paid_until")
    if not until:
        return True  # no expiry set → paid
    try:
        return date.fromisoformat(str(until)) >= date.today()
    except Exception:
        return True


def save_user_draft(email: str, draft_json: str) -> None:
    """Persist the user's form draft to Supabase so it survives page refresh.

    Requires a `draft_json` TEXT column on the `users` table.
    SQL migration (run once in Supabase SQL editor):
        ALTER TABLE users ADD COLUMN IF NOT EXISTS draft_json TEXT;
    Degrades gracefully if the column doesn't exist yet.
    """
    if not email or not draft_json:
        return
    try:
        c = _get_authed_client()
        if not c:
            return
        # Limit to ~50 KB to stay within Supabase row limits
        c.table("users").upsert(
            {"email": email, "draft_json": draft_json[:50000]},
            on_conflict="email",
        ).execute()
    except Exception:
        pass


def load_user_draft(email: str) -> str | None:
    """Retrieve the user's last saved draft JSON from Supabase, or None."""
    if not email:
        return None
    try:
        c = _get_authed_client()
        if not c:
            return None
        res = c.table("users").select("draft_json").eq("email", email).execute()
        if res.data:
            return res.data[0].get("draft_json") or None
        return None
    except Exception:
        return None


def clear_user_draft(email: str) -> None:
    """Clear saved draft after user successfully scores (so stale data isn't restored)."""
    if not email:
        return
    try:
        c = _get_authed_client()
        if not c:
            return
        c.table("users").upsert(
            {"email": email, "draft_json": None},
            on_conflict="email",
        ).execute()
    except Exception:
        pass


def log_wa_event(
    context_id: str,
    user_email: str,
    direction: str,
    phone: str,
    body: str,
    success: bool,
) -> None:
    """
    Write a WhatsApp interaction row to the `wa_conversations` table.

    Required table (run once in Supabase SQL editor):
        create table if not exists wa_conversations (
          id          bigserial primary key,
          created_at  timestamptz default now(),
          context_id  text,
          user_email  text,
          direction   text,
          phone       text,
          body        text,
          success     boolean
        );

    Degrades gracefully — never raises an exception.
    """
    try:
        c = _get_client()
        if not c:
            return
        c.table("wa_conversations").insert({
            "context_id": context_id or "",
            "user_email": user_email or "",
            "direction":  direction or "",
            "phone":      phone or "",
            "body":       (body or "")[:500],
            "success":    bool(success),
        }).execute()
    except Exception:
        pass


def delete_wa_conversations(email: str) -> None:
    """Deletes wa_conversations rows for email -- part of the "erase my
    history" data-deletion feature (see utils/audits.py's
    purge_account_audit_content). wa_conversations has no foreign key to
    users at all (it's a plain user_email text column, no `references`
    clause -- see 0000_base_schema.sql), so nothing else -- no cascade --
    will ever remove these rows; this explicit, separately-scoped delete is
    the only thing that does.
    """
    if not email:
        return
    try:
        c = _get_authed_client()
        if not c:
            return
        c.table("wa_conversations").delete().eq("user_email", email).execute()
    except Exception:
        pass


def save_example(field_name: str, sector: str, value: str) -> None:
    """Store an anonymised field example."""
    if not field_name or not value:
        return
    try:
        c = _get_client()
        if not c:
            return
        c.table("examples").insert({
            "field_name": field_name,
            "sector": sector or "Other",
            "value": value[:200],
        }).execute()
    except Exception:
        pass


def get_examples(field_name: str, sector: str, k: int = 5) -> list[str]:
    """Return up to k example values for a field+sector pair."""
    try:
        c = _get_client()
        if not c:
            return []
        res = (c.table("examples")
               .select("value")
               .eq("field_name", field_name)
               .eq("sector", sector or "Other")
               .order("created_at", desc=True)
               .limit(k)
               .execute())
        return [r["value"] for r in (res.data or [])]
    except Exception:
        return []


def get_payment_history(email: str, limit: int = 50) -> list[dict]:
    """Return this account's payment/invoice history (payments table, newest
    first), for the billing settings page. [] on any failure or missing email
    -- the billing page should render an empty state, never crash.

    Uses the session-scoped authenticated client (0047_rls_payments.sql's
    SELECT policy requires auth_email() match) -- this is exactly "the
    logged-in user reading their own data," the case _get_authed_client()
    exists for."""
    if not email:
        return []
    try:
        c = _get_authed_client()
        if not c:
            return []
        res = (c.table("payments")
               .select("*")
               .eq("email", email)
               .order("created_at", desc=True)
               .limit(limit)
               .execute())
        return res.data or []
    except Exception:
        return []


def list_all_users() -> list[dict]:
    """All users' email/plan/is_paid/free_checks_used/created_at/
    subscription_status/marketing_opt_out -- used only by utils.crm.
    build_segments() for the admin CRM dashboard. [] on any failure.

    NOTE: unfiltered/unpaginated -- fine at current account volume, but will
    need .range()-based pagination once the account count grows past a few
    thousand rows (Supabase's REST API caps a single response's row count).

    Reads every account, not just the caller's own row -- uses the
    service-role client (bypasses RLS by design), never the per-user
    auth_email()-scoped path, since there is no single "owner" row here."""
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return []
        res = c.table("users").select(
            "email, plan, is_paid, free_checks_used, created_at, "
            "subscription_status, marketing_opt_out"
        ).execute()
        return res.data or []
    except Exception:
        return []


def set_marketing_opt_out_by_token(token: str) -> bool:
    """Flips marketing_opt_out=true for whichever account owns this
    unsubscribe_token (see supabase/migrations/0013). The caller should show
    the same confirmation message regardless of the return value -- never
    reveal whether a given token matched a real account.

    Identified by token, not by a logged-in session (an unsubscribe link is
    typically opened signed out) -- uses the service-role client (bypasses
    RLS by design), since there is no auth.uid() to key an owner policy off
    here at all."""
    if not token:
        return False
    try:
        c = _get_service_client() or _get_client()
        if not c:
            return False
        res = c.table("users").update({"marketing_opt_out": True}).eq("unsubscribe_token", token).execute()
        return bool(res.data)
    except Exception:
        return False
