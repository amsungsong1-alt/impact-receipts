"""
test_populate_warehouse.py — golden tests for scripts/populate_warehouse.py
(Laudon Ch.6 Phase 2, C4): ETL from assessments/criterion_scores into the
star-schema warehouse (migration 0055).

No pytest, no network calls. In-memory SQLite engine, same convention as
test_assessment_facts.py -- this script does plain reads/inserts, not
information_schema introspection, so unlike scripts/quality_audit.py and
scripts/generate_data_dictionary.py it CAN run against SQLite. Run with:
python test_populate_warehouse.py
"""

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import scripts.populate_warehouse as pw
import utils.assessment_facts as af


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    af.Base.metadata.create_all(engine)
    pw.Base.metadata.create_all(engine)
    return engine


def _seed_assessment(engine, **overrides) -> int:
    defaults = dict(
        user_hash="hash1", donor="USAID", sector="Health",
        org_type="International NGO (INGO)", evaluation_type="Endline",
        result_level="Outcome", confidence_score=4.2, clarity_score=2.5,
        verdict="Strong KPI", created_at=datetime(2025, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    with Session(engine) as session:
        row = af.Assessment(**defaults)
        session.add(row)
        session.commit()
        return row.id


def _seed_criterion_scores(engine, assessment_id: int, scores: dict):
    """scores: {criterion: score}."""
    with Session(engine) as session:
        for criterion, score in scores.items():
            session.add(af.CriterionScore(assessment_id=assessment_id, criterion=criterion, score=score))
        session.commit()


def run_populate_full():
    failures = []
    engine = _fresh_engine()
    aid = _seed_assessment(engine)
    # Directness max 2.0, Verification max 2.0, Recency max 1.0 (confidence);
    # Definition max 1.25 (clarity) -- from evaluator.DIMENSION_MAP.
    _seed_criterion_scores(engine, aid, {
        "Directness": 1.8,      # 90% of 2.0 -> pass
        "Verification": 0.5,    # 25% of 2.0 -> fail
        "Recency": 1.0,         # 100% of 1.0 -> pass
        "Definition": 0.5,      # 40% of 1.25 -> fail
    })

    count = pw.populate(engine)
    if count != 1:
        failures.append(f"expected 1 new fact row, got {count}")

    with Session(engine) as session:
        fact = session.query(pw.FactAssessment).filter_by(assessment_id=aid).first()
        if fact is None:
            failures.append("no fact_assessment row was written")
        else:
            if float(fact.confidence_score) != 4.2 or float(fact.clarity_score) != 2.5:
                failures.append(f"fact row scores wrong: {fact.confidence_score}, {fact.clarity_score}")
            if fact.verdict != "Strong KPI":
                failures.append(f"fact row verdict wrong: {fact.verdict}")
            if (fact.criteria_passed_count, fact.criteria_failed_count) != (2, 2):
                failures.append(
                    f"expected 2 passed / 2 failed criteria, got "
                    f"{fact.criteria_passed_count}/{fact.criteria_failed_count}"
                )
            if str(fact.date_key) != "2025-07-15":
                failures.append(f"expected date_key 2025-07-15, got {fact.date_key}")

        donor = session.query(pw.DimDonor).filter_by(donor="USAID").first()
        if donor is None or fact is None or fact.donor_id != donor.id:
            failures.append("fact_assessment.donor_id does not point at the USAID dim_donor row")

        sector = session.query(pw.DimSector).filter_by(sector="Health").first()
        if sector is None or fact is None or fact.sector_id != sector.id:
            failures.append("fact_assessment.sector_id does not point at the Health dim_sector row")

        d = session.query(pw.DimDate).filter_by(date_key=date(2025, 7, 15)).first()
        if d is None or d.year != 2025 or d.quarter != 3 or d.month_name != "July":
            failures.append(f"dim_date row wrong: {d}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: populate() writes a correct fact_assessment row with get-or-create dimension "
          "rows and an accurate criteria pass/fail count derived from evaluator.DIMENSION_MAP.")


def run_idempotent_and_shared_dimensions():
    """Running populate() twice must not duplicate fact rows, and two
    assessments sharing a donor/sector/org_type must reuse the same
    dimension row rather than creating a duplicate."""
    failures = []
    engine = _fresh_engine()
    aid1 = _seed_assessment(engine)
    aid2 = _seed_assessment(engine, donor="USAID", sector="Health")  # same dims, different assessment

    pw.populate(engine)
    count_second_run = pw.populate(engine)  # nothing new to load
    if count_second_run != 0:
        failures.append(f"second populate() run should load 0 new rows, got {count_second_run}")

    with Session(engine) as session:
        total_facts = session.query(pw.FactAssessment).count()
        if total_facts != 2:
            failures.append(f"expected 2 total fact_assessment rows (one per assessment), got {total_facts}")

        donors = session.query(pw.DimDonor).filter_by(donor="USAID").all()
        if len(donors) != 1:
            failures.append(f"expected exactly 1 dim_donor row for USAID (shared, not duplicated), got {len(donors)}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: populate() is idempotent (re-running loads nothing new) and dimension rows "
          "are shared across assessments with the same donor/sector/org_type, never duplicated.")


def run_missing_dimensions_degrade_to_null():
    """An assessment with no donor/sector/org_type must still get a fact row,
    with the corresponding FKs left null -- never guessed. created_at's
    server_default makes forcing a true NULL through the ORM finicky, so
    _coerce_date()'s own None-handling is checked directly instead."""
    failures = []
    engine = _fresh_engine()
    aid = _seed_assessment(engine, donor=None, sector=None, org_type=None)

    pw.populate(engine)
    with Session(engine) as session:
        fact = session.query(pw.FactAssessment).filter_by(assessment_id=aid).first()
        if fact is None:
            failures.append("a bare assessment with no donor/sector/org_type should still get a fact row")
        elif (fact.donor_id, fact.sector_id, fact.org_type_id) != (None, None, None):
            failures.append(
                f"expected donor_id/sector_id/org_type_id all null, got "
                f"{(fact.donor_id, fact.sector_id, fact.org_type_id)}"
            )

    for bad_input in (None, "", "not a date"):
        if pw._coerce_date(bad_input) is not None:
            failures.append(f"_coerce_date({bad_input!r}) should return None, got {pw._coerce_date(bad_input)}")
    if pw._coerce_date("2025-07-15") != date(2025, 7, 15):
        failures.append(f"_coerce_date('2025-07-15') expected 2025-07-15, got {pw._coerce_date('2025-07-15')}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: missing donor/sector/org_type degrade to null dimension FKs, never guessed, "
          "never block the fact row from being written, and _coerce_date() handles "
          "None/empty/unparseable input safely.")


if __name__ == "__main__":
    run_populate_full()
    run_idempotent_and_shared_dimensions()
    run_missing_dimensions_degrade_to_null()
