"""
test_app.py — golden tests for evaluator.evaluate_submission().

Locks the CURRENT scoring behaviour for a set of representative submissions
before a structural refactor of app.py. Run with: python test_app.py

As pure helper modules are extracted from app.py (diagnostics.py,
governance.py, ...), extend this file with golden assertions for their
public functions using the same representative inputs.
"""

import evaluator
import diagnostics
import framework_crosswalk


CASES = {
    "strong": {
        "result_statement": (
            "Trained 487 smallholder farmers in climate-smart agriculture "
            "across 3 districts in Northern Ghana between January and June 2025."
        ),
        "target_group": "Smallholder farmers",
        "timeframe": "January-June 2025",
        "geographic_scope": "3 districts in Northern Ghana",
        "additional_context": "This result informs the Year 2 work plan revision.",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "Verified by independent third party",
        "logframe_indicator": "% of smallholder farmers trained applying climate-smart practices",
        "logframe_target": "450",
        "logframe_achievement": "487",
        "beneficiary_voice": "Direct beneficiary feedback collected (e.g., Lean Data survey, focus groups, NPS)",
        "bv_method_detail": "Phone survey with 142 smallholder farmers in June 2025, 30-minute structured interview.",
        "evidence": [{
            "type": "Attendance sheets / participant registers",
            "description": (
                "Signed attendance sheets from 12 training sessions across 3 districts "
                "in Northern Ghana, verified by District Agriculture Officer."
            ),
            "recency": "June 2025",
            "verified_by": "District Agriculture Officer",
        }],
        "provenance_checklist": {
            "sampling_documented": "Yes",
            "double_counting_checked": "Yes",
            "collection_tool_named": "Yes",
            "collector_independent": "Yes",
            "recall_period_ok": "Yes",
            "auditor_traceable": "Yes — an auditor could retrieve the original records",
        },
    },

    "weak": {
        "result_statement": "Some farmers were trained.",
        "target_group": "",
        "timeframe": "",
        "geographic_scope": "",
        "additional_context": "",
        "internal_review": "Not reviewed",
        "external_review": "No external review",
        "logframe_indicator": "",
        "logframe_target": "",
        "logframe_achievement": "",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Other",
            "description": "We think it went ok.",
            "recency": "",
            "verified_by": "",
        }],
        "provenance_checklist": {},
    },

    "placeholder": {
        "result_statement": "test test asdf",
        "target_group": "test",
        "timeframe": "test",
        "geographic_scope": "test",
        "additional_context": "",
        "internal_review": "Not reviewed",
        "external_review": "No external review",
        "logframe_indicator": "",
        "logframe_target": "",
        "logframe_achievement": "",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Other",
            "description": "asdf qwerty lorem placeholder sample test",
            "recency": "",
            "verified_by": "test",
        }],
        "provenance_checklist": {},
    },

    "qualitative": {
        "result_statement": (
            "Women-led savings groups in 5 communities reported increased "
            "financial resilience during the 2025 lean season."
        ),
        "target_group": "Women-led savings group members",
        "timeframe": "January-June 2025",
        "geographic_scope": "5 communities in Volta Region",
        "additional_context": "Findings will inform the gender strategy review.",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "No external review",
        "logframe_indicator": "Outcome narrative on financial resilience",
        "logframe_target": "",
        "logframe_achievement": "",
        "beneficiary_voice": "Beneficiary representatives consulted (community leaders, beneficiary committees)",
        "bv_method_detail": "Focus group discussions with 45 savings group members across 5 communities, April 2025.",
        "evidence": [{
            "type": "Case study",
            "description": (
                "Outcome harvesting case study triangulated across 5 communities, "
                "cross-checked against program monitoring records, with bias "
                "considered via independent facilitation."
            ),
            "recency": "May 2025",
            "verified_by": "Gender Advisor",
        }],
        "qualitative_rigor_checklist": {
            "sourcing_documented": True,
            "triangulated": True,
            "bias_considered": True,
            "beneficiary_voice_represented": True,
            "consent_ethics_addressed": True,
        },
        "provenance_checklist": {},
    },

    "qualitative_toggle_only": {
        "result_statement": (
            "Most Significant Change stories from 4 districts indicate growing "
            "confidence among adolescent girls in school clubs during 2025."
        ),
        "target_group": "Adolescent girls in school clubs",
        "timeframe": "2025",
        "geographic_scope": "4 districts",
        "additional_context": "",
        "internal_review": "Not reviewed",
        "external_review": "No external review",
        "logframe_indicator": "",
        "logframe_target": "",
        "logframe_achievement": "",
        "beneficiary_voice": "",
        "qualitative_evidence": True,
        "evidence": [{
            "type": "Other",
            "description": "Most Significant Change stories collected from club facilitators.",
            "recency": "",
            "verified_by": "",
        }],
        "qualitative_rigor_checklist": {},
        "provenance_checklist": {},
    },

    "missing_recency": {
        "result_statement": "Distributed 1,200 hygiene kits to displaced households in Q1 2025.",
        "target_group": "Displaced households",
        "timeframe": "January-March 2025",
        "geographic_scope": "Tamale municipality",
        "additional_context": "",
        "internal_review": "Collected only (no review)",
        "external_review": "No external review",
        "logframe_indicator": "Number of households reached with hygiene kits",
        "logframe_target": "1000",
        "logframe_achievement": "1200",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Raw datasets or survey exports",
            "description": (
                "Distribution log exported from KoboToolbox covering all 1,200 "
                "households, collected by field enumerators."
            ),
            "recency": "",
            "verified_by": "",
        }],
        "provenance_checklist": {},
    },

    "count_only_indicator": {
        "result_statement": "Number of community health workers trained reached 320 in 2025.",
        "target_group": "Community health workers",
        "timeframe": "2025",
        "geographic_scope": "Eastern Region",
        "additional_context": "",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "External partner review",
        "logframe_indicator": "Number of community health workers trained",
        "logframe_target": "300",
        "logframe_achievement": "320",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Attendance sheets / participant registers",
            "description": (
                "Attendance register signed by 320 community health workers "
                "across 8 training sessions, collected by program officers."
            ),
            "recency": "December 2025",
            "verified_by": "Program Officer",
        }],
        "provenance_checklist": {},
    },

    "provenance_marked_na": {
        "result_statement": "Number of community health workers trained reached 320 in 2025.",
        "target_group": "Community health workers",
        "timeframe": "2025",
        "geographic_scope": "Eastern Region",
        "additional_context": "",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "External partner review",
        "logframe_indicator": "Number of community health workers trained",
        "logframe_target": "300",
        "logframe_achievement": "320",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Attendance sheets / participant registers",
            "description": (
                "Attendance register signed by 320 community health workers "
                "across 8 training sessions, collected by program officers."
            ),
            "recency": "December 2025",
            "verified_by": "Program Officer",
        }],
        # Same submission as "count_only_indicator", but every new provenance
        # item is honestly marked "Not applicable" rather than left unanswered.
        "provenance_checklist": {
            "sampling_documented": "Not applicable",
            "double_counting_checked": "Not applicable",
            "collection_tool_named": "Not applicable",
            "collector_independent": "Not applicable",
            "recall_period_ok": "Not applicable",
            "auditor_traceable": "Choose an option...",
        },
    },

    "over_attributed": {
        "result_statement": (
            "Our program caused a 30% reduction in child malnutrition across "
            "the district in 2025."
        ),
        "target_group": "Children under 5",
        "timeframe": "2025",
        "geographic_scope": "Northern district",
        "additional_context": "",
        "internal_review": "Not reviewed",
        "external_review": "No external review",
        "logframe_indicator": "Reduction in child malnutrition rate",
        "logframe_target": "20%",
        "logframe_achievement": "30%",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Survey summary / assessment report",
            "description": (
                "Internal survey summary suggesting malnutrition declined, "
                "no comparison group or baseline used."
            ),
            "recency": "2025",
            "verified_by": "",
        }],
        "provenance_checklist": {},
    },

    "triangulated_contribution": {
        "result_statement": (
            "Our literacy programme contributed to improved reading scores among "
            "enrolled children in 2025, alongside the concurrent school feeding programme."
        ),
        "target_group": "Enrolled primary school children",
        "timeframe": "2025",
        "geographic_scope": "Greater Accra Region",
        "additional_context": "",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "External partner review",
        "logframe_indicator": "Average reading assessment score",
        "logframe_target": "60",
        "logframe_achievement": "68",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Tracer survey results",
            "description": (
                "Baseline and endline reading assessments were administered to the same "
                "cohort. A theory of change links training attendance to increased reading "
                "practice time and improved reading scores. A comparison group of "
                "non-enrolled children in a neighbouring school showed no significant "
                "change over the same period."
            ),
            "recency": "December 2025",
            "verified_by": "Education Advisor",
        }],
        "provenance_checklist": {},
    },

    "partial_logframe_mismatch": {
        "result_statement": (
            "Reached 900 households with cash transfers in 2025, exceeding "
            "the planned target."
        ),
        "target_group": "Vulnerable households",
        "timeframe": "2025",
        "geographic_scope": "Upper West Region",
        "additional_context": "",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "No external review",
        "logframe_indicator": "Number of households receiving cash transfers",
        "logframe_target": "800",
        "logframe_achievement": "850",
        "beneficiary_voice": "",
        "evidence": [{
            "type": "Financial records",
            "description": (
                "Payment reconciliation records from the financial service "
                "provider, covering all disbursements made in 2025."
            ),
            "recency": "2025",
            "verified_by": "Finance Manager",
        }],
        "provenance_checklist": {},
    },
}


