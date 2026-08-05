"""
test_impact_linked_readiness.py — golden tests for
utils/impact_linked_readiness.py (Impact-Linked Readiness Module, MVP).

No pytest, no network calls, no DB. Pure function tests over hand-built
submission dicts. Run with: python test_impact_linked_readiness.py
"""

import test_app  # reuse CASES["strong"] as a base fixture
from utils.impact_linked_readiness import (
    check_indicator_contractibility, trace_evidence_chain,
    assess_verification_readiness, generate_readiness_certificate,
)


def _clean_submission():
    """CASES["strong"] has no logframe_baseline or disaggregation_status key
    -- reusing it bare would incorrectly trip the 'no baseline'/'no
    disaggregation rule' flags on what's meant to be an all-clean fixture."""
    sub = dict(test_app.CASES["strong"])
    sub["logframe_baseline"] = "350"
    sub["disaggregation_status"] = "Yes — fully disaggregated"
    return sub


# ---------------------------------------------------------------------------
# Check 1 — contractibility
# ---------------------------------------------------------------------------

def run_contractibility_all_clean():
    failures = []
    checks = check_indicator_contractibility(_clean_submission())
    if len(checks) != 4:
        failures.append(f"expected 4 checks, got {len(checks)}")
    if any(c["status"] != "pass" for c in checks):
        failures.append(f"expected all 4 checks to pass for the clean fixture, got {checks}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a fully-populated, well-defined indicator passes all 4 contractibility checks.")


def run_contractibility_units_flag():
    failures = []
    sub = _clean_submission()
    sub["logframe_indicator"] = "improvement in outcomes"
    sub["logframe_target"] = "500"
    checks = check_indicator_contractibility(sub)
    units_check = next(c for c in checks if c["check"] == "units")
    if units_check["status"] != "flag":
        failures.append(f"expected a units flag for an indicator/target with no unit token, got {units_check}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a target with no recognizable unit correctly flags.")


def run_contractibility_disaggregation_flag():
    failures = []
    for bad_status in ("No", "Not applicable", "Not specified", "", None):
        sub = _clean_submission()
        sub["disaggregation_status"] = bad_status
        checks = check_indicator_contractibility(sub)
        disagg_check = next(c for c in checks if c["check"] == "disaggregation")
        if disagg_check["status"] != "flag":
            failures.append(f"expected a disaggregation flag for status={bad_status!r}, got {disagg_check}")

    # "Partially disaggregated" counts as having a rule stated -- must NOT flag.
    sub_partial = _clean_submission()
    sub_partial["disaggregation_status"] = "Partially disaggregated"
    partial_check = next(c for c in check_indicator_contractibility(sub_partial) if c["check"] == "disaggregation")
    if partial_check["status"] != "pass":
        failures.append(f"expected 'Partially disaggregated' to pass, got {partial_check}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: missing/no disaggregation rule flags correctly; 'Partially disaggregated' passes.")


def run_contractibility_verification_method_flag():
    failures = []
    sub = _clean_submission()
    sub["provenance_checklist"] = dict(sub["provenance_checklist"], collection_tool_named="No")
    checks = check_indicator_contractibility(sub)
    vm_check = next(c for c in checks if c["check"] == "verification_method")
    if vm_check["status"] != "flag":
        failures.append(f"expected a verification_method flag when collection_tool_named='No', got {vm_check}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no confirmed collection tool/method correctly flags verification_method.")


def run_contractibility_baseline_flag():
    failures = []
    sub = _clean_submission()
    sub["logframe_baseline"] = ""
    checks = check_indicator_contractibility(sub)
    baseline_check = next(c for c in checks if c["check"] == "baseline")
    if baseline_check["status"] != "flag":
        failures.append(f"expected a baseline flag when target is set but baseline is empty, got {baseline_check}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a target with no baseline correctly flags.")


