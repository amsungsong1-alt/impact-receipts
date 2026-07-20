"""
utils/outcomes.py — outcome feedback loop.

After a user downloads a Readiness Card or an Audit My Report Excel workbook, we schedule a
follow-up question shown on their next visit: was this report accepted by the donor? Answers
feed an admin-only acceptance-rate-by-score-band report.

Deliberately anonymized, unlike utils/audits.py (plaintext email, row-ownership-checked) and
utils/crm.py (plaintext email, growth analytics) -- this table only ever stores a one-way
hash of the account email (utils.metering-independent; reuses metrics.session_hash(), the
same technique already tested to never leak a raw id -- see test_metrics.py), never the
email itself. There is no "ownership check" against a real account here, only a hash
comparison: a caller must supply the same email that was hashed at schedule time to update a
row, but the row itself can never be reversed back to that email by anyone, including us.

Connects directly to the same Postgres database as utils/audits.py/utils/crm.py, via the same
SUPABASE_DB_URL secret and SQLAlchemy engine pattern (schema in supabase/migrations/0016).
All functions degrade gracefully on DB failure -- never crash the app, matching every other
utils/*.py module's convention.
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

EXPORT_TYPES = {"readiness_card", "audit_excel"}
RESPONSE_OPTIONS = ("Accepted", "Revisions requested", "Rejected", "Not yet submitted")
# Responses that represent an actual donor decision -- "Not yet submitted" is excluded from
# the acceptance-rate denominator below, since no decision has happened yet.
_DECIDED_RESPONSES = ("Accepted", "Revisions requested", "Rejected")

MIN_BAND_SAMPLE = 10  # same safeguard as utils.audits.MIN_BENCHMARK_SAMPLE -- don't cite a
                      # rate computed from a near-empty band.


class OutcomeFeedback(Base):
    __tablename__ = "outcome_feedback"
    id = Column(_PK, primary_key=True)
    ref_id = Column(Text, nullable=False)
    user_hash = Column(Text, nullable=False)
    export_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    response = Column(Text)
    score_band = Column(Text)
    confidence_score = Column(Float)
    clarity_score = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    responded_at = Column(DateTime(timezone=True))


_engine = None


def _get_engine():
    # Identical pattern to utils.audits._get_engine()/utils.crm._get_engine().
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


def schedule_followup(ref_id: str, email: str, export_type: str, confidence_score: float = None,
                       clarity_score: float = None, score_band: str = "") -> None:
    """Best-effort, insert-only. Never raises -- a logging failure must not block the
    download it's recording. No-ops on an unrecognized export_type, matching utils.crm.
    log_event()'s allowlist-enforcement convention."""
    if not ref_id or not email or export_type not in EXPORT_TYPES:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            session.add(OutcomeFeedback(
                ref_id=ref_id, user_hash=session_hash(email), export_type=export_type,
                confidence_score=confidence_score, clarity_score=clarity_score,
                score_band=score_band or "",
            ))
            session.commit()
    except Exception:
        pass


def get_pending_followup(email: str) -> dict | None:
    """The oldest still-pending follow-up for this email's hash, or None. Only one is ever
    returned at a time -- shown as a single banner, not a pile-up of every past download."""
    if not email:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            row = (session.query(OutcomeFeedback)
                   .filter(OutcomeFeedback.user_hash == session_hash(email),
                           OutcomeFeedback.status == "pending")
                   .order_by(OutcomeFeedback.created_at.asc())
                   .first())
            if not row:
                return None
            return {
                "id": row.id, "ref_id": row.ref_id, "export_type": row.export_type,
                "created_at": row.created_at,
            }
    except Exception:
        return None


def record_response(feedback_id: int, email: str, response: str) -> bool:
    """Marks a pending row 'answered' with the given response -- the hash of the supplied
    email must match the row's own hash (the only "ownership" check possible here, since the
    row was never linked to a real account in the first place). Returns True on success."""
    if not feedback_id or not email or response not in RESPONSE_OPTIONS:
        return False
    engine = _get_engine()
    if not engine:
        return False
    try:
        with Session(engine) as session:
            row = session.get(OutcomeFeedback, feedback_id)
            if not row or row.user_hash != session_hash(email) or row.status != "pending":
                return False
            row.status = "answered"
            row.response = response
            row.responded_at = datetime.now(timezone.utc)
            session.commit()
            return True
    except Exception:
        return False


def skip_followup(feedback_id: int, email: str) -> bool:
    """Dismisses a pending row permanently (status='skipped') so it never reappears on a
    later visit, without recording a response."""
    if not feedback_id or not email:
        return False
    engine = _get_engine()
    if not engine:
        return False
    try:
        with Session(engine) as session:
            row = session.get(OutcomeFeedback, feedback_id)
            if not row or row.user_hash != session_hash(email) or row.status != "pending":
                return False
            row.status = "skipped"
            session.commit()
            return True
    except Exception:
        return False


def compute_acceptance_stats() -> list[dict]:
    """Acceptance rate by score_band, for the admin view. Excludes 'Not yet submitted' from
    the rate's denominator (no donor decision has happened yet) and withholds a band's rate
    entirely below MIN_BAND_SAMPLE decided responses -- same safeguard as utils.audits.
    get_benchmark()'s MIN_BENCHMARK_SAMPLE, since this is exactly the kind of statistic that
    shouldn't be cited from a near-empty sample.

    Returns [{"score_band", "n_decided", "n_accepted", "acceptance_rate" (0-100, None if
    below MIN_BAND_SAMPLE), "n_not_yet_submitted"}, ...], one row per band that has at least
    one response of any kind."""
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = (session.query(OutcomeFeedback.score_band, OutcomeFeedback.response)
                    .filter(OutcomeFeedback.status == "answered")
                    .all())
    except Exception:
        return []

    bands: dict = {}
    for band, response in rows:
        band = band or "(no band)"
        b = bands.setdefault(band, {"n_decided": 0, "n_accepted": 0, "n_not_yet_submitted": 0})
        if response == "Not yet submitted":
            b["n_not_yet_submitted"] += 1
            continue
        if response in _DECIDED_RESPONSES:
            b["n_decided"] += 1
            if response == "Accepted":
                b["n_accepted"] += 1

    results = []
    for band, b in bands.items():
        rate = (round(b["n_accepted"] / b["n_decided"] * 100, 1)
                if b["n_decided"] >= MIN_BAND_SAMPLE else None)
        results.append({
            "score_band": band,
            "n_decided": b["n_decided"],
            "n_accepted": b["n_accepted"],
            "acceptance_rate": rate,
            "n_not_yet_submitted": b["n_not_yet_submitted"],
        })
    results.sort(key=lambda r: r["n_decided"], reverse=True)
    return results
