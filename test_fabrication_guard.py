"""
test_fabrication_guard.py — Laudon Ch.11, C5: red-team fixtures for the fabrication guard
(utils/fabrication_guard.py) and the retry-then-degrade flow it backstops in
council.run_council_assessment()'s synthesis step.

No pytest, no real network calls: council.run_council_assessment()'s API calls are tested by
temporarily swapping council._call_haiku for a fake, same pattern as test_council.py's
run_logframe_match(). Run with: python test_fabrication_guard.py
"""

import json

import council
from utils import fabrication_guard as fg


_BASE_SUBMISSION = {
    "result_statement": (
        "Trained 487 smallholder farmers in climate-smart agriculture across "
        "3 districts in Northern Ghana between January and June 2025."
    ),
    "target_group": "Smallholder farmers",
    "timeframe": "January-June 2025",
    "geographic_scope": "3 districts in Northern Ghana",
    "logframe_indicator": "% of smallholder farmers trained applying climate-smart practices",
    "logframe_target": "450",
    "logframe_achievement": "487",
    "evidence": [{
        "type": "Attendance sheets / participant registers",
        "description": "Signed attendance sheets from 12 sessions, verified by District Officer.",
        "recency": "June 2025",
        "verified_by": "District Agriculture Officer",
    }],
}


def run_red_team_fixtures():
    """Documents designed to tempt fabrication -- rounding a real number,
    inventing a percentage/date absent from the source, and (a false-positive
    check) correctly restating a real number with different formatting must
    all be classified correctly. Zero fabricated spans survive to a "clean"
    verdict."""
    failures = []

    cases = [
        # (label, draft, expect_clean, expect_offending_or_None)
        (
            "rounds_a_real_number",
            "Trained approximately 500 smallholder farmers across Northern Ghana.",
            False, ["500"],
        ),
        (
            "invents_a_percentage",
            "Trained 487 farmers, achieving a 95% adoption rate.",
            False, ["95"],
        ),
        (
            "invents_a_date",
            "Trained 487 farmers, with a follow-up planned for December 2026.",
            False, ["2026"],
        ),
        (
            "reformatted_but_real_number",
            "Trained 487 farmers (487 in total) across 3 districts.",
            True, [],
        ),
        (
            "entirely_clean_draft",
            "Trained 487 smallholder farmers across 3 districts in Northern Ghana.",
            True, [],
        ),
    ]

    for label, draft, expect_clean, expect_offending in cases:
        is_clean, offending = fg.check_fabrication(draft, _BASE_SUBMISSION)
        if is_clean != expect_clean:
            failures.append(f"[{label}] expected is_clean={expect_clean}, got {is_clean} (offending={offending})")
        elif not expect_clean and offending != expect_offending:
            failures.append(f"[{label}] expected offending={expect_offending}, got {offending}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: red-team fixtures — rounding, invented percentage/date all caught; "
          "reformatted-but-real number and a clean draft produce zero false positives.")


def run_structural_fallback_message():
    failures = []
    for field in ("upgraded_result_statement", "upgraded_evidence_statement"):
        msg = fg.structural_fallback_message(field)
        if not msg or "not in your evidence" not in msg.lower() and "not provided" not in msg.lower():
            failures.append(f"structural_fallback_message({field!r}) doesn't read as a structural nudge: {msg!r}")

    # An unrecognized field name must still return a sensible generic message, not raise.
    generic = fg.structural_fallback_message("some_unrecognized_field")
    if not generic:
        failures.append("structural_fallback_message() on an unknown field returned an empty string")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: structural_fallback_message — field-aware nudges present, unknown field degrades safely.")


def run_retry_then_degrade():
    """run_council_assessment()'s synthesis step must retry a dirty draft up
    to MAX_FABRICATION_RETRIES times, then degrade to a structural suggestion
    -- never a bare "" and never the fabricated text itself."""
    failures = []
    original_call_haiku = council._call_haiku
    _synthesis_calls = {"count": 0}

    def _fake(_system, user_msg, _api_key, max_tokens=300, model=None):
        if user_msg == "Please provide your assessment.":
            return "Solid evidence overall."  # one of the 5 persona calls
        # Synthesis call — always return a draft that fabricates a percentage,
        # on every attempt, to force exhausting every retry.
        _synthesis_calls["count"] += 1
        return json.dumps({
            "upgraded_result_statement": "Trained 487 farmers, achieving a 95% adoption rate.",
            "upgraded_evidence_statement": "Verified by an independent auditor in December 2026.",
            "reporting_team_brief": {
                "what_score_means": "x", "what_to_change": [], "how_long": "", "projected_status": "",
            },
        })

    council._call_haiku = _fake
    try:
        ev = {"fixes": [], "confidence_score": 3.0, "clarity_score": 3.0}
        result = council.run_council_assessment(_BASE_SUBMISSION, ev, api_key="fake")

        if _synthesis_calls["count"] != 2:
            failures.append(
                f"expected exactly 2 synthesis attempts (MAX_FABRICATION_RETRIES), got {_synthesis_calls['count']}"
            )

        if result["upgraded_result_statement"] == "":
            failures.append("a persistently dirty draft degraded to a bare empty string, not a structural suggestion")
        if "95" in result["upgraded_result_statement"] or "%" in result["upgraded_result_statement"]:
            failures.append(
                f"the fabricated percentage survived into the final output: {result['upgraded_result_statement']!r}"
            )
        if "not provided" not in result["upgraded_result_statement"].lower() and \
           "not in your evidence" not in result["upgraded_result_statement"].lower():
            failures.append(
                f"expected a structural-suggestion fallback, got: {result['upgraded_result_statement']!r}"
            )

        if result["upgraded_evidence_statement"] == "" or "2026" in result["upgraded_evidence_statement"]:
            failures.append(
                f"evidence statement did not degrade correctly: {result['upgraded_evidence_statement']!r}"
            )

        withheld = result.get("withheld", {})
        if not withheld.get("upgraded_result_statement") or not withheld.get("upgraded_evidence_statement"):
            failures.append(f"withheld flags should both be True after exhausting retries, got {withheld}")

        offending = withheld.get("offending_tokens", {})
        if "95" not in offending.get("upgraded_result_statement", []):
            failures.append(f"expected the offending token '95' recorded, got {offending}")
        if "2026" not in offending.get("upgraded_evidence_statement", []):
            failures.append(f"expected the offending token '2026' recorded, got {offending}")
    finally:
        council._call_haiku = original_call_haiku

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: retry-then-degrade — exhausts MAX_FABRICATION_RETRIES attempts, degrades to a "
          "structural suggestion (never the fabricated text, never a bare empty string), and "
          "records the offending tokens.")


