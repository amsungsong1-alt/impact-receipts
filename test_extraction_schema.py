"""
test_extraction_schema.py — golden tests for utils/extraction_schema.py (Laudon Ch.11, C2:
extraction/scoring separation formalized -- validating an LLM extraction response's shape
before any field reaches session_state, and a shared "is this field uncertain" check).

No pytest, no network calls. Run with: python test_extraction_schema.py
"""

from utils import extraction_schema as es


def run_validate_extraction():
    failures = []

    # A well-shaped, realistic single-result extraction response must pass.
    good = {
        "result_basics": {"result_statement": "Trained 487 farmers.", "target_group": "Farmers"},
        "logframe_linkage": {"indicator_name": "Not found"},
        "evidence_verification": {"evidence_description": "Attendance sheets."},
        "funder_readiness_inputs": {"learning_and_adaptation": "Not found"},
        "documents_referenced": ["progress_report.pdf"],
        "evidence_strengthening_checks": [],
        "extraction_metadata": {"confidence_note": "High confidence extraction."},
    }
    valid, errors = es.validate_extraction(good)
    if not valid:
        failures.append(f"a well-shaped extraction response should validate, got errors: {errors}")

    # A response missing several sections entirely must still validate --
    # a short/sparse document can legitimately have nothing to extract for
    # a whole section; validation checks shape, not completeness.
    sparse = {"result_basics": {"result_statement": "Some result."}}
    valid, errors = es.validate_extraction(sparse)
    if not valid:
        failures.append(f"a sparse-but-well-shaped response should validate, got errors: {errors}")

    # A multi-result response (top-level 'results' list) must validate.
    multi = {"results": [{"result_basics": {}}, {"result_basics": {}}]}
    valid, errors = es.validate_extraction(multi)
    if not valid:
        failures.append(f"a multi-result response should validate, got errors: {errors}")

    # Wrong top-level type must fail.
    valid, errors = es.validate_extraction(["not", "a", "dict"])
    if valid:
        failures.append("a top-level list (not a dict) should fail validation")

    # A section with the wrong type (string instead of dict) must fail.
    wrong_shape = {"result_basics": "this should be a dict, not a string"}
    valid, errors = es.validate_extraction(wrong_shape)
    if valid:
        failures.append("a section with the wrong type should fail validation")
    if not any("result_basics" in e for e in errors):
        failures.append(f"expected an error naming 'result_basics', got {errors}")

    # None / malformed input must never raise.
    try:
        valid, errors = es.validate_extraction(None)
        if valid:
            failures.append("None should fail validation, not pass")
    except Exception as exc:
        failures.append(f"validate_extraction(None) raised instead of returning (False, [...]): {exc}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: validate_extraction — well-shaped, sparse, and multi-result inputs pass; "
          "wrong top-level type and wrong section type fail; never raises on bad input.")


def run_is_uncertain_and_mark_uncertain_fields():
    failures = []

    cases = [
        ("Not found", True),
        ("", True),
        ("   ", True),
        (None, True),
        ([], True),
        ({}, True),
        ("487 farmers trained", False),
        ("0", False),  # a real, meaningful zero value -- not the same as missing
        (["item"], False),
        ({"key": "value"}, False),
    ]
    for value, expected in cases:
        got = es.is_uncertain(value)
        if got != expected:
            failures.append(f"is_uncertain({value!r}) expected {expected}, got {got}")

    flat = {
        "result_statement": "Trained 487 farmers.",
        "target_group": "Not found",
        "timeframe": "",
        "geographic_scope": "Northern Region",
    }
    marked = es.mark_uncertain_fields(flat)
    expected_marks = {
        "result_statement": False, "target_group": True,
        "timeframe": True, "geographic_scope": False,
    }
    if marked != expected_marks:
        failures.append(f"mark_uncertain_fields({flat}) expected {expected_marks}, got {marked}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: is_uncertain/mark_uncertain_fields — sentinel/empty/whitespace values flagged "
          "uncertain, real values (including a meaningful '0') are not.")


if __name__ == "__main__":
    run_validate_extraction()
    run_is_uncertain_and_mark_uncertain_fields()
