"""
test_warehouse.py — golden tests for utils/warehouse.py (Laudon Ch.6 Phase 2,
C5): OLAP slice/dice queries over the star-schema warehouse.

No pytest, no network calls. In-memory SQLite engine, same convention as
test_populate_warehouse.py -- slice_by() accepts an explicit engine
parameter, so no monkeypatching of module globals is needed here. Run with:
python test_warehouse.py
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import scripts.populate_warehouse as pw
import utils.warehouse as wh


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    pw.Base.metadata.create_all(engine)
    return engine


def _seed_fact(engine, donor: str = None, **overrides):
    defaults = dict(
        assessment_id=1, confidence_score=4.0, clarity_score=3.5,
        verdict="Strong KPI", criteria_passed_count=6, criteria_failed_count=2,
    )
    defaults.update(overrides)
    with Session(engine) as session:
        donor_id = pw._get_or_create(session, pw.DimDonor, "donor", donor)
        session.add(pw.FactAssessment(donor_id=donor_id, **defaults))
        session.commit()


def run_slice_by_donor_sample_gate():
    """Below MIN_SLICE_SAMPLE, a bucket must not appear at all -- avoids a
    misleading average from a near-empty group."""
    failures = []
    engine = _fresh_engine()

    for i in range(wh.MIN_SLICE_SAMPLE - 1):
        _seed_fact(engine, assessment_id=100 + i, donor="USAID", confidence_score=4.0)
    result = wh.slice_by("donor", engine=engine)
    if result:
        failures.append(f"expected no rows below MIN_SLICE_SAMPLE, got {result}")

    # One more pushes USAID to exactly MIN_SLICE_SAMPLE -- now it must appear.
    _seed_fact(engine, assessment_id=999, donor="USAID", confidence_score=4.0)
    result2 = wh.slice_by("donor", engine=engine)
    if len(result2) != 1 or result2[0]["label"] != "USAID" or result2[0]["n"] != wh.MIN_SLICE_SAMPLE:
        failures.append(f"expected exactly 1 USAID row at n={wh.MIN_SLICE_SAMPLE}, got {result2}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print(f"PASS: slice_by('donor') withholds buckets below MIN_SLICE_SAMPLE ({wh.MIN_SLICE_SAMPLE}) "
          "and includes them once the threshold is reached.")


def run_slice_by_aggregates_correct():
    failures = []
    engine = _fresh_engine()
    scores = [(4.0, 3.0, 8, 2), (2.0, 5.0, 4, 6)]
    for i, (conf, clar, passed, failed) in enumerate(scores * 5):  # 10 rows total
        _seed_fact(engine, assessment_id=200 + i, donor="FCDO",
                   confidence_score=conf, clarity_score=clar,
                   criteria_passed_count=passed, criteria_failed_count=failed)

    result = wh.slice_by("donor", engine=engine)
    if len(result) != 1:
        failures.append(f"expected exactly 1 donor bucket, got {result}")
    else:
        row = result[0]
        if row["avg_confidence"] != 3.0:  # mean of 4.0 and 2.0
            failures.append(f"expected avg_confidence 3.0, got {row['avg_confidence']}")
        if row["avg_clarity"] != 4.0:  # mean of 3.0 and 5.0
            failures.append(f"expected avg_clarity 4.0, got {row['avg_clarity']}")
        # pass_rate: (8/10 + 4/10)/2 = 0.6
        if row["pass_rate"] != 0.6:
            failures.append(f"expected pass_rate 0.6, got {row['pass_rate']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: slice_by('donor') computes correct avg_confidence/avg_clarity/pass_rate "
          "across a mixed set of fact rows.")


def run_degrades_gracefully():
    failures = []

    # Unknown dimension -- empty list, never raises.
    if wh.slice_by("not_a_real_dimension", engine=_fresh_engine()) != []:
        failures.append("an unknown dimension should return an empty list")

    # No engine at all -- empty list, never raises.
    try:
        result = wh.slice_by("donor", engine=None)
    except Exception as e:
        failures.append(f"slice_by() with no engine must never raise, got {e!r}")
    else:
        original_get_engine = wh._get_engine
        wh._get_engine = lambda: None
        try:
            if wh.slice_by("donor") != []:
                failures.append("no configured engine should return an empty list")
        finally:
            wh._get_engine = original_get_engine

    # Warehouse tables don't exist yet -- a bare engine with no tables created
    # must degrade to an empty list, not raise (this is the actual production
    # state today: 0055 is not applied anywhere).
    import sqlalchemy
    bare_engine = sqlalchemy.create_engine("sqlite:///:memory:")
    try:
        if wh.slice_by("donor", engine=bare_engine) != []:
            failures.append("a missing fact_assessment table should degrade to an empty list")
    except Exception as e:
        failures.append(f"slice_by() against a database with no warehouse tables must never raise, got {e!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: slice_by() degrades to an empty list for an unknown dimension, a missing engine, "
          "and a database where the warehouse tables don't exist yet -- never raises.")


if __name__ == "__main__":
    run_slice_by_donor_sample_gate()
    run_slice_by_aggregates_correct()
    run_degrades_gracefully()
