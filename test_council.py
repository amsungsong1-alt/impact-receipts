"""
test_council.py — golden tests for council.check_fabrication() and its helpers.

Locks the fabrication-guard behaviour that backstops the Council's AI-drafted
"upgraded statement" text: any numeral/year/percentage in a draft must appear
somewhere in the user's own submission, or the draft must be withheld. Pure
post-processing — no network calls, no API mocking needed.

Run with: python test_council.py
"""

import council


def run():
    failures = []

    def check(label, draft, submission, expect_clean, expect_offending=None):
        is_clean, offending = council.check_fabrication(draft, submission)
        if is_clean != expect_clean:
            failures.append(
                f"[{label}] expected is_clean={expect_clean}, got {is_clean} "
                f"(offending={offending})"
            )
        if expect_offending is not None and offending != expect_offending:
            failures.append(
                f"[{label}] expected offending={expect_offending}, got {offending}"
            )

    base_submission = {
        "result_statement": (
            "Trained 487 smallholder farmers in climate-smart agriculture "
            "across 3 districts in Northern Ghana between January and June 2025."
        ),
        "target_group": "Smallholder farmers",
        "timeframe": "January-June 2025",
        "geographic_scope": "3 districts in Northern Ghana",
        "additional_context": "This result informs the Year 2 work plan revision.",
        "logframe_indicator": "% of smallholder farmers trained applying climate-smart practices",
        "logframe_target": "450",
        "logframe_achievement": "487",
        "beneficiary_voice": "Direct beneficiary feedback collected",
        "bv_method_detail": "Phone survey with 142 smallholder farmers in June 2025.",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "Verified by independent third party",
        "evidence": [{
            "type": "Attendance sheets / participant registers",
            "description": (
                "Signed attendance sheets from 12 training sessions across 3 "
                "districts in Northern Ghana, verified by District Agriculture Officer."
            ),
            "recency": "June 2025",
            "verified_by": "District Agriculture Officer",
        }],
        "provenance_checklist": {"sampling_documented": "Yes"},
    }

    # 1. Clean draft — reuses only numbers already present in the source text.
    check(
        "clean_draft",
        "Trained 487 smallholder farmers across 3 districts in Northern Ghana, "
        "January-June 2025, verified by the District Agriculture Officer.",
        base_submission,
        expect_clean=True,
        expect_offending=[],
    )

    # 2. Fabricated draft — invents a percentage not present anywhere in the source.
    check(
        "fabricated_percentage",
        "Trained 487 smallholder farmers, a 108% increase over baseline, "
        "across 3 districts.",
        base_submission,
        expect_clean=False,
        expect_offending=["108"],
    )

    # 3. Draft restates logframe_target/logframe_achievement — these live in
    #    dedicated dict keys, not inside result_statement text, so this proves
    #    the guard checks the full submission and not just the narrative fields.
    check(
        "logframe_fields",
        "Against a target of 450, the programme achieved 487 — exceeding plan.",
        base_submission,
        expect_clean=True,
        expect_offending=[],
    )

    # 4. Comma-formatted number in the draft vs. an un-formatted source number,
    #    and the reverse direction too.
    comma_submission = dict(base_submission, result_statement=(
        "Reached 1200 households with hygiene kits in the distribution log."
    ))
    check(
        "comma_in_draft",
        "Reached 1,200 households with hygiene kits.",
        comma_submission,
        expect_clean=True,
        expect_offending=[],
    )
    comma_source_submission = dict(base_submission, result_statement=(
        "Reached 1,200 households with hygiene kits in the distribution log."
    ))
    check(
        "comma_in_source",
        "Reached 1200 households with hygiene kits.",
        comma_source_submission,
        expect_clean=True,
        expect_offending=[],
    )

    # 5. Percentage token handling both directions.
    pct_submission = dict(base_submission, result_statement=(
        "12% of households adopted the new practice, per the endline survey."
    ))
    check(
        "percent_in_draft_matches_bare_source",
        "12% of households adopted the new practice.",
        pct_submission,
        expect_clean=True,
        expect_offending=[],
    )

    # 5b. Trailing-period regression: a source field ending a sentence with a
    #     bare year must still match a draft token without the period, and a
    #     genuine decimal must not be mangled by the same normalization.
    period_submission = dict(base_submission, additional_context=(
        "Programme baseline was established in 2025."
    ))
    check(
        "trailing_period_year",
        "The baseline was established in 2025.",
        period_submission,
        expect_clean=True,
        expect_offending=[],
    )
    decimal_submission = dict(base_submission, result_statement=(
        "Reached 3.5 percent more households than the prior quarter."
    ))
    check(
        "genuine_decimal_not_mangled",
        "Reached 3.5 percent more households.",
        decimal_submission,
        expect_clean=True,
        expect_offending=[],
    )
    check(
        "decimal_mismatch_is_caught",
        "Reached 3.6 percent more households.",
        decimal_submission,
        expect_clean=False,
        expect_offending=["3.6"],
    )

    # 6. Number sourced only from an evidence[] item's description/recency field.
    evidence_only_submission = dict(base_submission, result_statement=(
        "Farmers were trained in climate-smart agriculture."
    ))
    check(
        "evidence_list_fields",
        "Trained farmers across 12 sessions, verified in June 2025.",
        evidence_only_submission,
        expect_clean=True,
        expect_offending=[],
    )

    # Empty draft is trivially clean (nothing to withhold).
    check("empty_draft", "", base_submission, expect_clean=True, expect_offending=[])

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)

    print(f"PASS: fabrication guard verified across representative drafts and submissions.")


