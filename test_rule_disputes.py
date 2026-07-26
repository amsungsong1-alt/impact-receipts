"""
test_rule_disputes.py — golden tests for utils/rule_disputes.py (Laudon Ch.11 organisational
learning loop, C6): recording a dispute against an expert-system rule's firing, and the
dispute-count ranking for the hidden admin view.

No pytest, no real network calls: utils.rule_disputes's own SQLAlchemy engine abstraction is
the seam to swap -- an in-memory SQLite engine stands in for the real Supabase Postgres
connection, same approach as test_outcomes.py/test_assessment_links.py. Run with:
python test_rule_disputes.py
"""

from sqlalchemy import create_engine

import utils.rule_disputes as rule_disputes


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    rule_disputes.Base.metadata.create_all(engine)
    return engine


def run_record_and_count():
    failures = []
    original_get_engine = rule_disputes._get_engine
    engine = _fresh_engine()
    rule_disputes._get_engine = lambda: engine
    try:
        rule_disputes.record_dispute(
            "directness_no_primary_record", "mel@example.com",
            reason="too strict for this evidence type", rule_base_version="2026.07.1",
        )
        rule_disputes.record_dispute(
            "directness_no_primary_record", "other@example.com", reason="agree with the rule but not the wording",
        )
        rule_disputes.record_dispute("verification_no_reviewer", "mel@example.com")

        # No-op calls (missing rule_id/email) must not write a row and must not raise.
        rule_disputes.record_dispute("", "mel@example.com")
        rule_disputes.record_dispute("some_rule", "")

        counts = rule_disputes.get_dispute_counts()
        counts_by_id = {c["rule_id"]: c["count"] for c in counts}
        if counts_by_id.get("directness_no_primary_record") != 2:
            failures.append(f"expected 2 disputes for directness_no_primary_record, got {counts_by_id}")
        if counts_by_id.get("verification_no_reviewer") != 1:
            failures.append(f"expected 1 dispute for verification_no_reviewer, got {counts_by_id}")

        # Sorted descending by count.
        if counts[0]["rule_id"] != "directness_no_primary_record":
            failures.append(f"expected the rule with more disputes first, got {counts}")
    finally:
        rule_disputes._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_dispute/get_dispute_counts — round-trip, no-op on missing fields, "
          "and descending sort verified.")


def run_hash_never_stores_plaintext_email():
    """A dispute row must never carry a recoverable plaintext email -- only
    metrics.session_hash()'s one-way hash, same discipline as
    utils.outcomes.py/utils.assessment_links.py."""
    failures = []
    original_get_engine = rule_disputes._get_engine
    engine = _fresh_engine()
    rule_disputes._get_engine = lambda: engine
    email = "very_identifiable_person@example.com"
    try:
        rule_disputes.record_dispute("some_rule_id", email, reason="test")
        from sqlalchemy.orm import Session
        with Session(engine) as session:
            row = session.query(rule_disputes.RuleDispute).first()
            if row is None:
                failures.append("expected one row to be written")
            elif email in (row.user_hash or ""):
                failures.append("the plaintext email leaked into the stored user_hash")
            elif row.user_hash != __import__("metrics").session_hash(email):
                failures.append("user_hash does not match metrics.session_hash(email)")
    finally:
        rule_disputes._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: dispute rows store only a one-way session hash, never the plaintext email.")


def run_never_raises_without_db():
    """Every function must degrade gracefully when SUPABASE_DB_URL isn't
    configured -- matching every other utils/*.py module's convention."""
    failures = []
    original_get_engine = rule_disputes._get_engine
    rule_disputes._get_engine = lambda: None
    try:
        rule_disputes.record_dispute("some_rule", "mel@example.com")  # must not raise
        if rule_disputes.get_dispute_counts() != []:
            failures.append("get_dispute_counts should return [] (not raise) with no DB engine")
    except Exception as exc:
        failures.append(f"a function raised instead of degrading gracefully without a DB engine: {exc}")
    finally:
        rule_disputes._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-DB degradation — record_dispute/get_dispute_counts never raise without a configured engine.")


if __name__ == "__main__":
    run_record_and_count()
    run_hash_never_stores_plaintext_email()
    run_never_raises_without_db()
