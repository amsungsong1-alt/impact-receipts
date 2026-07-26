"""
utils/cross_sell.py — Laudon Ch.9 CRM, C7: cross-sell recommendation logging.

recommend() is behaviour-only -- it never reads sector/country/org-type or
any other demographic field, only usage signals already computed elsewhere
(a behavioural segment, revision activity, a systemic weak-criterion streak
reused from utils.assessment_links). Recommendations are logged, not
auto-sent to anyone; "log every recommendation and its outcome so the logic
can be evaluated rather than believed" (the build prompt's own framing) --
this module never decides FOR the founder who to contact, it only tracks
who might be worth contacting and whether that call worked.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, func
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()
_PK = BigInteger().with_variant(Integer, "sqlite")

# recommendation_type -> the real-world plan label(s) (see app.py's
# tier_change crm_event metadata) that count as that recommendation having
# converted. Used by record_recommendation_outcome()'s callers.
CONVERSION_PLAN_LABELS = {
    "upgrade_to_subscription": {"monthly", "annual", "professional"},
    "upgrade_to_org_plan": {"agency"},
}


class CrossSellRecommendation(Base):
    __tablename__ = "cross_sell_recommendations"
    id = Column(_PK, primary_key=True)
    email = Column(Text, nullable=False)
    recommendation_type = Column(Text, nullable=False)
    shown_at = Column(DateTime(timezone=True), server_default=func.now())
    outcome = Column(Text)
    resolved_at = Column(DateTime(timezone=True))


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


def recommend(profile: dict) -> str | None:
    """Pure-ish (one DB read for the systemic-gap-streak check) function:
    given a customer_profiles row, returns the single best-fit recommendation
    type or None. Behaviour-only, never demographic:
      - embedded segment with real revision activity -> upgrade_to_subscription
      - org_emergent segment -> upgrade_to_org_plan
      - a systemic weak-criterion streak (reuses
        utils.assessment_links.detect_systemic_gap_streak() from the Ch.12
        work, not new logic) -> training_or_template_product, a demand
        signal for a not-yet-built product, not acted on yet.
    Never raises."""
    profile = profile or {}
    email = profile.get("email")

    from utils.crm import compute_behavioral_segment
    from utils.mel_calendar import load_mel_calendar
    segment = compute_behavioral_segment(profile, load_mel_calendar())

    if segment == "embedded" and (profile.get("revision_count_last_30d") or 0) > 0:
        return "upgrade_to_subscription"
    if segment == "org_emergent":
        return "upgrade_to_org_plan"

    if email:
        try:
            from utils.assessment_links import detect_systemic_gap_streak
            if detect_systemic_gap_streak(email):
                return "training_or_template_product"
        except Exception:
            pass
    return None


def record_recommendation(email: str, recommendation_type: str) -> None:
    """Best-effort, deduped -- no duplicate unresolved (outcome IS NULL)
    recommendation of the same type for the same account. Never raises."""
    if not email or not recommendation_type:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            existing = (session.query(CrossSellRecommendation)
                        .filter(CrossSellRecommendation.email == email,
                                CrossSellRecommendation.recommendation_type == recommendation_type,
                                CrossSellRecommendation.outcome.is_(None))
                        .first())
            if existing is not None:
                return
            session.add(CrossSellRecommendation(email=email, recommendation_type=recommendation_type))
            session.commit()
    except Exception:
        pass


def record_recommendation_outcome(email: str, recommendation_type: str, outcome: str) -> None:
    """Marks the most recent unresolved recommendation of this type for this
    account with a real-world outcome ('converted'/'declined'/'expired').
    No-ops if there's no matching pending recommendation. Never raises."""
    if not email or not recommendation_type or not outcome:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            row = (session.query(CrossSellRecommendation)
                   .filter(CrossSellRecommendation.email == email,
                           CrossSellRecommendation.recommendation_type == recommendation_type,
                           CrossSellRecommendation.outcome.is_(None))
                   .order_by(CrossSellRecommendation.shown_at.desc())
                   .first())
            if row is None:
                return
            row.outcome = outcome
            row.resolved_at = datetime.now(timezone.utc)
            session.commit()
    except Exception:
        pass


def record_outcome_for_plan_label(email: str, plan_label: str) -> None:
    """Convenience wrapper for app.py's tier_change call sites: given the
    real plan a customer just landed on, marks any matching pending
    recommendation(s) converted via CONVERSION_PLAN_LABELS. Never raises."""
    if not email or not plan_label:
        return
    plan_label_l = plan_label.lower()
    for rec_type, labels in CONVERSION_PLAN_LABELS.items():
        if plan_label_l in labels:
            record_recommendation_outcome(email, rec_type, "converted")


def list_pending_recommendations() -> list[dict]:
    """Every recommendation with no outcome yet -- the admin dashboard's
    "who to call" list. Returns [] on any DB failure."""
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = (session.query(CrossSellRecommendation)
                    .filter(CrossSellRecommendation.outcome.is_(None))
                    .order_by(CrossSellRecommendation.shown_at.desc())
                    .all())
            return [{"email": r.email, "recommendation_type": r.recommendation_type,
                     "shown_at": r.shown_at} for r in rows]
    except Exception:
        return []
