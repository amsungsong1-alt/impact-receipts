"""
utils/lifecycle_triggers.py — Laudon Ch.9 CRM, C6: deterministic, rule-based
lifecycle triggers. Small in number (TRIGGERS below), each individually
enabled/disabled -- deliberately not a marketing-automation platform.

Detection + logging only. This module never renders UI (that's app.py's
job, via _eligible_lifecycle_triggers(email) calling eligible_triggers()
and app.py's per-trigger _render_trigger_*() functions acting on the
result) and never sends anything itself except one plain
backend call for org_emergent_detected: notify_founder() (server-
initiated, no Streamlit dependency, safe to call from here). The other
triggers' user-facing actions (banners, the testimonial ask, the payment-
recovery message) are rendered by app.py.

A 5th trigger, at_risk_reengagement, is NOT fired from this module at all --
the other 4 fire live during a page load (the affected account is the one
browsing); at_risk_reengagement by definition needs to reach an account that
ISN'T currently visiting, so it's detected and actioned entirely inside the
customer-profile-refresh Edge Function, which inserts into the SAME
lifecycle_triggers_log table via a direct REST call. TRIGGERS still lists it
here (for its cooldown to be documented in one place) even though nothing in
this Python module ever fires it.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, func
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()
_PK = BigInteger().with_variant(Integer, "sqlite")

TRIGGERS = {
    "first_assessment_no_engagement": {"enabled": True, "cooldown_days": 90},
    "org_emergent_detected":          {"enabled": True, "cooldown_days": 30},
    "payment_recovery":               {"enabled": True, "cooldown_days": 3},
    "testimonial_ask":                {"enabled": True, "cooldown_days": 365},
    "at_risk_reengagement":           {"enabled": True, "cooldown_days": 30},  # fired by the Edge Function, not this module
}

# Combined delta_confidence + delta_clarity on a revision that triggers the
# testimonial ask -- a config constant, not buried in eligible_triggers()'s body.
TESTIMONIAL_DELTA_THRESHOLD = 1.5


class LifecycleTriggerLog(Base):
    __tablename__ = "lifecycle_triggers_log"
    id = Column(_PK, primary_key=True)
    email = Column(Text, nullable=False)
    trigger_name = Column(Text, nullable=False)
    fired_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
    # Identical pattern to utils.crm._get_engine().
    global _engine
    if _engine is not None:
        return _engine
    try:
        import streamlit as st
        db_url = st.secrets.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL", "")
    except Exception:
        db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        _engine = create_engine(db_url, pool_pre_ping=True)
    except Exception:
        _engine = None
    return _engine


def is_trigger_enabled(trigger_name: str) -> bool:
    return bool(TRIGGERS.get(trigger_name, {}).get("enabled", False))


def has_fired_recently(email: str, trigger_name: str) -> bool:
    """True if this trigger fired for this account within its configured
    cooldown window. Fails open to True (treat as "already fired, skip")
    on any DB error or missing engine -- better to silently skip a nudge
    than risk spamming one on repeated transient failures."""
    if not email or not trigger_name:
        return True
    engine = _get_engine()
    if not engine:
        return True
    cooldown_days = TRIGGERS.get(trigger_name, {}).get("cooldown_days", 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    try:
        with Session(engine) as session:
            row = (session.query(LifecycleTriggerLog)
                   .filter(LifecycleTriggerLog.email == email,
                           LifecycleTriggerLog.trigger_name == trigger_name,
                           LifecycleTriggerLog.fired_at >= cutoff)
                   .first())
            return row is not None
    except Exception:
        return True


def record_trigger_fired(email: str, trigger_name: str) -> None:
    """Best-effort, insert-only -- never raises."""
    if not email or not trigger_name:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            session.add(LifecycleTriggerLog(email=email, trigger_name=trigger_name))
            session.commit()
    except Exception:
        pass


def eligible_triggers(email: str, profile: dict, segment: str,
                       delta_confidence: float = 0.0, delta_clarity: float = 0.0) -> list[str]:
    """Returns the trigger names currently eligible to fire for this account,
    given already-computed inputs (a customer_profiles row, its behavioural
    segment, and an optional just-computed revision delta). Each candidate
    costs one has_fired_recently() DB read; never raises -- an unavailable
    DB makes every trigger look "already fired" (fail-open), so this
    degrades to "nothing fires," never a crash or a spam risk."""
    profile = profile or {}
    eligible: list[str] = []

    _has_revision = (profile.get("revision_count_last_30d") or 0) > 0
    if (is_trigger_enabled("first_assessment_no_engagement")
            and (profile.get("total_assessments") or 0) == 1
            and not _has_revision
            and not has_fired_recently(email, "first_assessment_no_engagement")):
        eligible.append("first_assessment_no_engagement")

    if (is_trigger_enabled("org_emergent_detected")
            and segment == "org_emergent"
            and not has_fired_recently(email, "org_emergent_detected")):
        eligible.append("org_emergent_detected")

    if (is_trigger_enabled("payment_recovery")
            and profile.get("subscription_status") == "attention"
            and not has_fired_recently(email, "payment_recovery")):
        eligible.append("payment_recovery")

    if (is_trigger_enabled("testimonial_ask")
            and (delta_confidence + delta_clarity) >= TESTIMONIAL_DELTA_THRESHOLD
            and not has_fired_recently(email, "testimonial_ask")):
        eligible.append("testimonial_ask")

    return eligible
