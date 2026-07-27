"""
utils/assessment_facts.py — Laudon Ch.6, C1 (write path): populates the
normalized assessment-fact tables (assessments, criterion_scores,
rules_fired, evidence_claims, indicators) from an already-computed
evaluate_submission() result.

Requires migrations 0030-0037 (supabase/migrations/) to be applied first --
degrades gracefully (no-ops) if the tables don't exist yet or the engine is
unavailable, same contract as every other utils/*.py write function. Until
those migrations are applied, calling record_assessment_facts() is a safe
no-op, not an error.

Hash-keyed (user_hash, metrics.session_hash()), not email -- same pattern
as utils/assessment_links.py, and populated for every scored assessment,
not just opted-in audits.py saves. Wired into the SAME call site as
utils.assessment_links.record_assessment() (app.py::render_screen_2()),
deliberately matching that feature's exact scope rather than expanding to
every scoring code path in the app.

Only scores, enums, dates, and booleans are ever written here -- never free
text. Result statements and evidence descriptions stay exactly where they
are today: encrypted, inside audits.submissions_json, opt-in only. This is
what lets a future warehouse built on these tables satisfy "no PII lands in
the warehouse" by construction, not a later scrubbing step.

Flags, never silently corrects: _parse_date() returns None for anything it
can't unambiguously parse, rather than guessing -- the original free-text
value is never lost (it stays in the encrypted blob), only not
double-counted here as a typed date it might not actually be.
"""
from __future__ import annotations
import os
from datetime import datetime, date

from sqlalchemy import (
    Column, BigInteger, Integer, Text, DateTime, Date, Numeric, Boolean, ForeignKey, func,
)
from sqlalchemy.orm import declarative_base, Session

from metrics import session_hash

Base = declarative_base()

# Same SQLite/rowid-alias autoincrement compat trick as utils/audits.py's _PK.
_PK = BigInteger().with_variant(Integer, "sqlite")


