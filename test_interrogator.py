"""
test_interrogator.py — golden tests for utils/interrogator.py (Laudon Ch.11
Donor Interrogator, C4): question selection over knowledge/donor_questions.yaml.

No pytest, no network calls. Run with: python test_interrogator.py
"""

from utils import interrogator


def _trace(criterion: str, fired: bool = True) -> dict:
    return {"rule_id": f"{criterion.lower()}_test_rule", "criterion": criterion, "fired": fired,
            "rationale": "test", "source": "test"}


def run_real_question_for_covered_pair():
    """USAID/Verification has real donor_templates.py-grounded content --
    a fired Verification rule with a filled-in verified_by field must return
    a real, non-declined question."""
    failures = []
    submission = {"evidence": [{"description": "site visit report", "verified_by": "external auditor",
                                 "recency": "2026-01", "type": "Document"}]}
    rule_trace = [_trace("Verification")]

    results = interrogator.select_questions(rule_trace, "USAID", submission)
    if len(results) != 1:
        failures.append(f"expected exactly 1 result, got {len(results)}: {results}")
    else:
        item = results[0]
        if item.get("declined"):
            failures.append(f"expected a real question for USAID/Verification, got a decline: {item}")
        if not item.get("question"):
            failures.append("expected non-empty question text")
        if item.get("criterion") != "Verification":
            failures.append(f"expected criterion Verification, got {item.get('criterion')}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a covered (donor, criterion) pair with real evidence returns a real question.")


def run_declines_gracefully_for_uncovered_pair():
    """World Bank has no Verification content in donor_templates.py -- must
    decline, never invent a filler question."""
    failures = []
    submission = {"evidence": [{"description": "baseline/endline data", "verified_by": "internal team",
                                 "recency": "2026-01", "type": "Document"}]}
    rule_trace = [_trace("Verification")]

    results = interrogator.select_questions(rule_trace, "World Bank", submission)
    if len(results) != 1:
        failures.append(f"expected exactly 1 result, got {len(results)}: {results}")
    else:
        item = results[0]
        if not item.get("declined"):
            failures.append(f"expected a decline for World Bank/Verification (no content), got: {item}")
        if "question" in item:
            failures.append("a declined entry must not carry a question field")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: an uncovered (donor, criterion) pair declines gracefully, never invents a question.")


def run_declines_gracefully_for_uncertain_field():
    """Even for a covered pair (USAID/Directness), an uncertain evidence
    description means there's nothing real to ask about yet."""
    failures = []
    submission = {"evidence": [{"description": "Not found", "verified_by": "external auditor",
                                 "recency": "2026-01", "type": "Document"}]}
    rule_trace = [_trace("Directness")]

    results = interrogator.select_questions(rule_trace, "USAID", submission)
    if len(results) != 1:
        failures.append(f"expected exactly 1 result, got {len(results)}: {results}")
    else:
        item = results[0]
        if not item.get("declined"):
            failures.append(f"expected a decline when the evidence description is uncertain, got: {item}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: an uncertain extracted field declines gracefully, even for a covered pair.")


def run_never_raises_on_unknown_donor():
    failures = []
    submission = {"evidence": [{"description": "some evidence", "verified_by": "someone",
                                 "recency": "2026-01", "type": "Document"}]}
    rule_trace = [_trace("Directness"), _trace("Verification")]

    try:
        results = interrogator.select_questions(rule_trace, "Not A Real Donor", submission)
    except Exception as e:
        failures.append(f"select_questions() raised on an unknown donor: {e!r}")
        results = []

    if len(results) != 2:
        failures.append(f"expected one decline per fired criterion, got {len(results)}: {results}")
    else:
        if not all(r.get("declined") for r in results):
            failures.append(f"an unknown donor must decline every criterion, got: {results}")

    # Also confirm an empty trace, empty submission, and empty donor all degrade safely.
    try:
        if interrogator.select_questions([], "", {}) != []:
            failures.append("expected [] for an empty rule_trace")
        if interrogator.select_questions(None, "USAID", None) != []:
            failures.append("expected [] for a None rule_trace/submission")
    except Exception as e:
        failures.append(f"select_questions() raised on empty/None input: {e!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: unknown donor and empty/None input both degrade safely, never raise.")


def run_dedupes_repeated_criterion_and_ignores_unfired():
    """Only fired rules count, and a criterion that fires more than once
    (two rules in the same knowledge/rules/*.yaml file) only yields one
    selected question, not a duplicate."""
    failures = []
    submission = {"evidence": [{"description": "site visit", "verified_by": "external auditor",
                                 "recency": "2026-01", "type": "Document"}]}
    rule_trace = [
        _trace("Directness", fired=True),
        _trace("Directness", fired=True),   # a second Directness rule also firing
        _trace("Verification", fired=False),  # not fired -- must be ignored
    ]

    results = interrogator.select_questions(rule_trace, "USAID", submission)
    criteria = [r["criterion"] for r in results]
    if criteria != ["Directness"]:
        failures.append(f"expected only one de-duplicated Directness entry, got {criteria}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: repeated fired criteria de-dupe to one entry, unfired rules are ignored.")


if __name__ == "__main__":
    run_real_question_for_covered_pair()
    run_declines_gracefully_for_uncovered_pair()
    run_declines_gracefully_for_uncertain_field()
    run_never_raises_on_unknown_donor()
    run_dedupes_repeated_criterion_and_ignores_unfired()
