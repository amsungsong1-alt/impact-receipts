"""
utils/verification.py — reference-ID verification lookup for exported documents.

Every export (Readiness Card, Audit My Report Excel, Framework Crosswalk, Portfolio
Readiness Report) prints a "Ref: IMP-..." style ID and tells the reader to "cite this
reference ID" — but until now nothing behind that ID was actually checkable. This module
is the write side (record_export(), called alongside every download) and the read side
(verify_ref_id(), called by app.py's ?verify= landing page) of closing that gap.

Deliberately a separate table from utils/outcomes.py's outcome_feedback: that module drives
a different feature (the donor-acceptance-followup banner) with a fixed export-type
allowlist and a pending/answered/skipped lifecycle that doesn't apply to an immutable proof
record — reusing it would silently expand that banner's scope as a side effect. No
user_hash/email here either — a verify lookup is meant to work for anyone holding the
printed ref_id, not just the account that generated it.

Connects to the same Postgres database as utils/audits.py/utils/crm.py/utils/outcomes.py,
via the same SUPABASE_DB_URL secret and SQLAlchemy engine pattern (schema in
supabase/migrations/0019). All functions degrade gracefully on DB failure — never crash the
app, matching every other utils/*.py module's convention.
"""
from __future__ import annotations
import hashlib
import os

from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, Float, func
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()

# Same SQLite/rowid-alias autoincrement compat trick as utils/audits.py's _PK.
_PK = BigInteger().with_variant(Integer, "sqlite")

EXPORT_TYPES = {"readiness_card", "audit_excel", "framework_crosswalk", "portfolio_report"}


class ExportVerification(Base):
    __tablename__ = "export_verifications"
    id = Column(_PK, primary_key=True)
    ref_id = Column(Text, nullable=False)
    export_type = Column(Text, nullable=False)
    content_hash = Column(Text, nullable=False)
    confidence_score = Column(Float)
    clarity_score = Column(Float)
    score_band = Column(Text)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
    # Identical pattern to utils.audits._get_engine()/utils.outcomes._get_engine().
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


def compute_content_hash(result_statement: str, evidence_description: str, evidence_type: str,
                          confidence_score, clarity_score) -> str:
    """SHA-256 of the normalized (lowercased/stripped) content behind an export. Stored so a
    future v2 could let a verify page confirm a pasted document's content matches what was
    scored -- v1 never re-hashes or compares against anything, this is write-only for now.
    Never derivable back to the raw text (a one-way digest), so storing it doesn't create a
    second copy of submission content outside utils/audits.py's already-encrypted store."""
    normalized = "|".join([
        (result_statement or "").strip().lower(),
        (evidence_description or "").strip().lower(),
        (evidence_type or "").strip().lower(),
        str(confidence_score if confidence_score is not None else ""),
        str(clarity_score if clarity_score is not None else ""),
    ])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def record_export(ref_id: str, export_type: str, content_hash: str,
                   confidence_score: float = None, clarity_score: float = None,
                   score_band: str = "") -> None:
    """Best-effort, insert-only. Never raises -- a logging failure must not block the
    download it's recording, same contract as utils.outcomes.schedule_followup(). No-ops on
    an unrecognized export_type."""
    if not ref_id or export_type not in EXPORT_TYPES:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            session.add(ExportVerification(
                ref_id=ref_id, export_type=export_type, content_hash=content_hash,
                confidence_score=confidence_score, clarity_score=clarity_score,
                score_band=score_band or "",
            ))
            session.commit()
    except Exception:
        pass


def verify_ref_id(ref_id: str) -> dict | None:
    """Looks up a reference ID for the public ?verify= landing page. Returns only what's
    already printed in plaintext on the exported document itself (export type, date, scores,
    band) -- never raw submission content, which was never stored here in the first place
    (only its hash, see compute_content_hash()). Returns None on no-match, never
    distinguishing malformed-ID from right-format-no-row (same convention as app.py's
    unsubscribe landing, which never reveals whether a token matched a real account)."""
    if not ref_id:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            row = (session.query(ExportVerification)
                   .filter(ExportVerification.ref_id == ref_id)
                   .first())
            if not row:
                return None
            return {
                "ref_id": row.ref_id,
                "export_type": row.export_type,
                "confidence_score": row.confidence_score,
                "clarity_score": row.clarity_score,
                "score_band": row.score_band,
                "generated_at": row.generated_at,
            }
    except Exception:
        return None
