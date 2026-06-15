"""
test_app.py — golden tests for evaluator.evaluate_submission().

Locks the CURRENT scoring behaviour for a set of representative submissions
before a structural refactor of app.py. Run with: python test_app.py

As pure helper modules are extracted from app.py (diagnostics.py,
governance.py, ...), extend this file with golden assertions for their
public functions using the same representative inputs.
"""

import evaluator


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
        },
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
    "strong": {
        "confidence_score": 4.2,
        "clarity_score": 5.0,
        "verdict": "Strong KPI — well-positioned for submission",
    },
    "weak": {
        "confidence_score": 0.1,
        "clarity_score": 0.75,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "placeholder": {
        "confidence_score": 0.0,
        "clarity_score": 3.1,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "qualitative": {
        "confidence_score": 3.8,
        "clarity_score": 5.0,
        "verdict": "Strong KPI — well-positioned for submission",
    },
    "missing_recency": {
        "confidence_score": 0.9,
        "clarity_score": 3.95,
        "verdict": "Well-defined but weak evidence — strengthen the verification chain",
    },
    "count_only_indicator": {
        "confidence_score": 3.2,
        "clarity_score": 4.6,
        "verdict": "Well-defined but weak evidence — strengthen the verification chain",
    },
    "over_attributed": {
        "confidence_score": 0.3,
        "clarity_score": 3.23,
        "verdict": "High risk — strengthen both axes before relying on this result",
    },
    "triangulated_contribution": {
        "confidence_score": 4.0,
        "clarity_score": 4.25,
        "verdict": "Strong KPI — well-positioned for submission",
    },
    "partial_logframe_mismatch": {
        "confidence_score": 2.2,
        "clarity_score": 3.92,
        "verdict": "Well-defined but weak evidence — strengthen the verification chain",
    },
    "provenance_marked_na": {
        "confidence_score": 3.4,
        "clarity_score": 4.6,
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

    assert VERIFICATION_GOLDEN["count_only_indicator"]["verify_score"] < VERIFICATION_GOLDEN["provenance_marked_na"]["verify_score"], (
        "Acceptance check: unanswered provenance items must lower Verification "
        "more than the same items honestly marked 'Not applicable'."
    )

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)

    print(f"PASS: {len(CASES)} golden submissions evaluated, all scores match.")


if __name__ == "__main__":
    run()