def run_contractibility_never_raises():
    failures = []
    try:
        empty = check_indicator_contractibility({})
        none_result = check_indicator_contractibility(None)
    except Exception as e:
        failures.append(f"check_indicator_contractibility must never raise, got {e!r}")
    else:
        if len(empty) != 4 or len(none_result) != 4:
            failures.append("expected 4 checks even for an empty/None submission")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: never raises on empty/None submission, still returns all 4 checks.")


# ---------------------------------------------------------------------------
# Check 2 — evidence chain
# ---------------------------------------------------------------------------

def run_evidence_chain_aggregation_always_missing():
    failures = []
    for sub in (_clean_submission(), {}, None):
        chain = trace_evidence_chain(sub)
        agg_link = next(link for link in chain if link["link"] == "aggregation_method")
        if agg_link["present"] is not False:
            failures.append(f"aggregation_method must ALWAYS be present=False (no field captures it), got {agg_link}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: aggregation_method is always present=False, regardless of input -- the intentional MVP gap "
          "is locked in, never silently fabricated as present.")


def run_evidence_chain_links_map_correctly():
    failures = []
    sub = _clean_submission()
    chain = trace_evidence_chain(sub)
    by_link = {link["link"]: link for link in chain}

    if len(chain) != 5:
        failures.append(f"expected 5 chain links, got {len(chain)}")
    if not by_link["collection_instrument"]["present"]:
        failures.append("expected collection_instrument present for the clean fixture (collection_tool_named=Yes)")
    if not by_link["sampling_approach"]["present"]:
        failures.append("expected sampling_approach present for the clean fixture (sampling_documented=Yes)")
    if not by_link["raw_records"]["present"]:
        failures.append("expected raw_records present for the clean fixture (auditor_traceable=Yes)")
    if not by_link["definition"]["present"]:
        failures.append("expected definition present for the clean fixture (passes all contractibility checks)")

    # Partial traceability -> raw_records NOT present, but detail notes "partial."
    sub_partial = _clean_submission()
    sub_partial["provenance_checklist"] = dict(
        sub_partial["provenance_checklist"],
        auditor_traceable="Partially — some records would take effort to locate",
    )
    partial_chain = trace_evidence_chain(sub_partial)
    partial_raw = next(link for link in partial_chain if link["link"] == "raw_records")
    if partial_raw["present"] is not False or "PARTIALLY" not in partial_raw["detail"]:
        failures.append(f"expected raw_records present=False with a 'PARTIALLY' detail note, got {partial_raw}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: collection_instrument/sampling_approach/raw_records/definition links map correctly to "
          "provenance_checklist answers and Check 1's result; partial traceability handled distinctly.")


def run_evidence_chain_definition_tracks_contractibility():
    """Regression guard: the 'definition' link must track
    check_indicator_contractibility()'s own result, not re-derive it
    separately -- the two checks must never silently disagree."""
    failures = []
    sub = _clean_submission()
    sub["logframe_baseline"] = ""  # trips a contractibility flag
    chain = trace_evidence_chain(sub)
    definition_link = next(link for link in chain if link["link"] == "definition")
    if definition_link["present"] is not False:
        failures.append(
            "expected the 'definition' chain link to be present=False when "
            f"check_indicator_contractibility() has a flag, got {definition_link}"
        )

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: the 'definition' chain link correctly tracks check_indicator_contractibility()'s result.")


# ---------------------------------------------------------------------------
# Check 5 — verification readiness
# ---------------------------------------------------------------------------

def run_verification_readiness_signal_is_always_self_declared():
    failures = []
    for sub in (_clean_submission(), {}, None):
        result = assess_verification_readiness(sub)
        if result["signal"] != "self_declared":
            failures.append(f"expected signal='self_declared' always, got {result['signal']!r} for {sub}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: verification-readiness signal is always the literal string 'self_declared' -- "
          "a policy invariant, never 'verified' or 'confirmed'.")


