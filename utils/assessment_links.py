"""
utils/assessment_links.py — Laudon Ch.12 Implementation-stage tracking (D3).

Links a scoring run to the prior run a user explicitly marks it a revision of, so a
before/after delta ("did the fix actually raise the score?") can be shown on Screen 2.
Nothing else in the app answers this today: summarize_monthly_trend() (evaluator.py) shows a
coarse monthly aggregate, and utils/outcomes.py tracks the ultimate donor decision, but
neither links two specific scoring runs together.

Must work for every user, not just those who opt into utils/audits.py's saved-history
feature -- so this can't extend the opt-in, encrypted, plaintext-email-owned `audits` table.
Follows the same discipline as utils/outcomes.py (outcome_feedback) and utils/verification.py
(export_verifications), the two existing tables that already work for every user regardless
of opt-in: user_hash is a one-way hash (metrics.session_hash(), reused directly, never the
email itself), and no raw submission content is ever stored here -- only scores and which of
the 8 criteria was weakest at that point in time.

Connects to the same Postgres database as those modules, via the same SUPABASE_DB_URL secret
and SQLAlchemy engine pattern (schema in supabase/migrations/0020). All functions degrade
gracefully on DB failure -- never crash the app, matching every other utils/*.py module.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, Float, func
from sqlalchemy.orm import declarative_base, Session

from metrics import session_hash

Base = declarative_base()

# Same SQLite/rowid-alias autoincrement compat trick as utils/audits.py's _PK.
_PK = BigInteger().with_variant(Integer, "sqlite")


class AssessmentLink(Base):
    __tablename__ = "assessment_links"
    id = Column(_PK, primary_key=True)
    assessment_id = Column(Text, nullable=False)
    parent_assessment_id = Column(Text)
    user_hash = Column(Text, nullable=False)
    confidence_score = Column(Float)
    clarity_score = Column(Float)
    weakest_dimension = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
    # Identical pattern to utils.outcomes._get_engine()/utils.verification._get_engine().
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


def record_assessment(assessment_id: str, email: str, confidence_score: float = None,
                       clarity_score: float = None, weakest_dimension: str = "",
                       parent_assessment_id: str = None) -> None:
    """Best-effort, insert-only. Never raises -- called unconditionally at
    evaluation time for every user, so a logging failure must never block
    Screen 2 from rendering, matching utils.outcomes.schedule_followup()'s
    contract."""
    if not assessment_id or not email:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            session.add(AssessmentLink(
                assessment_id=assessment_id, parent_assessment_id=parent_assessment_id or None,
                user_hash=session_hash(email), confidence_score=confidence_score,
                clarity_score=clarity_score, weakest_dimension=weakest_dimension or "",
            ))
            session.commit()
    except Exception:
        pass


def list_recent_assessments(email: str, limit: int = 10) -> list:
    """This user's own recent assessments, newest first -- feeds the "This is
    a revision of..." picker on Screen 2. Scoped by user_hash, the only
    "ownership" check possible here since rows are never linked to a real
    account (same convention as utils.outcomes.get_pending_followup())."""
    if not email:
        return []
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = (session.query(AssessmentLink)
                    .filter(AssessmentLink.user_hash == session_hash(email))
                    # id as a tiebreaker: CURRENT_TIMESTAMP is only
                    # second-resolution on SQLite, so two inserts within the
                    # same second would otherwise sort arbitrarily.
                    .order_by(AssessmentLink.created_at.desc(), AssessmentLink.id.desc())
                    .limit(limit)
                    .all())
            return [{
                "assessment_id": r.assessment_id, "confidence_score": r.confidence_score,
                "clarity_score": r.clarity_score, "weakest_dimension": r.weakest_dimension,
                "parent_assessment_id": r.parent_assessment_id,
                "created_at": r.created_at,
            } for r in rows]
    except Exception:
        return []


def detect_systemic_gap_streak(email: str, streak_length: int = 3) -> str | None:
    """D5 -- Laudon Ch.12 p.474, operational-intelligence pattern: "the same
    criterion is the weakest link three assessments running" is a systemic
    gap, not a one-off incident. Pure read over already-shipped D3 data, zero
    new schema -- list_recent_assessments() already stores weakest_dimension
    ordered by recency per user.

    Returns the shared dimension name if the `streak_length` most recent
    assessments all agree on their weakest_dimension, else None (including
    when there are fewer than `streak_length` assessments to compare, or any
    of them has no weakest_dimension recorded)."""
    recent = list_recent_assessments(email, limit=streak_length)
    if len(recent) < streak_length:
        return None
    dims = {r["weakest_dimension"] for r in recent}
    if len(dims) == 1:
        _dim = dims.pop()
        return _dim or None
    return None


def get_delta(assessment_id: str) -> dict | None:
    """Axis-level before/after for one assessment relative to its parent, or
    None if this assessment has no parent link or either row can't be found.
    Phase 1 ships axis-level deltas only (confidence_score/clarity_score) --
    per-criterion deltas would need criterion_scores persisted too, which
    this table deliberately doesn't store (no raw submission content, and
    per-criterion scores start edging toward re-derivable submission
    content); weakest_dimension is stored precisely so the UI still has a
    trend signal without that."""
    if not assessment_id:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            child = (session.query(AssessmentLink)
                     .filter(AssessmentLink.assessment_id == assessment_id)
                     .order_by(AssessmentLink.created_at.desc(), AssessmentLink.id.desc())
                     .first())
            if not child or not child.parent_assessment_id:
                return None
            parent = (session.query(AssessmentLink)
                      .filter(AssessmentLink.assessment_id == child.parent_assessment_id)
                      .order_by(AssessmentLink.created_at.asc(), AssessmentLink.id.asc())
                      .first())
            if not parent:
                return None
            time_elapsed = None
            if child.created_at and parent.created_at:
                time_elapsed = child.created_at - parent.created_at
            return {
                "parent_assessment_id": parent.assessment_id,
                "parent_confidence_score": parent.confidence_score,
                "parent_clarity_score": parent.clarity_score,
                "parent_weakest_dimension": parent.weakest_dimension,
                "confidence_score": child.confidence_score,
                "clarity_score": child.clarity_score,
                "weakest_dimension": child.weakest_dimension,
                "delta_confidence": round((child.confidence_score or 0) - (parent.confidence_score or 0), 2),
                "delta_clarity": round((child.clarity_score or 0) - (parent.clarity_score or 0), 2),
                "time_elapsed": time_elapsed,
            }
    except Exception:
        return None
