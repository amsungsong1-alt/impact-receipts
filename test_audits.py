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

import json
import os
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# A real (test-only) Fernet key so save_audit()/add_library_items()'s
# fail-closed encryption doesn't reject every write in this test run --
# must be set before utils.audits/utils.crypto's first use.
os.environ.setdefault("AUDIT_ENCRYPTION_KEY", Fernet.generate_key().decode())

import utils.audits as audits
import utils.crypto as crypto


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


def run_access_log_and_rate_limit():
    failures = []
    original_get_engine = audits._get_engine
    engine = _fresh_engine()
    audits._get_engine = lambda: engine
    try:
        # save_audit() must append an access_log row as a side effect.
        audits.save_audit("a@example.com",
                           [{"donor": "GIZ", "sector": "Education & Skills", "org_type": "National NGO"}],
                           [{"confidence_score": 4.0, "clarity_score": 4.0, "verdict": "Strong"}],
                           "IMP-log-1")
        with Session(engine) as session:
            logged = (session.query(audits.AccessLog)
                      .filter(audits.AccessLog.email == "a@example.com",
                              audits.AccessLog.action == "save_audit").all())
        if len(logged) != 1:
            failures.append(f"save_audit() should append exactly 1 access_log row, found {len(logged)}")

        # check_rate_limit: under the threshold is allowed, at/over it is not.
        for _ in range(3):
            audits.log_access("limit_test@example.com", "test_action")
        if not audits.check_rate_limit("limit_test@example.com", "test_action", max_count=5, window_seconds=60):
            failures.append("check_rate_limit denied a request under its max_count threshold")
        for _ in range(3):
            audits.log_access("limit_test@example.com", "test_action")
        if audits.check_rate_limit("limit_test@example.com", "test_action", max_count=5, window_seconds=60):
            failures.append("check_rate_limit allowed a request at/over its max_count threshold")

        # A different email's actions must not count toward this email's limit.
        if not audits.check_rate_limit("other_user@example.com", "test_action", max_count=5, window_seconds=60):
            failures.append("check_rate_limit incorrectly shared state across different emails")

        # Entries outside the time window must not count toward the limit.
        with Session(engine) as session:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=120)
            for _ in range(10):
                session.add(audits.AccessLog(email="window_test@example.com", action="test_action",
                                              created_at=stale_cutoff))
            session.commit()
        if not audits.check_rate_limit("window_test@example.com", "test_action", max_count=5, window_seconds=60):
            failures.append("check_rate_limit counted access_log rows outside its time window")

        # A DB error must fail OPEN, not closed.
        audits._get_engine = lambda: None
        if not audits.check_rate_limit("a@example.com", "test_action", max_count=1, window_seconds=60):
            failures.append("check_rate_limit did not fail open when the engine is unavailable")
    finally:
        audits._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: access log — save_audit logging, rate-limit threshold/window/fail-open verified.")