def run_retry_succeeds_on_second_attempt():
    """A draft that's dirty on the first attempt but clean on a later one
    must be accepted -- the retry loop's whole point is to give the model a
    second chance, not just to exhaust attempts and always degrade."""
    failures = []
    original_call_haiku = council._call_haiku
    _synthesis_calls = {"count": 0}

    def _fake(_system, user_msg, _api_key, max_tokens=300, model=None):
        if user_msg == "Please provide your assessment.":
            return "Solid evidence overall."
        _synthesis_calls["count"] += 1
        if _synthesis_calls["count"] == 1:
            # First attempt: dirty (invents a percentage).
            draft = "Trained 487 farmers, achieving a 95% adoption rate."
        else:
            # Second attempt: clean.
            draft = "Trained 487 farmers across 3 districts in Northern Ghana."
        return json.dumps({
            "upgraded_result_statement": draft,
            "upgraded_evidence_statement": "Verified by District Agriculture Officer.",
            "reporting_team_brief": {
                "what_score_means": "x", "what_to_change": [], "how_long": "", "projected_status": "",
            },
        })

    council._call_haiku = _fake
    try:
        ev = {"fixes": [], "confidence_score": 3.0, "clarity_score": 3.0}
        result = council.run_council_assessment(_BASE_SUBMISSION, ev, api_key="fake")

        if _synthesis_calls["count"] != 2:
            failures.append(f"expected exactly 2 synthesis attempts (dirty then clean), got {_synthesis_calls['count']}")
        if result["withheld"].get("upgraded_result_statement"):
            failures.append("a draft that became clean on retry should not be marked withheld")
        if "95" in result["upgraded_result_statement"]:
            failures.append("the first (dirty) attempt's text leaked into the final accepted output")
        if result["upgraded_result_statement"] != "Trained 487 farmers across 3 districts in Northern Ghana.":
            failures.append(f"expected the clean second-attempt draft, got {result['upgraded_result_statement']!r}")
    finally:
        council._call_haiku = original_call_haiku

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: retry succeeds on second attempt — a draft that becomes clean on retry is accepted, not discarded.")


def run_check_score_grounding():
    """Laudon Ch.11, C3: check_score_grounding() catches a MISSTATED existing
    score, distinct from check_fabrication()'s INVENTED-number check. Must
    NOT flag legitimate threshold/rubric references near a criterion name --
    the false-positive risk the narrow "is/was/scored/:" pattern exists to
    avoid."""
    failures = []
    ev = {
        "confidence_components": {"direct_score": 1.2, "verify_score": 2.0, "recency_score": 1.0},
        "clarity_components": {
            "definition_score": 1.0, "measurement_score": 1.25, "integrity_score": 0.75,
            "scope_score": 0.5, "governance_score": 0.75,
        },
    }

    cases = [
        ("correct_is_claim", "Your Directness score is 1.2, which is why you need a primary record.", True, []),
        ("misstated_is_claim", "Your Directness score is 1.8, which is fairly strong.", False,
         ["Directness: stated 1.8, actual 1.2"]),
        ("threshold_reference_not_flagged", "You need Directness to reach 1.2 to clear the threshold.", True, []),
        ("correct_colon_claim", "Verification: 2.0 out of 2.0, fully verified.", True, []),
        ("misstated_colon_claim", "Verification: 1.5, needs an external reviewer.", False,
         ["Verification: stated 1.5, actual 2.0"]),
        ("no_criterion_mentioned", "Nothing to see here.", True, []),
        ("empty_text", "", True, []),
    ]
    for label, text, expect_grounded, expect_mismatches in cases:
        is_grounded, mismatches = fg.check_score_grounding(text, ev)
        if is_grounded != expect_grounded:
            failures.append(f"[{label}] expected is_grounded={expect_grounded}, got {is_grounded} (mismatches={mismatches})")
        elif mismatches != expect_mismatches:
            failures.append(f"[{label}] expected mismatches={expect_mismatches}, got {mismatches}")

    # Never raises on a malformed/empty ev.
    try:
        is_grounded, mismatches = fg.check_score_grounding("Directness is 1.2.", {})
        if not is_grounded or mismatches:
            failures.append(f"an empty ev dict should find nothing to compare against (no false mismatch), got {mismatches}")
    except Exception as exc:
        failures.append(f"check_score_grounding raised on an empty ev dict: {exc}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: check_score_grounding — misstated scores caught, threshold/rubric references "
          "correctly NOT flagged, never raises on malformed input.")


if __name__ == "__main__":
    run_red_team_fixtures()
    run_structural_fallback_message()
    run_retry_then_degrade()
    run_retry_succeeds_on_second_attempt()
    run_check_score_grounding()
