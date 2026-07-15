"""
utils/audits.py — opt-in saved audit history, reusable logframe libraries,
and the anonymized benchmark that powers "How you compare."

Unlike utils/db.py (which talks to Supabase over its REST API via the anon
key), this module connects directly to the same underlying Postgres database
via SQLAlchemy, using a separate SUPABASE_DB_URL secret (the Postgres
connection string, not the SUPABASE_URL/SUPABASE_ANON_KEY pair). Schema is
tracked in supabase/migrations/0006-0011 -- the models below map onto that
already-created schema, they don't generate it. 0009 creates a
least-privilege Postgres role (app_audits_rw) that SUPABASE_DB_URL should
connect as instead of the default superuser -- see that migration's header
comment for why this matters: a superuser bypasses every GRANT/REVOKE check,
so the access_log table's append-only guarantee (0010) has no teeth without it.

Audit content (submissions_json/evaluations_json, and the Logframe Library's
free-text indicator columns) is encrypted at rest via utils/crypto.py
(Fernet/AES, key in AUDIT_ENCRYPTION_KEY) -- see 0011's migration comment for
what this does and does NOT cover (existing rows are not retroactively
encrypted). The denormalized donor/sector/org_type/score columns stay
unencrypted by design, so listing and benchmarking never need decryption.

All functions degrade gracefully on DB failure (never crash the app),
matching utils/db.py's convention. Nothing here runs unless a user has
explicitly opted in (the "save this audit" consent toggle, or explicit
Logframe Library actions) -- a user who never opts in sees zero behavior
change.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, Float, JSON, ForeignKey, func
from sqlalchemy.orm import declarative_base, Session

from utils.crypto import encrypt_text, decrypt_text

Base = declarative_base()

MIN_BENCHMARK_SAMPLE = 10  # don't show a percentile from a near-empty bucket

# SQLite's rowid-alias autoincrement requires the PK column to compile to
# exactly "INTEGER PRIMARY KEY" -- BigInteger alone doesn't qualify on that
# dialect (it's fine on real Postgres, where these map to bigserial). Swap to
# plain Integer only for SQLite so the in-memory test engine still gets
# working autoincrement ids.
_PK = BigInteger().with_variant(Integer, "sqlite")


class Audit(Base):
    __tablename__ = "audits"
    id = Column(_PK, primary_key=True)
    email = Column(Text, nullable=False)
    ref_id = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    active_slots = Column(Integer, nullable=False)
    submissions_json = Column(Text, nullable=False)  # Fernet ciphertext, not raw JSON -- see utils/crypto.py
    evaluations_json = Column(Text, nullable=False)  # same
    donor = Column(Text)
    sector = Column(Text)
    org_type = Column(Text)
    primary_confidence_score = Column(Float)
    primary_clarity_score = Column(Float)
    primary_verdict = Column(Text)


class LogframeLibrary(Base):
    __tablename__ = "logframe_libraries"
    id = Column(_PK, primary_key=True)
    email = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class LogframeLibraryItem(Base):
    __tablename__ = "logframe_library_items"
    id = Column(_PK, primary_key=True)
    library_id = Column(BigInteger, ForeignKey("logframe_libraries.id"), nullable=False)
    indicator_name = Column(Text)
    logframe_indicator = Column(Text)
    logframe_baseline = Column(Text)
    logframe_target = Column(Text)
    logframe_achievement = Column(Text)
    sector = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditAggregateStats(Base):
    __tablename__ = "audit_aggregate_stats"
    donor = Column(Text, primary_key=True)
    sector = Column(Text, primary_key=True)
    org_type = Column(Text, primary_key=True)
    sample_size = Column(Integer, default=0)
    confidence_scores = Column(JSON, default=list)
    clarity_scores = Column(JSON, default=list)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class AccessLog(Base):
    __tablename__ = "access_log"
    id = Column(_PK, primary_key=True)
    email = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    resource_type = Column(Text)
    resource_id = Column(Text)
    ip_address = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
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


# ---------------------------------------------------------------------------
# Saved audits
# ---------------------------------------------------------------------------

def save_audit(email: str, submissions: list, evaluations: list, ref_id: str) -> int | None:
    """Persist one submission-run as a saved audit. Denormalizes donor/sector/
    org_type and result-#1's scores from the run for fast listing, then
    triggers a best-effort aggregate-bucket recompute (a failed recompute
    must not fail the save itself)."""
    if not email or not submissions or not evaluations or not ref_id:
        return None
    engine = _get_engine()
    if not engine:
        return None
    enc_submissions = encrypt_text(json.dumps(submissions))
    enc_evaluations = encrypt_text(json.dumps(evaluations))
    if enc_submissions is None or enc_evaluations is None:
        # Fail closed -- never fall back to storing plaintext content just
        # because AUDIT_ENCRYPTION_KEY is missing or encryption failed.
        return None
    try:
        first_sub = submissions[0] or {}
        first_ev = evaluations[0] or {}
        donor = first_sub.get("donor") or ""
        sector = first_sub.get("sector") or ""
        org_type = first_sub.get("org_type") or ""
        with Session(engine) as session:
            row = Audit(
                email=email,
                ref_id=ref_id,
                active_slots=len(submissions),
                submissions_json=enc_submissions,
                evaluations_json=enc_evaluations,
                donor=donor,
                sector=sector,
                org_type=org_type,
                primary_confidence_score=first_ev.get("confidence_score"),
                primary_clarity_score=first_ev.get("clarity_score"),
                primary_verdict=first_ev.get("verdict"),
            )
            session.add(row)
            session.commit()
            audit_id = row.id
    except Exception:
        return None
    log_access(email, "save_audit", resource_type="audit", resource_id=audit_id)
    if donor and sector and org_type:
        try:
            _recompute_bucket(donor, sector, org_type)
        except Exception:
            pass
    return audit_id


def list_audits(email: str, limit: int = 50) -> list[dict]:
    """Summary rows for the My Audits page (no submissions/evaluations JSON --
    use get_audit() for the full record needed to re-download a PDF)."""
    if not email:
        return []
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = (session.query(Audit)
                    .filter(Audit.email == email)
                    .order_by(Audit.created_at.desc())
                    .limit(limit)
                    .all())
            return [{
                "id": r.id, "ref_id": r.ref_id, "created_at": r.created_at,
                "donor": r.donor, "sector": r.sector, "org_type": r.org_type,
                "primary_confidence_score": r.primary_confidence_score,
                "primary_clarity_score": r.primary_clarity_score,
                "primary_verdict": r.primary_verdict,
                "active_slots": r.active_slots,
            } for r in rows]
    except Exception:
        return []


def get_audit(email: str, audit_id: int) -> dict | None:
    """Full saved-audit record, scoped to email (a user can't fetch another
    account's audit by guessing an id)."""
    if not email or not audit_id:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            row = session.get(Audit, audit_id)
            if not row or row.email != email:
                return None
            dec_submissions = decrypt_text(row.submissions_json)
            dec_evaluations = decrypt_text(row.evaluations_json)
            if dec_submissions is None or dec_evaluations is None:
                return None  # wrong/missing key, or corrupted ciphertext -- never return partial content
            return {
                "id": row.id, "ref_id": row.ref_id, "created_at": row.created_at,
                "active_slots": row.active_slots,
                "submissions": json.loads(dec_submissions),
                "evaluations": json.loads(dec_evaluations),
                "donor": row.donor, "sector": row.sector, "org_type": row.org_type,
            }
    except Exception:
        return None


def delete_audit(email: str, audit_id: int) -> None:
    if not email or not audit_id:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            row = session.get(Audit, audit_id)
            if row and row.email == email:
                log_access(email, "delete_audit", resource_type="audit", resource_id=audit_id)
                session.delete(row)
                session.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Logframe Library
# ---------------------------------------------------------------------------

def create_logframe_library(email: str, name: str) -> int | None:
    if not email or not name:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            lib = LogframeLibrary(email=email, name=name)
            session.add(lib)
            session.commit()
            lib_id = lib.id
    except Exception:
        return None
    log_access(email, "create_logframe_library", resource_type="logframe_library", resource_id=lib_id)
    return lib_id


def list_logframe_libraries(email: str) -> list[dict]:
    if not email:
        return []
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = (session.query(LogframeLibrary)
                    .filter(LogframeLibrary.email == email)
                    .order_by(LogframeLibrary.updated_at.desc())
                    .all())
            return [{"id": r.id, "name": r.name, "created_at": r.created_at,
                      "updated_at": r.updated_at} for r in rows]
    except Exception:
        return []


_LIBRARY_ENCRYPTED_FIELDS = (
    "indicator_name", "logframe_indicator", "logframe_baseline",
    "logframe_target", "logframe_achievement",
)  # sector is deliberately excluded -- low-cardinality/constrained, not free text


def add_library_items(library_id: int, email: str, items: list) -> None:
    """items: list of dicts with indicator_name/logframe_indicator/
    logframe_baseline/logframe_target/logframe_achievement/sector keys --
    the same shape CSV Portfolio upload and IRC batch extraction already
    produce. email is re-checked as an ownership guard, not just a filter.
    The five free-text fields are encrypted at rest (see utils/crypto.py);
    fails closed (stores nothing) if AUDIT_ENCRYPTION_KEY is missing."""
    if not library_id or not email or not items:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            lib = session.get(LogframeLibrary, library_id)
            if not lib or lib.email != email:
                return
            for item in items:
                encrypted = {}
                for field in _LIBRARY_ENCRYPTED_FIELDS:
                    val = encrypt_text(item.get(field, "") or "")
                    if val is None:
                        return  # fail closed -- never store plaintext content
                    encrypted[field] = val
                session.add(LogframeLibraryItem(
                    library_id=library_id,
                    sector=item.get("sector", ""),
                    **encrypted,
                ))
            lib.updated_at = datetime.now(timezone.utc)
            session.commit()
    except Exception:
        return
    log_access(email, "add_library_items", resource_type="logframe_library", resource_id=library_id)


def get_library_items(library_id: int, email: str) -> list[dict]:
    if not library_id or not email:
        return []
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            lib = session.get(LogframeLibrary, library_id)
            if not lib or lib.email != email:
                return []
            rows = (session.query(LogframeLibraryItem)
                    .filter(LogframeLibraryItem.library_id == library_id)
                    .order_by(LogframeLibraryItem.created_at.asc())
                    .all())
            items = []
            for r in rows:
                decrypted = {f: (decrypt_text(getattr(r, f)) or "") for f in _LIBRARY_ENCRYPTED_FIELDS}
                items.append({"id": r.id, "sector": r.sector, **decrypted})
            return items
    except Exception:
        return []


def delete_logframe_library(library_id: int, email: str) -> None:
    if not library_id or not email:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            lib = session.get(LogframeLibrary, library_id)
            if lib and lib.email == email:
                log_access(email, "delete_logframe_library", resource_type="logframe_library", resource_id=library_id)
                session.delete(lib)  # DB-level ON DELETE CASCADE removes its items
                session.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Anonymized benchmark ("How you compare")
# ---------------------------------------------------------------------------

def _recompute_bucket(donor: str, sector: str, org_type: str) -> None:
    """Re-derives one (donor, sector, org_type) bucket's score arrays from
    the audits table. Internal -- called by save_audit() after each save."""
    engine = _get_engine()
    if not engine:
        return
    with Session(engine) as session:
        rows = (session.query(Audit.primary_confidence_score, Audit.primary_clarity_score)
                .filter(Audit.donor == donor, Audit.sector == sector, Audit.org_type == org_type,
                        Audit.primary_confidence_score.isnot(None),
                        Audit.primary_clarity_score.isnot(None))
                .all())
        conf_scores = [r[0] for r in rows]
        clar_scores = [r[1] for r in rows]
        bucket = session.get(AuditAggregateStats, (donor, sector, org_type))
        if bucket is None:
            bucket = AuditAggregateStats(donor=donor, sector=sector, org_type=org_type)
            session.add(bucket)
        bucket.sample_size = len(conf_scores)
        bucket.confidence_scores = conf_scores
        bucket.clarity_scores = clar_scores
        bucket.updated_at = datetime.now(timezone.utc)
        session.commit()


def _percentile_rank(scores: list, value: float) -> int:
    if not scores:
        return 50
    below_or_equal = sum(1 for s in scores if s <= value)
    return round(below_or_equal / len(scores) * 100)


def get_benchmark(donor: str, sector: str, org_type: str,
                   my_confidence: float, my_clarity: float) -> dict | None:
    """Returns {"sample_size", "confidence_percentile", "clarity_percentile"}
    for this donor/sector/org_type bucket, or None if it has fewer than
    MIN_BENCHMARK_SAMPLE saved audits (avoids showing a misleading percentile
    from a near-empty bucket)."""
    if not donor or not sector or not org_type:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            bucket = session.get(AuditAggregateStats, (donor, sector, org_type))
            if not bucket or bucket.sample_size < MIN_BENCHMARK_SAMPLE:
                return None
            return {
                "sample_size": bucket.sample_size,
                "confidence_percentile": _percentile_rank(bucket.confidence_scores or [], my_confidence),
                "clarity_percentile": _percentile_rank(bucket.clarity_scores or [], my_clarity),
            }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Access log (append-only) + rate limiting
# ---------------------------------------------------------------------------

def log_access(email: str, action: str, resource_type: str | None = None,
                resource_id=None, ip_address: str | None = None) -> None:
    """Best-effort append to the access log. Never raises -- a logging
    failure must not block the action it's recording. Insert-only by design
    (see migration 0010's comment) -- this module never updates or deletes a
    row here, and the DB role it connects as has no grant to do so either."""
    if not email or not action:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            session.add(AccessLog(
                email=email, action=action, resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                ip_address=ip_address,
            ))
            session.commit()
    except Exception:
        pass


def check_rate_limit(email: str, action: str, max_count: int, window_seconds: int) -> bool:
    """True if `email` has performed fewer than max_count of `action` in the
    last window_seconds, per access_log. Fails OPEN (returns True) on any DB
    error -- a rate-limiter outage must not block legitimate use, matching
    this module's existing degrade-gracefully convention."""
    if not email or not action:
        return True
    engine = _get_engine()
    if not engine:
        return True
    try:
        from sqlalchemy import func as _func
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        with Session(engine) as session:
            count = (session.query(_func.count(AccessLog.id))
                     .filter(AccessLog.email == email, AccessLog.action == action,
                             AccessLog.created_at >= cutoff)
                     .scalar())
            return (count or 0) < max_count
    except Exception:
        return True
