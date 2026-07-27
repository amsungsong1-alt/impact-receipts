"""
test_assessment_facts.py — golden tests for utils/assessment_facts.py
(Laudon Ch.6, C1 write path): populating the normalized assessment-fact
tables from an evaluate_submission() result.

No pytest, no network calls. In-memory SQLite engine swap, same convention
as test_assessment_links.py -- SQLite doesn't enforce foreign keys by
default, which is fine here since these tests check content, not
cascade-delete behavior (that's a Postgres-only concern for the real CHECK/
FK constraints, not re-tested here). Run with:
python test_assessment_facts.py
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.assessment_facts as af
from metrics import session_hash


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    af.Base.metadata.create_all(engine)
    return engine


def _submission(**overrides) -> dict:
    base = {
        "donor": "USAID", "sector": "Health", "org_type": "International NGO (INGO)",
        "evaluation_type": "Endline", "result_level": "Outcome",
        "evidence": [{"type": "Attendance sheets / participant registers",
                      "verified_by": "District Officer", "recency": "July 2025"}],
        "logframe_indicator": "% of participants employed", "logframe_target": "60%",
        "logframe_baseline": "10%", "logframe_achievement": "55%",
        "logframe_data_forthcoming": False,
    }
    base.update(overrides)
    return base


def _ev(**overrides) -> dict:
    base = {
        "confidence_score": 4.2, "clarity_score": 3.8, "verdict": "Strong KPI",
        "confidence_components": {
            "direct_score": 1.8, "direct_level": 4,
            "verify_score": 1.6, "verify_level": 4,
            "recency_score": 0.8, "recency_level": 4,
        },
        "clarity_components": {
            "definition_score": 1.0, "measurement_score": 1.0, "integrity_score": 0.8,
            "scope_score": 0.5, "governance_score": 0.5,
        },
        "rule_trace": [
            {"rule_id": "directness_no_primary_record", "criterion": "Directness", "fired": False},
            {"rule_id": "verification_internal_only", "criterion": "Verification", "fired": True},
        ],
        "rule_base_version": "2026.07.1",
    }
    base.update(overrides)
    return base


def run_record_assessment_facts_full():
    failures = []
    original_get_engine = af._get_engine
    engine = _fresh_engine()
    af._get_engine = lambda: engine
    try:
        af.record_assessment_facts("test@example.com", _submission(), _ev(), ref_id="ASM-TEST-1")

        with Session(engine) as session:
            a = session.query(af.Assessment).first()
            if a is None:
                failures.append("no assessment row was written")
            else:
                if a.donor != "USAID" or float(a.confidence_score) != 4.2 or a.ref_id != "ASM-TEST-1":
                    failures.append(f"assessment row has wrong content: {a.donor}, {a.confidence_score}, {a.ref_id}")
                if a.user_hash != session_hash("test@example.com"):
                    failures.append("user_hash does not match metrics.session_hash() -- wrong hash function/input")

                scores = {s.criterion: (s.level, float(s.score) if s.score is not None else None)
                          for s in session.query(af.CriterionScore).filter_by(assessment_id=a.id).all()}
                if scores.get("Directness") != (4, 1.8):
                    failures.append(f"Directness criterion_scores row wrong: {scores.get('Directness')}")
                if scores.get("Definition") != (None, 1.0):
                    failures.append(
                        f"Definition should have a null level (clarity criteria have no level scale), "
                        f"got: {scores.get('Definition')}"
                    )
                if len(scores) != 8:
                    failures.append(f"expected 8 criterion_scores rows (one per DIMENSION_MAP entry), got {len(scores)}")

                fired = session.query(af.RuleFired).filter_by(assessment_id=a.id).all()
                if len(fired) != 1 or fired[0].rule_id != "verification_internal_only":
                    failures.append(f"expected only the 1 fired rule written, got: {[(r.rule_id, r.fired if hasattr(r,'fired') else None) for r in fired]}")

                ec = session.query(af.EvidenceClaim).filter_by(assessment_id=a.id).first()
                if not ec or ec.evidence_type != "Attendance sheets / participant registers" or ec.verified is not True:
                    failures.append(f"evidence_claims row wrong: {ec}")
                if not ec or str(ec.recency_date) != "2025-07-01":
                    failures.append(f"evidence_claims.recency_date should parse 'July 2025' -> 2025-07-01, got: {ec.recency_date if ec else None}")

                ind = session.query(af.Indicator).filter_by(assessment_id=a.id).first()
                if not ind or ind.indicator_name != "% of participants employed":
                    failures.append(f"indicators row wrong: {ind}")
                if ind and (ind.baseline_date is not None or ind.endline_date is not None):
                    failures.append(
                        "baseline_date/endline_date should stay null -- there is no real date source "
                        "field for them, and guessing one would violate the no-fabrication rule"
                    )
    finally:
        af._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_assessment_facts — writes assessments/criterion_scores/rules_fired/"
          "evidence_claims/indicators correctly, only fired rules stored, clarity criteria "
          "correctly have a null level, unparseable/absent dates stay null rather than guessed.")


def run_never_writes_free_text():
    """The whole point of this table set: no result statement, no evidence
    description, ever. Confirm no column anywhere in the ORM models could
    even hold either."""
    failures = []
    free_text_fields = {"result_statement", "description", "evidence_description"}
    for model in (af.Assessment, af.CriterionScore, af.RuleFired, af.EvidenceClaim, af.Indicator):
        columns = {c.name for c in model.__table__.columns}
        overlap = columns & free_text_fields
        if overlap:
            failures.append(f"{model.__tablename__} has a free-text-shaped column: {overlap}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no ORM model exposes a column that could hold free-text result statement/"
          "evidence description content.")


def run_degrades_gracefully():
    failures = []
    original_get_engine = af._get_engine
    engine = _fresh_engine()
    af._get_engine = lambda: engine
    try:
        # Empty email must no-op, not raise, and must not write a row.
        af.record_assessment_facts("", _submission(), _ev())
        with Session(engine) as session:
            if session.query(af.Assessment).count() != 0:
                failures.append("an empty email should not write any row")

        # No engine available must no-op, not raise.
        af._get_engine = lambda: None
        af.record_assessment_facts("x@example.com", _submission(), _ev())

        # A malformed/empty ev dict must not raise (missing keys degrade to
        # None/skip, matching every other utils/*.py write function).
        af._get_engine = lambda: engine
        af.record_assessment_facts("x@example.com", {}, {})
        with Session(engine) as session:
            a = session.query(af.Assessment).filter_by(user_hash=session_hash("x@example.com")).first()
            if a is None:
                failures.append("a minimal/empty submission+ev should still write a bare assessment row")
    except Exception as exc:
        failures.append(f"record_assessment_facts raised: {exc!r}")
    finally:
        af._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: degrades gracefully — empty email writes nothing, no engine no-ops, "
          "a malformed/empty submission+ev never raises.")


def run_date_parsing():
    failures = []
    cases = [
        ("July 2025", "2025-07-01"),
        ("2025-07-15", "2025-07-15"),
        ("15/07/2025", "2025-07-15"),
        ("", None),
        (None, None),
        ("not a date at all", None),
    ]
    for raw, expected in cases:
        got = af._parse_date(raw)
        got_str = str(got) if got is not None else None
        if got_str != expected:
            failures.append(f"_parse_date({raw!r}) expected {expected!r}, got {got_str!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: _parse_date — handles known formats, degrades to None for anything ambiguous, never raises.")


if __name__ == "__main__":
    run_record_assessment_facts_full()
    run_never_writes_free_text()
    run_degrades_gracefully()
    run_date_parsing()
