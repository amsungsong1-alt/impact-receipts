"""
utils/metering.py — centralized "can this account do X" usage-access checks.

Replaces ~7 call sites in app.py that each independently re-derived
is_paid/checks_used/allowed from utils/db.py's get_user()/is_still_paid(),
with slightly different local variable names -- and, in three cases, a bug
where the gate read a session-state key nothing in the app ever wrote,
silently making it always pass regardless of plan.

No Streamlit import -- same UI-free discipline as evaluator.py/diagnostics.py.
All functions degrade gracefully (utils/db.py's get_user()/increment_checks()
already never raise), matching the rest of this codebase's conventions.
"""
from __future__ import annotations

from utils.db import get_user, is_still_paid, increment_checks

FREE_CHECKS_LIMIT = 3  # free manual checks per account, lifetime (no reset)


def check_access(email: str) -> dict:
    """One get_user() round trip. Returns the single shape every gate should
    read instead of re-deriving is_paid/checks_used/allowed independently:
    {"is_paid": bool, "plan": str, "checks_used": int,
     "checks_remaining": int, "allowed": bool}.
    allowed = is_paid or checks_used < FREE_CHECKS_LIMIT. No email -> allowed=False.
    """
    if not email:
        return {"is_paid": False, "plan": "free", "checks_used": 0,
                "checks_remaining": 0, "allowed": False}
    user = get_user(email)
    is_paid = is_still_paid(user)
    checks_used = (user or {}).get("free_checks_used", 0)
    plan = (user or {}).get("plan") or "free"
    return {
        "is_paid": is_paid,
        "plan": plan,
        "checks_used": checks_used,
        "checks_remaining": max(0, FREE_CHECKS_LIMIT - checks_used),
        "allowed": is_paid or checks_used < FREE_CHECKS_LIMIT,
    }


def record_check(email: str) -> None:
    """Centralized replacement for db.increment_checks() at every call site --
    no-ops for a paid account internally, so callers don't need their own
    separate 'if not paid' guard (removing a class of bug where a newly
    gated feature forgets it)."""
    if not email:
        return
    if is_still_paid(get_user(email)):
        return
    increment_checks(email)
