"""
test_audits.py — golden tests for utils/audits.py (saved audit history,
Logframe Library, and the anonymized benchmark).

No pytest, no real network calls, no real Postgres project: utils.audits's
own SQLAlchemy engine abstraction is the seam to swap -- an in-memory SQLite
engine (sqlite:///:memory:) stands in for the real Supabase Postgres
connection, with utils.audits.Base.metadata.create_all() building matching
tables. Simpler than test_billing.py's hand-rolled Supabase REST fake, since
the same SQLAlchemy models work unchanged against either dialect. Run with:
python test_audits.py
"""

from sqlalchemy import create_engine

import utils.audits as audits


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    audits.Base.metadata.create_all(engine)
    return engine


def run_audits():
    failures = []
    original_get_engine = audits._get_engine
    engine = _fresh_engine()
    audits._get_engine = lambda: engine
    try:
        subs = [{"donor": "USAID", "sector": "WASH", "org_type": "International NGO (INGO)"}]
        evs = [{"confidence_score": 4.2, "clarity_score": 3.9, "verdict": "Strong"}]

        audit_id = audits.save_audit("a@example.com", subs, evs, "IMP-1")
        if not audit_id:
            failures.append("save_audit returned falsy id for a valid save")

        listed = audits.list_audits("a@example.com")
        if len(listed) != 1:
            failures.append(f"list_audits expected 1 row, got {len(listed)}")
        elif listed[0]["ref_id"] != "IMP-1":
            failures.append(f"list_audits ref_id mismatch: {listed[0]['ref_id']}")

        # email-scoping: a different account must not see or fetch this audit
        other_listed = audits.list_audits("b@example.com")
        if other_listed:
            failures.append("list_audits leaked another account's audit")
        if audits.get_audit("b@example.com", audit_id) is not None:
            failures.append("get_audit returned a row for the wrong email")

        full = audits.get_audit("a@example.com", audit_id)
        if not full or full["submissions"] != subs or full["evaluations"] != evs:
            failures.append("get_audit did not round-trip submissions/evaluations JSON")

        # a second save with the same ref_id must fail gracefully (unique constraint), not crash
        dup = audits.save_audit("a@example.com", subs, evs, "IMP-1")
        if dup is not None:
            failures.append("save_audit did not reject a duplicate ref_id")

        # delete is scoped to the owning email
        audits.delete_audit("b@example.com", audit_id)
        if audits.get_audit("a@example.com", audit_id) is None:
            failures.append("delete_audit deleted a row for the wrong email")
        audits.delete_audit("a@example.com", audit_id)
        if audits.get_audit("a@example.com", audit_id) is not None:
            failures.append("delete_audit did not delete the owner's own audit")
    finally:
        audits._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: audits — save/list/get/delete round-trip and email-scoping verified.")


def run_logframe_library():
    failures = []
    original_get_engine = audits._get_engine
    engine = _fresh_engine()
    audits._get_engine = lambda: engine
    try:
        lib_id = audits.create_logframe_library("a@example.com", "USAID WASH 2025")
        if not lib_id:
            failures.append("create_logframe_library returned falsy id")

        libs = audits.list_logframe_libraries("a@example.com")
        if len(libs) != 1 or libs[0]["name"] != "USAID WASH 2025":
            failures.append(f"list_logframe_libraries unexpected result: {libs}")

        items = [
            {"indicator_name": "% households with safe water", "logframe_indicator": "Ind 1.1",
             "logframe_baseline": "40%", "logframe_target": "80%", "sector": "WASH"},
            {"indicator_name": "# boreholes rehabilitated", "logframe_indicator": "Ind 1.2",
             "logframe_baseline": "0", "logframe_target": "25", "sector": "WASH"},
        ]
        audits.add_library_items(lib_id, "a@example.com", items)

        # ownership guard: a different email must not be able to add items or read them
        audits.add_library_items(lib_id, "b@example.com", items)
        fetched_wrong_owner = audits.get_library_items(lib_id, "b@example.com")
        if fetched_wrong_owner:
            failures.append("get_library_items returned rows for a non-owning email")

        fetched = audits.get_library_items(lib_id, "a@example.com")
        if len(fetched) != 2:
            failures.append(f"get_library_items expected 2 items (owner-only add should have "
                             f"succeeded once, attacker add should have been a no-op), got {len(fetched)}")

        audits.delete_logframe_library(lib_id, "b@example.com")
        if not audits.list_logframe_libraries("a@example.com"):
            failures.append("delete_logframe_library deleted a library for the wrong email")
        audits.delete_logframe_library(lib_id, "a@example.com")
        if audits.list_logframe_libraries("a@example.com"):
            failures.append("delete_logframe_library did not delete the owner's own library")
    finally:
        audits._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: logframe library — create/list/add/get/delete and ownership scoping verified.")


def run_benchmark():
    failures = []
    original_get_engine = audits._get_engine
    engine = _fresh_engine()
    audits._get_engine = lambda: engine
    try:
        # below the sample-size threshold: no benchmark should be returned
        for i in range(3):
            audits.save_audit(f"u{i}@example.com",
                               [{"donor": "FCDO", "sector": "Health & Nutrition", "org_type": "National NGO"}],
                               [{"confidence_score": 3.0, "clarity_score": 3.0, "verdict": "Acceptable"}],
                               f"IMP-below-{i}")
        below = audits.get_benchmark("FCDO", "Health & Nutrition", "National NGO", 3.0, 3.0)
        if below is not None:
            failures.append(f"get_benchmark returned a result below MIN_BENCHMARK_SAMPLE: {below}")

        # cross the threshold with a known distribution: confidence scores 1.0..10.0
        for i in range(3, audits.MIN_BENCHMARK_SAMPLE + 2):
            score = float(i)
            audits.save_audit(f"u{i}@example.com",
                               [{"donor": "FCDO", "sector": "Health & Nutrition", "org_type": "National NGO"}],
                               [{"confidence_score": score, "clarity_score": score, "verdict": "Acceptable"}],
                               f"IMP-above-{i}")

        result = audits.get_benchmark("FCDO", "Health & Nutrition", "National NGO", 3.0, 3.0)
        if result is None:
            failures.append("get_benchmark returned None at/above MIN_BENCHMARK_SAMPLE")
        elif result["sample_size"] < audits.MIN_BENCHMARK_SAMPLE:
            failures.append(f"get_benchmark sample_size too low: {result['sample_size']}")

        # a bucket that has never had a save must return None, not raise
        empty = audits.get_benchmark("World Bank", "Governance & Accountability",
                                      "Community-Based Organisation (CBO)", 3.5, 3.5)
        if empty is not None:
            failures.append(f"get_benchmark returned a result for a bucket with zero audits: {empty}")

        # a different (donor, sector, org_type) triple must not share the FCDO bucket's data
        cross_bucket = audits.get_benchmark("FCDO", "Health & Nutrition",
                                             "International NGO (INGO)", 3.0, 3.0)
        if cross_bucket is not None:
            failures.append("get_benchmark leaked scores across a different org_type bucket")
    finally:
        audits._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: benchmark — sample-size gate, bucket isolation, and recompute-on-save verified.")


if __name__ == "__main__":
    run_audits()
    run_logframe_library()
    run_benchmark()
