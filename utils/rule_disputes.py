"""
utils/rule_disputes.py — Laudon Ch.11 organisational learning loop (C6).

When a user or reviewer disputes one of the expert-system rule base's firings
(knowledge/rules/*.yaml, utils/inference.py), this module captures the dispute against the
rule id. Surfaces a dispute-count ranking for the hidden admin view so a MEL specialist can
see which rules get disputed most often and decide whether to edit the YAML — this module
never auto-tunes or auto-disables a rule from dispute volume; codified judgement stays
human-owned, per Laudon's point about ML needing significant human training to apply here too.

Anonymized (hashed email via metrics.session_hash(), same as utils/outcomes.py/
utils/assessment_links.py) — a dispute doesn't need row-ownership-checked mutation, only
insert + aggregate read, so no plaintext email is stored here.

Note: this ships raw dispute *counts*, not a true dispute *rate* — there is no lightweight,
always-on counter of how many times each rule has fired (rule_trace is computed live per
request, only ever persisted inside utils/audits.py's encrypted, opt-in-only evaluations_json),
so "disputes per firing" isn't computable yet. A count ranking ("these rules get disputed
most often") is still directly useful and is what ships in this pass; true rate normalization
is deferred until a firing-count mechanism is scoped on its own.

Connects to the same Postgres database as utils/outcomes.py/utils/assessment_links.py, via the
same SUPABASE_DB_URL secret and SQLAlchemy engine pattern (schema in supabase/migrations/0022).
All functions degrade gracefully on DB failure -- never crash the app.
"""
from __future__ import annotations
import os

from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, func
from sqlalchemy.orm import declarative_base, Session

from metrics import session_hash

Base = declarative_base()

# Same SQLite/rowid-alias autoincrement compat trick as utils/audits.py's _PK.
_PK = BigInteger().with_variant(Integer, "sqlite")


class RuleDispute(Base):
    __tablename__ = "rule_disputes"
    id = Column(_PK, primary_key=True)
    rule_id = Column(Text, nullable=False)
    rule_base_version = Column(Text)
    user_hash = Column(Text, nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
    # Identical pattern to utils.outcomes._get_engine()/utils.assessment_links._get_engine().
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


def record_dispute(rule_id: str, email: str, reason: str = "", rule_base_version: str = "") -> None:
    """Best-effort, insert-only. Never raises -- a logging failure must not
    block the UI action that triggered it, same contract as every other
    utils/*.py write. No-ops on a missing rule_id or email."""
    if not rule_id or not email:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        with Session(engine) as session:
            session.add(RuleDispute(
                rule_id=rule_id, rule_base_version=rule_base_version or "",
                user_hash=session_hash(email), reason=reason or "",
            ))
            session.commit()
    except Exception:
        pass


def get_dispute_counts() -> list:
    """Raw dispute count per rule_id, sorted descending -- for the hidden
    admin view. Returns [] on any DB failure rather than raising."""
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = (session.query(RuleDispute.rule_id, func.count(RuleDispute.id))
                    .group_by(RuleDispute.rule_id)
                    .all())
            counts = [{"rule_id": rule_id, "count": count} for rule_id, count in rows]
            counts.sort(key=lambda r: r["count"], reverse=True)
            return counts
    except Exception:
        return []