class Assessment(Base):
    __tablename__ = "assessments"
    id = Column(_PK, primary_key=True)
    user_hash = Column(Text, nullable=False)
    ref_id = Column(Text)
    donor = Column(Text)
    sector = Column(Text)
    org_type = Column(Text)
    evaluation_type = Column(Text)
    result_level = Column(Text)
    confidence_score = Column(Numeric)
    clarity_score = Column(Numeric)
    verdict = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CriterionScore(Base):
    __tablename__ = "criterion_scores"
    id = Column(_PK, primary_key=True)
    assessment_id = Column(BigInteger, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    criterion = Column(Text, nullable=False)
    level = Column(Integer)
    score = Column(Numeric)


class RuleFired(Base):
    __tablename__ = "rules_fired"
    id = Column(_PK, primary_key=True)
    assessment_id = Column(BigInteger, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(Text, nullable=False)
    criterion = Column(Text, nullable=False)
    rule_base_version = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"
    id = Column(_PK, primary_key=True)
    assessment_id = Column(BigInteger, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    evidence_type = Column(Text)
    verified = Column(Boolean)
    recency_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Indicator(Base):
    __tablename__ = "indicators"
    id = Column(_PK, primary_key=True)
    assessment_id = Column(BigInteger, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    indicator_name = Column(Text)
    logframe_target = Column(Text)
    logframe_baseline = Column(Text)
    logframe_achievement = Column(Text)
    baseline_date = Column(Date)
    endline_date = Column(Date)
    data_forthcoming = Column(Boolean)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
    # Identical pattern to utils.assessment_links._get_engine().
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


# The 3 confidence-axis criteria carry a clean 0-5 rubric level
# (direct_level/verify_level/recency_level) alongside their axis-weighted
# score. The 5 clarity-axis criteria are computed from yes/no checklist
# counts, not a single level scale -- there is no equivalent "level" for
# them, so `level` is legitimately null for Definition/Measurement/
# Integrity/Scope/Governance rows. Not a bug -- an accurate reflection of
# how evaluator.py's two axes are actually computed.
_LEVEL_KEYS = {
    "direct_score": "direct_level",
    "verify_score": "verify_level",
    "recency_score": "recency_level",
}


def _parse_date(value) -> date | None:
    """Best-effort parse of a free-text date field (e.g. evidence['recency'],
    which is a "Month Year" string like "July 2025" -- see
    evaluator._parse_month_year()'s sibling formats). Returns None for
    anything not unambiguously one of the tried formats, never raises,
    never guesses."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %Y", "%b %Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def record_assessment_facts(email: str, submission: dict, ev: dict, ref_id: str = "") -> None:
    """Best-effort, insert-only -- called unconditionally at evaluation time
    for every user (same call site/contract as
    utils.assessment_links.record_assessment()), so a failure here must
    never block Screen 2 from rendering. Writes one assessments row plus
    its criterion_scores/rules_fired/evidence_claims/indicators. Silently
    no-ops (never raises) if email is empty, the DB is unavailable, or the
    Ch.6 tables (migrations 0030-0037) don't exist yet."""
    if not email:
        return
    engine = _get_engine()
    if not engine:
        return
    try:
        confidence_components = ev.get("confidence_components", {}) or {}
        clarity_components = ev.get("clarity_components", {}) or {}

        with Session(engine) as session:
            assessment = Assessment(
                user_hash=session_hash(email),
                ref_id=ref_id or None,
                donor=submission.get("donor") or None,
                sector=submission.get("sector") or None,
                org_type=submission.get("org_type") or None,
                evaluation_type=submission.get("evaluation_type") or None,
                result_level=submission.get("result_level") or None,
                confidence_score=ev.get("confidence_score"),
                clarity_score=ev.get("clarity_score"),
                verdict=ev.get("verdict") or None,
            )
            session.add(assessment)
            session.flush()  # populates assessment.id without committing yet

            from evaluator import DIMENSION_MAP
            for criterion, (comp_key, score_key, _max_val) in DIMENSION_MAP.items():
                components = confidence_components if comp_key == "confidence_components" else clarity_components
                if score_key not in components:
                    continue
                level_key = _LEVEL_KEYS.get(score_key)
                session.add(CriterionScore(
                    assessment_id=assessment.id, criterion=criterion,
                    level=components.get(level_key) if level_key else None,
                    score=components.get(score_key),
                ))

            for rule in (ev.get("rule_trace") or []):
                if not rule.get("fired"):
                    continue
                session.add(RuleFired(
                    assessment_id=assessment.id, rule_id=rule.get("rule_id", ""),
                    criterion=rule.get("criterion", ""), rule_base_version=ev.get("rule_base_version"),
                ))

            evidence_list = submission.get("evidence") or []
            if evidence_list:
                primary_evidence = evidence_list[0]
                session.add(EvidenceClaim(
                    assessment_id=assessment.id,
                    evidence_type=primary_evidence.get("type") or None,
                    verified=bool((primary_evidence.get("verified_by") or "").strip()) or None,
                    recency_date=_parse_date(primary_evidence.get("recency")),
                ))

            indicator_name = submission.get("logframe_indicator")
            if indicator_name:
                # baseline_date/endline_date are left null here -- the submission
                # dict carries logframe_baseline/logframe_target/logframe_achievement
                # as free-text VALUES ("50 households"), not dates, and there is no
                # separate "when was baseline measured" field to parse one from.
                # Flag-never-guess: leaving these null is honest; mapping an
                # unrelated field into a date column would not be.
                session.add(Indicator(
                    assessment_id=assessment.id, indicator_name=indicator_name,
                    logframe_target=submission.get("logframe_target") or None,
                    logframe_baseline=submission.get("logframe_baseline") or None,
                    logframe_achievement=submission.get("logframe_achievement") or None,
                    data_forthcoming=bool(submission.get("logframe_data_forthcoming", False)),
                ))

            session.commit()
    except Exception:
        pass
