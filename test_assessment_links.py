"""
test_assessment_links.py — golden tests for utils/assessment_links.py (Laudon Ch.12
Implementation-stage tracking, D3): recording a scoring run at evaluation time, linking a
revision to its parent, and computing the before/after delta.

No pytest, no real network calls: utils.assessment_links's own SQLAlchemy engine abstraction
is the seam to swap -- an in-memory SQLite engine stands in for the real Supabase Postgres
connection, same approach as test_outcomes.py/test_verification.py, since the same SQLAlchemy
models work unchanged against either dialect. Run with: python test_assessment_links.py
"""

from sqlalchemy import create_engine

import utils.assessment_links as assessment_links


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    assessment_links.Base.metadata.create_all(engine)
    return engine


def run_record_and_list():
    failures = []
    original_get_engine = assessment_links._get_engine
    engine = _fresh_engine()
    assessment_links._get_engine = lambda: engine
    email = "mel@example.com"
    try:
        assessment_links.record_assessment(
            "ASM-1", email, confidence_score=2.4, clarity_score=3.1, weakest_dimension="Directness")
        assessment_links.record_assessment(
            "ASM-2", email, confidence_score=3.8, clarity_score=3.9, weakest_dimension="Verification",
            parent_assessment_id="ASM-1")

        # A no-op call (missing email/assessment_id) must not write a row and must not raise.
        assessment_links.record_assessment("", email)
        assessment_links.record_assessment("ASM-3", "")

        recent = assessment_links.list_recent_assessments(email)
        if len(recent) != 2:
            failures.append(f"expected 2 recorded assessments for {email}, got {len(recent)}")
        if recent and recent[0]["assessment_id"] != "ASM-2":
            failures.append(f"list_recent_assessments should be newest-first, got {[r['assessment_id'] for r in recent]}")

        # A different email (different hash) must not see this user's assessments.
        other = assessment_links.list_recent_assessments("someone_else@example.com")
        if other:
            failures.append("list_recent_assessments leaked rows across different email hashes")
    finally:
        assessment_links._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_assessment/list_recent_assessments — hash isolation and newest-first ordering verified.")


def run_delta_computation():
    failures = []
    original_get_engine = assessment_links._get_engine
    engine = _fresh_engine()
    assessment_links._get_engine = lambda: engine
    email = "mel@example.com"
    try:
        assessment_links.record_assessment(
            "ASM-A", email, confidence_score=2.5, clarity_score=3.0, weakest_dimension="Directness")
        assessment_links.record_assessment(
            "ASM-B", email, confidence_score=3.9, clarity_score=3.4, weakest_dimension="Recency",
            parent_assessment_id="ASM-A")

        delta = assessment_links.get_delta("ASM-B")
        if not delta:
            failures.append("get_delta returned None for an assessment with a real parent link")
        else:
            if delta["parent_assessment_id"] != "ASM-A":
                failures.append(f"expected parent_assessment_id 'ASM-A', got {delta['parent_assessment_id']}")
            if delta["delta_confidence"] != 1.4:
                failures.append(f"expected delta_confidence 1.4 (3.9 - 2.5), got {delta['delta_confidence']}")
            if delta["delta_clarity"] != 0.4:
                failures.append(f"expected delta_clarity 0.4 (3.4 - 3.0), got {delta['delta_clarity']}")

        # An assessment with no parent link must return None, not a crash or a bogus delta.
        if assessment_links.get_delta("ASM-A") is not None:
            failures.append("get_delta should return None for an assessment with no parent_assessment_id")

        # A nonexistent assessment_id must return None, not raise.
        if assessment_links.get_delta("ASM-DOES-NOT-EXIST") is not None:
            failures.append("get_delta should return None for an unrecorded assessment_id")
    finally:
        assessment_links._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: get_delta — parent lookup, delta math, and no-parent/no-match handling verified.")


def run_never_raises_without_db():
    """Every function must degrade gracefully when SUPABASE_DB_URL isn't configured --
    matching every other utils/*.py module's convention. record_assessment() in particular
    is called unconditionally at evaluation time for every user, so it must never raise."""
    failures = []
    original_get_engine = assessment_links._get_engine
    assessment_links._get_engine = lambda: None
    try:
        assessment_links.record_assessment("ASM-1", "mel@example.com", confidence_score=3.0)
        if assessment_links.list_recent_assessments("mel@example.com") != []:
            failures.append("list_recent_assessments should return [] (not raise) with no DB engine")
        if assessment_links.get_delta("ASM-1") is not None:
            failures.append("get_delta should return None (not raise) with no DB engine")
    except Exception as exc:
        failures.append(f"a function raised instead of degrading gracefully without a DB engine: {exc}")
    finally:
        assessment_links._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-DB degradation — record_assessment/list_recent_assessments/get_delta never raise without a configured engine.")


def run_systemic_gap_streak():
    """D5 -- detect_systemic_gap_streak(): Laudon Ch.12 p.474 operational-
    intelligence pattern. Confirms the 3-in-a-row true positive, a
    mixed-dimension true negative, and the fewer-than-streak_length no-op."""
    failures = []
    original_get_engine = assessment_links._get_engine
    engine = _fresh_engine()
    assessment_links._get_engine = lambda: engine
    email = "mel@example.com"
    try:
        # Fewer than 3 assessments recorded -- must not claim a streak.
        assessment_links.record_assessment("ASM-1", email, weakest_dimension="Directness")
        if assessment_links.detect_systemic_gap_streak(email) is not None:
            failures.append("detect_systemic_gap_streak should return None with only 1 assessment recorded")

        assessment_links.record_assessment("ASM-2", email, weakest_dimension="Directness")
        if assessment_links.detect_systemic_gap_streak(email) is not None:
            failures.append("detect_systemic_gap_streak should return None with only 2 assessments recorded")

        # Third assessment shares the same weakest_dimension -- a genuine streak.
        assessment_links.record_assessment("ASM-3", email, weakest_dimension="Directness")
        streak = assessment_links.detect_systemic_gap_streak(email)
        if streak != "Directness":
            failures.append(f"expected a 'Directness' streak across ASM-1/2/3, got {streak!r}")

        # A 4th assessment with a DIFFERENT weakest_dimension breaks the streak
        # -- only the most recent 3 are considered, not any historical window.
        assessment_links.record_assessment("ASM-4", email, weakest_dimension="Verification")
        if assessment_links.detect_systemic_gap_streak(email) is not None:
            failures.append("a differing 4th assessment should break the streak over the most recent 3")

        # A different email (different hash) must never see this user's streak.
        if assessment_links.detect_systemic_gap_streak("someone_else@example.com") is not None:
            failures.append("detect_systemic_gap_streak leaked a streak across different email hashes")
    finally:
        assessment_links._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: systemic gap streak — 3-in-a-row detection, mixed-dimension negative, "
          "insufficient-history no-op, and hash isolation verified.")


if __name__ == "__main__":
    run_record_and_list()
    run_delta_computation()
    run_never_raises_without_db()
    run_systemic_gap_streak()
