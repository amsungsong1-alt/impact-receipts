"""
test_indicator_stewardship.py — golden tests for
utils/indicator_stewardship.py (Laudon Ch.6 Phase 2, C7 register half).

No pytest, no network calls. In-memory SQLite engine, same convention as
test_assessment_facts.py/test_populate_warehouse.py. Run with:
python test_indicator_stewardship.py
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.assessment_facts as af
import utils.indicator_stewardship as ist
from metrics import session_hash


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    af.Base.metadata.create_all(engine)
    return engine


def _seed(engine, email: str, indicator_name: str, target: str, baseline: str = "10%") -> None:
    with Session(engine) as session:
        a = af.Assessment(user_hash=session_hash(email))
        session.add(a)
        session.flush()
        session.add(af.Indicator(
            assessment_id=a.id, indicator_name=indicator_name,
            logframe_target=target, logframe_baseline=baseline,
        ))
        session.commit()


def run_flags_inconsistent_targets():
    failures = []
    engine = _fresh_engine()
    email = "org@example.com"
    _seed(engine, email, "% of households with clean water", "60%")
    _seed(engine, email, "% of households with clean water", "75%")  # inconsistent target
    _seed(engine, email, "% of farmers trained", "500")
    _seed(engine, email, "% of farmers trained", "500")  # consistent -- same target

    findings = ist.find_indicator_inconsistencies(email, engine=engine)
    names = {f["indicator_name"] for f in findings}
    if "% of households with clean water" not in names:
        failures.append(f"expected the clean-water indicator flagged for inconsistent targets, got {findings}")
    if "% of farmers trained" in names:
        failures.append("the farmers-trained indicator has identical targets across both uses -- should NOT be flagged")

    water_finding = next((f for f in findings if f["indicator_name"] == "% of households with clean water"), None)
    if water_finding and water_finding["distinct_targets"] != ["60%", "75%"]:
        failures.append(f"expected distinct_targets ['60%', '75%'], got {water_finding['distinct_targets']}")
    if water_finding and water_finding["use_count"] != 2:
        failures.append(f"expected use_count 2, got {water_finding['use_count']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: find_indicator_inconsistencies — flags an indicator name reused with different "
          "targets, does NOT flag one reused with identical targets, and reports the distinct values.")


def run_single_use_never_flagged():
    """An indicator used only once has nothing to be inconsistent with."""
    failures = []
    engine = _fresh_engine()
    email = "solo@example.com"
    _seed(engine, email, "% of villages with sanitation", "40%")

    findings = ist.find_indicator_inconsistencies(email, engine=engine)
    if findings:
        failures.append(f"a single-use indicator should never be flagged, got {findings}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: an indicator used only once is never flagged (MIN_USES_TO_FLAG gate).")


def run_account_isolation():
    """Two accounts using the same indicator name with different targets
    must NOT leak into each other's findings -- each account's register is
    scoped to its own user_hash."""
    failures = []
    engine = _fresh_engine()
    _seed(engine, "org_a@example.com", "% trained", "100")
    _seed(engine, "org_a@example.com", "% trained", "100")  # consistent within org_a
    _seed(engine, "org_b@example.com", "% trained", "999")  # org_b's own, different value, single use

    findings_a = ist.find_indicator_inconsistencies("org_a@example.com", engine=engine)
    findings_b = ist.find_indicator_inconsistencies("org_b@example.com", engine=engine)
    if findings_a:
        failures.append(f"org_a's uses are internally consistent -- should be flag-free, got {findings_a}")
    if findings_b:
        failures.append(f"org_b has only 1 use -- should be flag-free, got {findings_b}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: findings are isolated per account via user_hash -- one account's indicator usage "
          "never leaks into or affects another account's register.")


def run_degrades_gracefully():
    failures = []
    engine = _fresh_engine()

    if ist.find_indicator_inconsistencies("", engine=engine) != []:
        failures.append("an empty email should return an empty list")

    try:
        result = ist.find_indicator_inconsistencies("x@example.com", engine=None)
    except Exception as e:
        failures.append(f"must never raise with no configured engine, got {e!r}")
    else:
        original_get_engine = ist._get_engine
        ist._get_engine = lambda: None
        try:
            if ist.find_indicator_inconsistencies("x@example.com") != []:
                failures.append("no configured engine should return an empty list")
        finally:
            ist._get_engine = original_get_engine

    # A database missing the assessments/indicators tables entirely.
    import sqlalchemy
    bare_engine = sqlalchemy.create_engine("sqlite:///:memory:")
    try:
        if ist.find_indicator_inconsistencies("x@example.com", engine=bare_engine) != []:
            failures.append("missing tables should degrade to an empty list")
    except Exception as e:
        failures.append(f"must never raise when the indicators/assessments tables don't exist yet, got {e!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: degrades gracefully — empty email, no engine, and missing tables all return "
          "an empty list rather than raising.")


if __name__ == "__main__":
    run_flags_inconsistent_targets()
    run_single_use_never_flagged()
    run_account_isolation()
    run_degrades_gracefully()