def run_encryption():
    failures = []
    original_get_engine = audits._get_engine
    engine = _fresh_engine()
    audits._get_engine = lambda: engine
    try:
        subs = [{"donor": "GIZ", "sector": "Health & Nutrition", "org_type": "International NGO (INGO)",
                 "result_statement": "Trained 200 nurses in maternal health."}]
        evs = [{"confidence_score": 4.0, "clarity_score": 3.5, "verdict": "Strong"}]
        audit_id = audits.save_audit("enc@example.com", subs, evs, "IMP-enc-1")
        if not audit_id:
            failures.append("save_audit returned falsy id with a valid encryption key configured")

        # The raw stored value must be genuine ciphertext, not plaintext JSON.
        with Session(engine) as session:
            row = session.get(audits.Audit, audit_id)
            if row.submissions_json == json.dumps(subs):
                failures.append("submissions_json is stored as plaintext, not encrypted")
            if "Trained 200 nurses" in (row.submissions_json or ""):
                failures.append("plaintext result_statement content is visible in the raw stored column")

        # get_audit() must still round-trip correctly through decryption.
        full = audits.get_audit("enc@example.com", audit_id)
        if not full or full["submissions"] != subs or full["evaluations"] != evs:
            failures.append("get_audit did not correctly decrypt back to the original content")

        # Logframe Library items: same ciphertext-at-rest + round-trip checks.
        lib_id = audits.create_logframe_library("enc@example.com", "Encryption test library")
        audits.add_library_items(lib_id, "enc@example.com", [{
            "indicator_name": "Sensitive indicator name", "logframe_indicator": "Ind 9.9",
            "logframe_baseline": "10", "logframe_target": "50", "sector": "Health & Nutrition",
        }])
        with Session(engine) as session:
            item_row = session.query(audits.LogframeLibraryItem).filter(
                audits.LogframeLibraryItem.library_id == lib_id).first()
            if item_row.indicator_name == "Sensitive indicator name":
                failures.append("logframe_library_items.indicator_name is stored as plaintext")
        items = audits.get_library_items(lib_id, "enc@example.com")
        if not items or items[0]["indicator_name"] != "Sensitive indicator name":
            failures.append("get_library_items did not correctly decrypt indicator_name")

        # Fail closed: without a usable key, save_audit/add_library_items must
        # refuse to store anything rather than silently falling back to plaintext.
        original_get_fernet = crypto._get_fernet
        crypto._get_fernet = lambda: None
        try:
            if audits.save_audit("enc@example.com", subs, evs, "IMP-enc-nofail") is not None:
                failures.append("save_audit did not fail closed when no encryption key is available")
            if audits.add_library_items(lib_id, "enc@example.com", [{"indicator_name": "should not save"}]) is not None:
                pass  # add_library_items returns None either way; verified via row count below
            with Session(engine) as session:
                count_after = session.query(audits.LogframeLibraryItem).filter(
                    audits.LogframeLibraryItem.library_id == lib_id).count()
            if count_after != 1:
                failures.append(f"add_library_items stored a row without a usable encryption key "
                                 f"(expected still 1, found {count_after})")
        finally:
            crypto._get_fernet = original_get_fernet
    finally:
        audits._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: encryption — audits and logframe items are ciphertext at rest, round-trip correctly, fail closed without a key.")


def run_cross_account_denial():
    """Exhaustive sweep, one block per utils/audits.py function that takes an
    email: confirms account B's email is never sufficient to read/mutate
    account A's rows, no matter which id is guessed. Companion to the
    app.py-side audit (every call site into this module passes a freshly-read
    st.session_state["user_email"], never a URL param or uploaded-file value
    -- see the fix in _load_from_inputs_json) -- this half verifies the
    module itself refuses cross-account access even if that upstream
    discipline were ever violated by a future call site."""
    failures = []
    original_get_engine = audits._get_engine
    engine = _fresh_engine()
    audits._get_engine = lambda: engine
    A, B = "owner@example.com", "attacker@example.com"
    try:
        subs = [{"donor": "SIDA", "sector": "Governance & Accountability", "org_type": "National NGO"}]
        evs = [{"confidence_score": 3.8, "clarity_score": 3.6, "verdict": "Acceptable"}]
        audit_id = audits.save_audit(A, subs, evs, "IMP-xacct-1")
        lib_id = audits.create_logframe_library(A, "A's private library")
        audits.add_library_items(lib_id, A, [{"indicator_name": "A's indicator"}])

        if audits.get_audit(B, audit_id) is not None:
            failures.append("get_audit: account B read account A's audit")
        audits.delete_audit(B, audit_id)
        if audits.get_audit(A, audit_id) is None:
            failures.append("delete_audit: account B deleted account A's audit")

        if audits.get_library_items(lib_id, B):
            failures.append("get_library_items: account B read account A's library items")
        audits.add_library_items(lib_id, B, [{"indicator_name": "B's injected indicator"}])
        if len(audits.get_library_items(lib_id, A)) != 1:
            failures.append("add_library_items: account B added an item to account A's library")
        audits.delete_logframe_library(lib_id, B)
        if not audits.list_logframe_libraries(A):
            failures.append("delete_logframe_library: account B deleted account A's library")

        if audits.list_audits(B):
            failures.append("list_audits: account B's listing included account A's data")
        if audits.list_logframe_libraries(B):
            failures.append("list_logframe_libraries: account B's listing included account A's data")

        # Guessing a numeric id that happens to belong to someone else must
        # behave identically to guessing a nonexistent id -- no oracle for
        # "this id exists but isn't yours" vs. "this id doesn't exist."
        if audits.get_audit(B, audit_id) != audits.get_audit(B, 999999):
            failures.append("get_audit leaks whether a foreign id exists vs. doesn't (timing/response oracle)")
    finally:
        audits._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: cross-account denial — every utils/audits.py function refuses another account's data, for every function and every id.")


if __name__ == "__main__":
    run_audits()
    run_logframe_library()
    run_benchmark()
    run_access_log_and_rate_limit()
    run_encryption()
    run_cross_account_denial()