def run_logframe_match():
    """match_logframe_indicator() — pure JSON-parsing/validation logic, tested
    by swapping out council._call_haiku so no network call happens."""
    failures = []
    indicators = [
        "Indicator 1.2: Number of households with access to safe water",
        "Indicator 2.1: % of farmers applying climate-smart practices",
    ]
    original_call_haiku = council._call_haiku

    def _fake(_system, _user, _api_key, max_tokens=300, model=None):
        return _fake.response

    council._call_haiku = _fake
    try:
        # 1. A clean match to a real candidate is accepted as-is.
        _fake.response = (
            '{"best_match": "Indicator 2.1: % of farmers applying climate-smart practices", '
            '"confidence_label": "Strong", "justification": "Result reports farmers adopting practices."}'
        )
        result = council.match_logframe_indicator(
            "487 farmers applying climate-smart practices.", indicators, api_key="fake"
        )
        if result["best_match"] != indicators[1] or result["confidence_label"] != "Strong":
            failures.append(f"clean_match: unexpected result {result!r}")

        # 2. A model response inventing an indicator NOT in the candidate list
        #    must be discarded — never force/substitute a match the user didn't give us.
        _fake.response = (
            '{"best_match": "Indicator 9.9: an indicator that was never pasted", '
            '"confidence_label": "Strong", "justification": "x"}'
        )
        result = council.match_logframe_indicator("Some result.", indicators, api_key="fake")
        if result["best_match"] != "" or result["confidence_label"] != "None":
            failures.append(f"invented_indicator_rejected: unexpected result {result!r}")

        # 3. Model explicitly declines to match — passed through as-is, never forced.
        _fake.response = '{"best_match": "", "confidence_label": "None", "justification": "No indicator fits."}'
        result = council.match_logframe_indicator("Unrelated result about roads.", indicators, api_key="fake")
        if result["best_match"] != "" or result["confidence_label"] != "None":
            failures.append(f"no_match_declined: unexpected result {result!r}")

        # 4. Malformed JSON response degrades to "None" rather than raising.
        _fake.response = "not valid json at all"
        result = council.match_logframe_indicator("Some result.", indicators, api_key="fake")
        if result["best_match"] != "" or result["confidence_label"] != "None":
            failures.append(f"malformed_json: unexpected result {result!r}")

        # 5. No indicators pasted / no result statement — never calls the API, returns None.
        result = council.match_logframe_indicator("Some result.", [], api_key="fake")
        if result["confidence_label"] != "None":
            failures.append(f"no_indicators: unexpected result {result!r}")
        result = council.match_logframe_indicator("", indicators, api_key="fake")
        if result["confidence_label"] != "None":
            failures.append(f"no_result_statement: unexpected result {result!r}")
    finally:
        council._call_haiku = original_call_haiku

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)

    print("PASS: logframe match — accepts real candidates, rejects invented ones, degrades safely.")


if __name__ == "__main__":
    run()
    run_logframe_match()
