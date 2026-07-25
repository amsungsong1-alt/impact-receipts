"""
test_verification.py — golden tests for utils/verification.py (reference-ID verification
lookup for exported documents: recording an export at download time, and looking it up from
the public ?verify= landing page).

No pytest, no real network calls: utils.verification's own SQLAlchemy engine abstraction is
the seam to swap -- an in-memory SQLite engine stands in for the real Supabase Postgres
connection, same approach as test_outcomes.py/test_audits.py/test_crm.py, since the same
SQLAlchemy models work unchanged against either dialect. Run with: python test_verification.py
"""

from sqlalchemy import create_engine

import utils.verification as verification


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    verification.Base.metadata.create_all(engine)
    return engine


def run_content_hash_determinism():
    """compute_content_hash() must be deterministic (same inputs -> same digest, so a
    future v2 re-hash-and-compare stays possible), normalize case/whitespace (a donor
    re-typing or re-pasting shouldn't produce a different hash), and be sensitive to a
    genuinely different score or statement (not just always returning a constant)."""
    failures = []

    h1 = verification.compute_content_hash("Trained 487 farmers.", "Attendance sheets.", "Attendance sheets / participant registers", 4.7, 4.2)
    h2 = verification.compute_content_hash("Trained 487 farmers.", "Attendance sheets.", "Attendance sheets / participant registers", 4.7, 4.2)
    if h1 != h2:
        failures.append("compute_content_hash is not deterministic for identical inputs")

    h3 = verification.compute_content_hash("  TRAINED 487 farmers.  ", "  ATTENDANCE sheets.  ", "Attendance sheets / participant registers", 4.7, 4.2)
    if h1 != h3:
        failures.append("compute_content_hash should normalize case/whitespace, but differing case/padding changed the hash")

    h4 = verification.compute_content_hash("Trained 500 farmers.", "Attendance sheets.", "Attendance sheets / participant registers", 4.7, 4.2)
    if h1 == h4:
        failures.append("compute_content_hash should differ for a genuinely different result statement")

    h5 = verification.compute_content_hash("Trained 487 farmers.", "Attendance sheets.", "Attendance sheets / participant registers", 3.1, 4.2)
    if h1 == h5:
        failures.append("compute_content_hash should differ for a genuinely different confidence_score")

    if len(h1) != 64:
        failures.append(f"expected a 64-hex-char SHA-256 digest, got length {len(h1)}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_content_hash — deterministic, normalized, and input-sensitive.")


def run_record_and_verify():
    failures = []
    original_get_engine = verification._get_engine
    engine = _fresh_engine()
    verification._get_engine = lambda: engine
    try:
        content_hash = verification.compute_content_hash(
            "Trained 487 farmers.", "Attendance sheets.",
            "Attendance sheets / participant registers", 4.7, 4.2,
        )
        verification.record_export(
            "IMP-20260101_000000", "readiness_card", content_hash,
            confidence_score=4.7, clarity_score=4.2, score_band="Strong",
        )

        # An unrecognized export_type must be silently rejected (no row written).
        verification.record_export("XYZ-99999999_999999", "not_a_real_export_type", content_hash)

        found = verification.verify_ref_id("IMP-20260101_000000")
        if not found:
            failures.append("verify_ref_id did not find a ref_id that was just recorded")
        else:
            if found["export_type"] != "readiness_card":
                failures.append(f"expected export_type 'readiness_card', got {found['export_type']}")
            if found["confidence_score"] != 4.7 or found["clarity_score"] != 4.2:
                failures.append(f"scores did not round-trip: {found}")
            if found["score_band"] != "Strong":
                failures.append(f"expected score_band 'Strong', got {found['score_band']}")
            # The verify landing page must never be able to reconstruct raw
            # submission content from what verify_ref_id() returns.
            if "content_hash" in found or "result_statement" in found:
                failures.append("verify_ref_id leaked the content hash or raw content -- should only return printed-on-document fields")

        # A ref_id that was never recorded (or rejected for an unrecognized
        # export_type) must return None -- never distinguishing "malformed" from
        # "right format, no row" (same convention as app.py's unsubscribe landing).
        if verification.verify_ref_id("IMP-99999999_999999") is not None:
            failures.append("verify_ref_id should return None for an unrecorded ref_id")
        if verification.verify_ref_id("XYZ-99999999_999999") is not None:
            failures.append("verify_ref_id found a row for a ref_id whose export_type was rejected at record time")
        if verification.verify_ref_id("") is not None:
            failures.append("verify_ref_id('') should return None, not raise or match everything")
    finally:
        verification._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_export/verify_ref_id — round-trip, allowlist enforcement, and no-match handling verified.")


def run_never_raises_without_db():
    """Every function must degrade gracefully when SUPABASE_DB_URL isn't configured
    (_get_engine() returns None) -- matching every other utils/*.py module's convention."""
    failures = []
    original_get_engine = verification._get_engine
    verification._get_engine = lambda: None
    try:
        verification.record_export("IMP-1", "readiness_card", "somehash")  # must not raise
        if verification.verify_ref_id("IMP-1") is not None:
            failures.append("verify_ref_id should return None (not raise) when no DB engine is available")
    except Exception as exc:
        failures.append(f"a function raised instead of degrading gracefully without a DB engine: {exc}")
    finally:
        verification._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-DB degradation — record_export/verify_ref_id never raise without a configured engine.")


if __name__ == "__main__":
    run_content_hash_determinism()
    run_record_and_verify()
    run_never_raises_without_db()