GOLDEN = {
    # Verdict strings now use SUBMISSION_THRESHOLD=4.0 (aligned with diagnostic badge).
    # Clarity scores updated to match actual evaluator output (pre-existing drift
    # from description_quality + audit_trail additions; no scoring logic changed here).
    "strong": {
        "confidence_score": 4.2,
        "clarity_score": 5.0,
        "verdict": "Strong KPI — submission-ready on both axes",
    },
    "weak": {
        "confidence_score": 0.1,
        "clarity_score": 0.56,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "placeholder": {
        "confidence_score": 0.0,
        "clarity_score": 2.82,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "qualitative": {
        "confidence_score": 3.8,
        "clarity_score": 4.99,
        # conf=3.8 < SUBMISSION_THRESHOLD=4.0, clar=4.99 >= 4.0 → "Well-defined but weak"
        "verdict": "Well-defined but weak evidence — strengthen the verification chain",
    },
    "qualitative_toggle_only": {
        "confidence_score": 0.3,
        "clarity_score": 0.92,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "missing_recency": {
        "confidence_score": 0.9,
        "clarity_score": 3.55,
        # both < 4.0 → "High risk"
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "count_only_indicator": {
        "confidence_score": 3.0,
        "clarity_score": 4.24,
        # conf=3.0 < 4.0, clar=4.24 >= 4.0 → "Well-defined but weak"
        "verdict": "Well-defined but weak evidence — strengthen the verification chain",
    },
    "over_attributed": {
        "confidence_score": 0.3,
        "clarity_score": 2.92,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "triangulated_contribution": {
        "confidence_score": 3.8,
        "clarity_score": 3.94,
        # conf=3.8 < 4.0 (False), clar=3.94 < 4.0 (False) → "High risk"
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "partial_logframe_mismatch": {
        "confidence_score": 2.2,
        "clarity_score": 3.74,
        # both < 4.0 → "High risk"
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "provenance_marked_na": {
        "confidence_score": 3.2,
        "clarity_score": 4.24,
        # conf=3.2 < 4.0 (False), clar=4.24 >= 4.0 (True) → "Well-defined but weak"
        "verdict": "Well-defined but weak evidence — strengthen the verification chain",
    },
}


# Directness refinement (over-attribution flagging): locks the new
# direct_level/direct_score/direct_overattribution_flag for the two cases
# that exercise the new rule — an over-attributed thin-evidence claim must
# score LOWER than a triangulated contribution claim, and both must surface
# a rationale explaining why.
DIRECTNESS_GOLDEN = {
    "over_attributed": {
        "direct_level": 1,
        "direct_score": 0.4,
        "direct_overattribution_flag": True,
    },
    "triangulated_contribution": {
        "direct_level": 5,
        "direct_score": 2.0,
        "direct_overattribution_flag": False,
    },
}


# Provenance/collection-method check feeding Verification: locks
# verify_score/provenance_adjustment for a case with no provenance answers
# (every item treated as unanswered -> "No") versus the same submission with
# every new item honestly marked "Not applicable" -> neutral. Unanswered
# items must lower Verification; "Not applicable" must not.
VERIFICATION_GOLDEN = {
    "count_only_indicator": {
        "verify_level": 4,
        "provenance_adjustment": -0.18,
        "verify_score": 1.42,
    },
    "provenance_marked_na": {
        "verify_level": 4,
        "provenance_adjustment": -0.03,
        "verify_score": 1.57,
    },
}


# Qualitative evidence track: locks is_qualitative detection (via evidence
# type AND via the manual toggle on otherwise-quantitative evidence types),
# and the resulting Definition/Measurement scores when the 5-item rigor
# checklist is fully answered ("qualitative") vs. left entirely unanswered
# ("qualitative_toggle_only") — unanswered items must not be assumed sound.
QUALITATIVE_GOLDEN = {
    "qualitative": {
        "is_qualitative": True,
        "definition_score": 1.25,
        "measurement_score": 1.25,
    },
    "qualitative_toggle_only": {
        "is_qualitative": True,
        "definition_score": 0.42,
        "measurement_score": 0.0,
    },
    "strong": {
        "is_qualitative": False,
    },
}


def run():
    failures = []
    for name, submission in CASES.items():
        result = evaluator.evaluate_submission(submission)
        expected = GOLDEN[name]
        for key, expected_value in expected.items():
            actual_value = result.get(key)
            if actual_value != expected_value:
                failures.append(
                    f"[{name}] {key}: expected {expected_value!r}, got {actual_value!r}"
                )

        if name in DIRECTNESS_GOLDEN:
            conf_comp = result["confidence_components"]
            for key, expected_value in DIRECTNESS_GOLDEN[name].items():
                actual_value = conf_comp.get(key)
                if actual_value != expected_value:
                    failures.append(
                        f"[{name}] confidence_components.{key}: expected {expected_value!r}, got {actual_value!r}"
                    )
            if not conf_comp.get("direct_rationale"):
                failures.append(f"[{name}] confidence_components.direct_rationale: missing/empty")

        if name in QUALITATIVE_GOLDEN:
            clar_comp = result["clarity_components"]
            for key, expected_value in QUALITATIVE_GOLDEN[name].items():
                actual_value = clar_comp.get(key)
                if actual_value != expected_value:
                    failures.append(
                        f"[{name}] clarity_components.{key}: expected {expected_value!r}, got {actual_value!r}"
                    )

        if name in VERIFICATION_GOLDEN:
            conf_comp = result["confidence_components"]
            for key, expected_value in VERIFICATION_GOLDEN[name].items():
                actual_value = conf_comp.get(key)
                if actual_value != expected_value:
                    failures.append(
                        f"[{name}] confidence_components.{key}: expected {expected_value!r}, got {actual_value!r}"
                    )
            if not conf_comp.get("verify_rationale"):
                failures.append(f"[{name}] confidence_components.verify_rationale: missing/empty")

    assert DIRECTNESS_GOLDEN["over_attributed"]["direct_score"] < DIRECTNESS_GOLDEN["triangulated_contribution"]["direct_score"], (
        "Acceptance check: an over-attributed thin-evidence claim must score "
        "LOWER on Directness than a triangulated contribution claim."
    )

    assert QUALITATIVE_GOLDEN["qualitative"]["definition_score"] == 1.25, (
        "Acceptance check: a fully-answered qualitative submission must reach full "
        "Narrative Definition marks without a stated number or named logframe target "
        "(neither has_number nor has_target apply to narrative evidence)."
    )

    assert VERIFICATION_GOLDEN["count_only_indicator"]["verify_score"] < VERIFICATION_GOLDEN["provenance_marked_na"]["verify_score"], (
        "Acceptance check: unanswered provenance items must lower Verification "
        "more than the same items honestly marked 'Not applicable'."
    )

    # -----------------------------------------------------------------------
    # Boundary tests: threshold alignment and council-audit fixes
    # -----------------------------------------------------------------------

    # 1. Verdict and diag_state must agree at the 4.0 threshold
    #    conf=3.9, clar=3.9 → both below threshold: verdict "High risk", diag NOT "STRONG"
    _b_low = evaluator.evaluate_submission({
        "result_statement": "Reached 250 households with hygiene kits in Q1 2025.",
        "target_group": "Households",
        "timeframe": "Q1 2025",
        "geographic_scope": "Tamale",
        "additional_context": "MEL lead owns this result.",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "External partner review",
        "logframe_indicator": "Number of households reached",
        "logframe_target": "200",
        "logframe_achievement": "250",
        "beneficiary_voice": "",
        "evidence": [{"type": "Attendance sheets / participant registers",
                       "description": "Distribution logs from 10 community centres, signed and dated.",
                       "recency": "March 2025", "verified_by": "District Officer"}],
        "provenance_checklist": {"collector_independent": "Yes", "recall_period_ok": "Yes"},
    })
    # Force scores to known boundary values via direct threshold check
    _diag_low, _ = diagnostics.get_diagnostic_state(3.9, 3.9, [], "")
    if _diag_low == "STRONG":
        failures.append("Boundary: conf=3.9, clar=3.9 should NOT produce diag_state STRONG")
    _vert_below_threshold = evaluator.SUBMISSION_THRESHOLD
    if 3.9 >= _vert_below_threshold or 3.9 >= _vert_below_threshold:
        pass  # Would be high risk — just confirming constant is 4.0
    assert evaluator.SUBMISSION_THRESHOLD == 4.0, "SUBMISSION_THRESHOLD must be 4.0"

    # 2. At exactly 4.0: diag_state is STRONG (with non-empty beneficiary voice)
    _diag_at, _ = diagnostics.get_diagnostic_state(4.0, 4.0, [],
        "Anecdotal beneficiary quotes only (uncollected, not systematic)")
    if _diag_at != "STRONG":
        failures.append(f"Boundary: conf=4.0, clar=4.0 with BV should be STRONG, got {_diag_at!r}")

    # 3. Core alignment: "Strong KPI" verdict only fires when BOTH axes >= SUBMISSION_THRESHOLD=4.0
    #    which is exactly when diag_state is "STRONG". This eliminates the old contradiction
    #    where verdict said "Strong KPI" (at >= 3.5) but diag_state said "NEEDS REFINEMENT" (< 4.0).
    _bv_anecdotal_label = "Anecdotal beneficiary quotes only (uncollected, not systematic)"
    _cases_alignment = [
        # (conf, clar, expected_diag, expected_verdict_prefix)
        (4.0, 4.0, "STRONG",          "Strong KPI"),
        (4.0, 3.5, "NEEDS REFINEMENT","Misleading KPI"),  # conf OK, clar below 4.0
        (3.5, 4.0, "NEEDS REFINEMENT","Well-defined but weak"),  # clar OK, conf below 4.0
        (3.5, 3.5, "NEEDS REFINEMENT","High risk"),  # both below 4.0
    ]
    for conf, clar, expected_diag, expected_verdict_prefix in _cases_alignment:
        _diag_s, _ = diagnostics.get_diagnostic_state(conf, clar, [], _bv_anecdotal_label)
        if _diag_s != expected_diag:
            failures.append(
                f"Threshold alignment: conf={conf}, clar={clar}: "
                f"expected diag {expected_diag!r}, got {_diag_s!r}"
            )
        # Verify the evaluator verdict also agrees with threshold (conf >= 4.0, clar >= 4.0)
        _conf_high = conf >= evaluator.SUBMISSION_THRESHOLD
        _clar_high = clar >= evaluator.SUBMISSION_THRESHOLD
        _actual_verdict_key = (_conf_high, _clar_high)
        _verdicts_map = {
            (True,  True):  "Strong KPI",
            (True,  False): "Misleading KPI",
            (False, True):  "Well-defined but weak",
            (False, False): "High risk",
        }
        _actual_verdict_prefix = _verdicts_map[_actual_verdict_key]
        if _actual_verdict_prefix != expected_verdict_prefix:
            failures.append(
                f"Verdict prefix mismatch: conf={conf}, clar={clar}: "
                f"expected {expected_verdict_prefix!r}, got {_actual_verdict_prefix!r}"
            )

    # 4. BV bonus capped at 0.1 without method_detail for top tiers
    _bv_no_detail = evaluator.compute_beneficiary_voice_bonus(
        "Direct beneficiary feedback collected (e.g., Lean Data survey, focus groups, NPS)", "")
    if _bv_no_detail != 0.1:
        failures.append(f"BV bonus without detail should be 0.1, got {_bv_no_detail}")
    _bv_with_detail = evaluator.compute_beneficiary_voice_bonus(
        "Direct beneficiary feedback collected (e.g., Lean Data survey, focus groups, NPS)",
        "Phone survey with 80 farmers in March 2025, 20-minute structured interview.")
    if _bv_with_detail != 0.5:
        failures.append(f"BV bonus with sufficient detail should be 0.5, got {_bv_with_detail}")

    # 5. Anecdotal BV tier unaffected by detail requirement (detail only gates top tiers)
    _bv_anecdotal = evaluator.compute_beneficiary_voice_bonus(
        "Anecdotal beneficiary quotes only (uncollected, not systematic)", "")
    if _bv_anecdotal != 0.1:
        failures.append(f"Anecdotal BV bonus should be 0.1, got {_bv_anecdotal}")

    # 6. Qualitative evidence type is exempt from no-numbers confidence penalty
    _qual_result = evaluator.evaluate_submission({
        "result_statement": "Women reported increased sense of agency over household decisions.",
        "target_group": "Women in savings groups",
        "timeframe": "2025",
        "geographic_scope": "Volta Region",
        "additional_context": "",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "No external review",
        "logframe_indicator": "",
        "logframe_target": "",
        "logframe_achievement": "",
        "beneficiary_voice": "",
        "evidence": [{"type": "Outcome harvesting",
                       "description": "Outcomes collected from 3 community sessions using participatory methods.",
                       "recency": "2025", "verified_by": "MEL Officer"}],
        "provenance_checklist": {},
    })
    # Outcome harvesting has no numbers in result — must NOT apply the ×0.6 penalty
    _raw_conf = _qual_result.get("raw_confidence_score", 0)
    _penalized_conf = _qual_result.get("confidence_score", 0)
    _mult = _qual_result.get("content_quality_multiplier", 1.0)
    if _mult < 0.6:
        failures.append(
            f"Qualitative evidence (Outcome harvesting) with no numbers in result statement "
            f"should NOT apply ×0.6 penalty; got multiplier={_mult}"
        )

    # 7. Qualitative evidence type ladder tier (council XVI Fix 1)
    #    EVIDENCE_TYPE_LADDER_TIER must now classify these three types correctly.
    _ladder_cases = [
        ("Case study", "Moderate"),
        ("Outcome harvesting", "Stronger"),
        ("Beneficiary narrative or testimony", "Moderate"),
        ("Baseline and endline study", "Stronger"),
    ]
    for _ev_type, _expected_tier in _ladder_cases:
        _ladder = evaluator.get_evidence_ladder(_ev_type, "some evidence description from field", "Evaluator")
        _actual_tier = _ladder.get("dominant_tier")
        if _actual_tier != _expected_tier:
            failures.append(
                f"Evidence ladder tier for '{_ev_type}': expected {_expected_tier!r}, got {_actual_tier!r}"
            )

    # -----------------------------------------------------------------------

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)

    print(f"PASS: {len(CASES)} golden submissions evaluated, all scores match.")
    print("PASS: boundary tests — threshold alignment, BV bonus gating, qualitative exemption, evidence ladder tiers.")


def run_systemic_gaps():
    """evaluator.DIMENSION_MAP / compute_systemic_gaps() -- the Agency
    Dashboard's systemic-gaps ranking. Synthetic evaluations engineered so a
    known dimension (Verification) fails a known fraction of the time."""
    failures = []

    def _ev(direct=2.0, verify=2.0, recency=1.0, definition=1.25,
             measurement=1.25, integrity=1.0, scope=0.75, governance=0.75,
             verify_level=5):
        return {
            "confidence_components": {
                "direct_score": direct, "verify_score": verify,
                "recency_score": recency, "verify_level": verify_level,
            },
            "clarity_components": {
                "definition_score": definition, "measurement_score": measurement,
                "integrity_score": integrity, "scope_score": scope,
                "governance_score": governance,
            },
        }

    # Empty input -> no crash, empty result.
    if evaluator.compute_systemic_gaps([]) != []:
        failures.append("compute_systemic_gaps([]) should return [] without raising")

    # 10 evaluations: 6 with a failing Verification score (< 60% of 2.0 = 1.2),
    # 4 passing -- every other dimension always passes (full marks).
    evals = (
        [_ev(verify=0.5, verify_level=1) for _ in range(6)] +
        [_ev(verify=2.0, verify_level=5) for _ in range(4)]
    )
    gaps = evaluator.compute_systemic_gaps(evals)
    gap_by_dim = {g["dimension"]: g for g in gaps}

    verify_gap = gap_by_dim.get("Verification")
    if not verify_gap:
        failures.append("compute_systemic_gaps did not return a Verification row")
    elif abs(verify_gap["fail_pct"] - 60.0) > 0.01:
        failures.append(f"Verification fail_pct expected 60.0, got {verify_gap['fail_pct']}")
    elif verify_gap["n_evaluated"] != 10:
        failures.append(f"Verification n_evaluated expected 10, got {verify_gap['n_evaluated']}")
    elif abs(verify_gap.get("verify_source_missing_pct", -1) - 60.0) > 0.01:
        failures.append(
            f"verify_source_missing_pct (verify_level<=1 rate) expected 60.0, "
            f"got {verify_gap.get('verify_source_missing_pct')}"
        )

    # Every other dimension should be at 0% fail (always full marks in this fixture).
    for dim, (comp_key, score_key, _max_val) in evaluator.DIMENSION_MAP.items():
        if dim == "Verification":
            continue
        row = gap_by_dim.get(dim)
        if not row or row["fail_pct"] != 0.0:
            failures.append(f"{dim} should be 0% fail in this fixture, got {row}")

    # Ranking: Verification (60% fail) must sort first (descending fail_pct).
    if gaps[0]["dimension"] != "Verification":
        failures.append(f"compute_systemic_gaps should rank Verification first, got {gaps[0]['dimension']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: systemic gaps — DIMENSION_MAP/compute_systemic_gaps ranking, fail_pct, and "
          "verify_source_missing_pct verified.")


def run_framework_crosswalk():
    """framework_crosswalk.evaluate_frameworks() -- pass/fail determination per named
    standard, using the universal per-criterion thresholds (not framework-specific bars)."""
    failures = []

    def _ev(direct=2.0, verify=2.0, recency=1.0, definition=1.25,
             measurement=1.25, integrity=1.0, scope=0.75, governance=0.75):
        return {
            "confidence_components": {
                "direct_score": direct, "verify_score": verify, "recency_score": recency,
            },
            "clarity_components": {
                "definition_score": definition, "measurement_score": measurement,
                "integrity_score": integrity, "scope_score": scope,
                "governance_score": governance,
            },
        }

    # 1. A submission at full marks on every dimension -> every framework should be
    #    submission-ready, no failing rows anywhere.
    full_marks = _ev()
    results = framework_crosswalk.evaluate_frameworks(full_marks)
    if set(results.keys()) != set(framework_crosswalk.FRAMEWORKS.keys()):
        failures.append(f"evaluate_frameworks should return one entry per FRAMEWORKS key, got {list(results.keys())}")
    for fw_key, fw in results.items():
        if not fw["overall_ready"]:
            failures.append(f"{fw_key} should be overall_ready at full marks, got {fw}")
        for row in fw["rows"]:
            if not row["pass"]:
                failures.append(f"{fw_key}/{row['criterion']} should pass at full marks, got {row}")
            if "remediation" in row:
                failures.append(f"{fw_key}/{row['criterion']} should not carry remediation text when passing")

    # 2. Fail Verification specifically (below the 1.2/2.0 universal threshold). Every
    #    framework that cites Verification (per FRAMEWORKS) must report it failing, with a
    #    citation and remediation text; a framework that doesn't cite Verification must not
    #    mention it at all (not pass, not fail -- absent, meaning "not directly assessed").
    weak_verify = _ev(verify=0.5)
    results2 = framework_crosswalk.evaluate_frameworks(weak_verify)
    for fw_key, fw in results2.items():
        cites_verification = "Verification" in framework_crosswalk.FRAMEWORKS[fw_key]["criteria"]
        row = next((r for r in fw["rows"] if r["criterion"] == "Verification"), None)
        if cites_verification:
            if not row:
                failures.append(f"{fw_key} cites Verification in FRAMEWORKS but evaluate_frameworks omitted it")
            elif row["pass"]:
                failures.append(f"{fw_key}/Verification should fail at verify_score=0.5, got {row}")
            elif not row.get("remediation"):
                failures.append(f"{fw_key}/Verification failing row is missing remediation text")
            elif fw["overall_ready"]:
                failures.append(f"{fw_key} should not be overall_ready with a failing cited criterion")
        elif row is not None:
            failures.append(f"{fw_key} does not cite Verification in FRAMEWORKS but evaluate_frameworks returned a row for it")

    # 3. Degrade gracefully: falsy input -> {}, never raises. A dict missing the expected
    #    component keys entirely -> valid (empty-rows) result, not a crash.
    if framework_crosswalk.evaluate_frameworks({}) != {}:
        failures.append("evaluate_frameworks({}) should return {}")
    if framework_crosswalk.evaluate_frameworks(None) != {}:
        failures.append("evaluate_frameworks(None) should return {} without raising")
    try:
        empty_result = framework_crosswalk.evaluate_frameworks({"confidence_components": {}, "clarity_components": {}})
        if any(fw["rows"] for fw in empty_result.values()):
            failures.append("evaluate_frameworks with empty component dicts should produce zero rows everywhere")
    except Exception as exc:
        failures.append(f"evaluate_frameworks raised on a dict with empty component sub-dicts: {exc}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: framework crosswalk — pass/fail via universal thresholds, per-framework "
          "citation coverage, and graceful degradation verified.")


if __name__ == "__main__":
    run()
    run_systemic_gaps()
    run_framework_crosswalk()
