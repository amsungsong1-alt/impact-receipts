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
from datetime import date, timedelta

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


def get_user(email: str) -> dict | None:
    """Return user row or None (includes free_checks_used, is_paid, paid_until)."""
    if not email:
        return None
    try:
        c = _get_client()
        if not c:
            return None
        res = c.table("users").select("*").eq("email", email).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def upsert_user(email: str) -> dict | None:
    """Create user if not exists; return row."""
    if not email:
        return None
    try:
        c = _get_client()
        if not c:
            return None
        existing = get_user(email)
        if existing:
            return existing
        c.table("users").insert({"email": email, "free_checks_used": 0,
                                  "is_paid": False}).execute()
        return get_user(email)
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
        user = get_user(email)
        current = (user or {}).get("free_checks_used", 0)
        c.table("users").upsert({"email": email, "free_checks_used": current + 1}).execute()
    except Exception:
        pass


def mark_paid(email: str, days: int = 30) -> None:
    """Set is_paid=True, paid_until = today + days."""
    if not email:
        return
    try:
        c = _get_client()
        if not c:
            return
        until = (date.today() + timedelta(days=days)).isoformat()
        c.table("users").upsert({"email": email, "is_paid": True,
                                  "paid_until": until}).execute()
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
        c = _get_client()
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
        c = _get_client()
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
        c = _get_client()
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
        c = _get_client()
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
    -- the billing page should render an empty state, never crash."""
    if not email:
        return []
    try:
        c = _get_client()
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
    thousand rows (Supabase's REST API caps a single response's row count)."""
    try:
        c = _get_client()
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
    reveal whether a given token matched a real account."""
    if not token:
        return False
    try:
        c = _get_client()
        if not c:
            return False
        res = c.table("users").update({"marketing_opt_out": True}).eq("unsubscribe_token", token).execute()
        return bool(res.data)
    except Exception:
        return False
