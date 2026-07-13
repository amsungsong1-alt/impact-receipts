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
    """Increment free_checks_used by 1."""
    if not email:
        return
    try:
        c = _get_client()
        if not c:
            return
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