def run_verification_readiness_traceable_mapping():
    failures = []
    cases = {
        "Yes — an auditor could retrieve the original records": True,
        "Partially — some records would take effort to locate": False,
        "No / not sure": None,
        "Choose an option...": None,
        "": None,
    }
    for answer, expected in cases.items():
        sub = _clean_submission()
        sub["provenance_checklist"] = dict(sub["provenance_checklist"], auditor_traceable=answer)
        result = assess_verification_readiness(sub)
        if result["traceable"] != expected:
            failures.append(f"auditor_traceable={answer!r}: expected traceable={expected!r}, got {result['traceable']!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: auditor_traceable's 3-way answer maps correctly to traceable=True/False/None.")


# ---------------------------------------------------------------------------
# Integration — generate_readiness_certificate()
# ---------------------------------------------------------------------------

def run_certificate_never_touches_scores():
    failures = []
    cert = generate_readiness_certificate(_clean_submission())
    if "confidence_score" in cert or "clarity_score" in cert:
        failures.append(
            "generate_readiness_certificate() must never read or return confidence_score/"
            f"clarity_score -- this is a structurally separate product surface, got keys {list(cert.keys())}"
        )

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: the certificate never touches confidence_score/clarity_score -- durable guard "
          "against future scope creep merging the two systems.")


def run_certificate_disclaimer_and_lights():
    failures = []
    clean_cert = generate_readiness_certificate(_clean_submission())
    if "Pre-verification diagnostic" not in clean_cert["disclaimer"] or "not independent assurance" not in clean_cert["disclaimer"]:
        failures.append("expected the pre-verification/not-independent-assurance disclaimer to always be present")
    if clean_cert["contractibility"]["light"] != "green":
        failures.append(f"expected a green contractibility light for the fully-clean fixture, got {clean_cert['contractibility']['light']}")
    if clean_cert["evidence_chain"]["light"] != "amber":
        # aggregation_method is ALWAYS present=False, so even a clean submission
        # can never reach a green evidence-chain light -- 4/5 present is amber, not red.
        failures.append(
            "expected an amber evidence-chain light for the clean fixture (aggregation_method "
            f"is always missing), got {clean_cert['evidence_chain']['light']}"
        )
    if clean_cert["gaps"] == []:
        failures.append("expected at least one named gap (aggregation_method + the verification-readiness "
                         "gap note) even for the clean fixture")

    # Empty submission -> everything red/amber, never raises, never crashes.
    empty_cert = generate_readiness_certificate({})
    if empty_cert["contractibility"]["light"] != "red":
        failures.append(f"expected a red contractibility light for an empty submission, got {empty_cert['contractibility']['light']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: disclaimer always present, traffic lights compute correctly (clean fixture can never "
          "reach a green evidence-chain light due to the always-missing aggregation_method link), "
          "gaps list is never empty, empty submission degrades to red without raising.")


def run_certificate_runs_standalone():
    """Must not require evaluate_submission() to have been called first."""
    failures = []
    try:
        cert = generate_readiness_certificate(_clean_submission())
    except Exception as e:
        failures.append(f"generate_readiness_certificate() must run standalone, got {e!r}")
    else:
        if "indicator" not in cert:
            failures.append("expected the certificate to echo back the indicator name")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: generate_readiness_certificate() runs standalone, no dependency on evaluate_submission().")


if __name__ == "__main__":
    run_contractibility_all_clean()
    run_contractibility_units_flag()
    run_contractibility_disaggregation_flag()
    run_contractibility_verification_method_flag()
    run_contractibility_baseline_flag()
    run_contractibility_never_raises()
    run_evidence_chain_aggregation_always_missing()
    run_evidence_chain_links_map_correctly()
    run_evidence_chain_definition_tracks_contractibility()
    run_verification_readiness_signal_is_always_self_declared()
    run_verification_readiness_traceable_mapping()
    run_certificate_never_touches_scores()
    run_certificate_disclaimer_and_lights()
    run_certificate_runs_standalone()
