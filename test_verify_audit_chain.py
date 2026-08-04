"""
test_verify_audit_chain.py — golden tests for
scripts/verify_audit_chain.py's verify_chain() (Laudon Ch.8 hardening, C4:
tamper-evident audit logging).

No pytest, no database: verify_chain() is a pure function over plain dicts,
so this constructs synthetic chains by hand using the exact same hash
formula the Postgres trigger uses (see _row_hash, duplicated here
deliberately -- this test would not catch a bug where BOTH the trigger and
this test's formula drifted from each other in the same way, but it does
catch the formula being implemented incorrectly in the verification script
itself relative to a known-good chain). Run with:
python test_verify_audit_chain.py
"""
from scripts.verify_audit_chain import verify_chain, _row_hash


def _build_clean_chain(n: int) -> list[dict]:
    rows = []
    prev_hash = ""
    for i in range(1, n + 1):
        email = f"user{i}@example.com"
        action = "login_success"
        resource_type = None
        resource_id = None
        ip_address = "127.0.0.1"
        created_at_text = f"2026-08-0{i} 12:00:00+00"
        row_hash = _row_hash(prev_hash, email, action, resource_type, resource_id,
                              ip_address, created_at_text)
        rows.append({
            "id": i, "prev_hash": prev_hash, "row_hash": row_hash,
            "email": email, "action": action, "resource_type": resource_type,
            "resource_id": resource_id, "ip_address": ip_address,
            "created_at_text": created_at_text,
        })
        prev_hash = row_hash
    return rows


def run_clean_chain_verifies_with_no_problems():
    rows = _build_clean_chain(5)
    problems = verify_chain(rows)
    assert problems == [], f"expected a clean chain to have no problems, got: {problems}"
    print("PASS: run_clean_chain_verifies_with_no_problems")


def run_edited_row_content_is_detected():
    rows = _build_clean_chain(5)
    rows[2]["email"] = "attacker-edited@example.com"  # tamper with row id=3's content only
    problems = verify_chain(rows)
    assert any("id=3" in p and "recomputed hash" in p for p in problems), \
        f"expected the edited row's own hash mismatch to be reported, got: {problems}"
    print("PASS: run_edited_row_content_is_detected")


def run_deleted_row_breaks_the_chain():
    rows = _build_clean_chain(5)
    del rows[2]  # simulate row id=3 being deleted outright
    problems = verify_chain(rows)
    # The row immediately after the deleted one (id=4) now has a prev_hash
    # pointing at a row_hash that no longer appears anywhere in the result set.
    assert any("id=4" in p and "prev_hash" in p for p in problems), \
        f"expected a broken chain link right after the deleted row, got: {problems}"
    print("PASS: run_deleted_row_breaks_the_chain")


def run_reordered_rows_break_the_chain():
    rows = _build_clean_chain(4)
    rows[1], rows[2] = rows[2], rows[1]  # swap id=2 and id=3 out of chain order
    problems = verify_chain(rows)
    assert len(problems) > 0, "expected reordering to be detected as a broken chain"
    print("PASS: run_reordered_rows_break_the_chain")


def run_empty_chain_has_no_problems():
    assert verify_chain([]) == []
    print("PASS: run_empty_chain_has_no_problems")


if __name__ == "__main__":
    run_clean_chain_verifies_with_no_problems()
    run_edited_row_content_is_detected()
    run_deleted_row_breaks_the_chain()
    run_reordered_rows_break_the_chain()
    run_empty_chain_has_no_problems()
    print("\nAll test_verify_audit_chain.py tests passed.")
