"""
donor_templates.py — Donor-specific diagnostic language for Impact-Receipts v3.0.

Covers USAID, FCDO, GIZ, World Bank. Each entry has "low" and "high" guidance
keyed by sub-dimension name. Consumed by app.py Screen 2 diagnostic section.
"""

DONOR_DIAGNOSTICS = {
    "USAID": {
        "Directness": {
            "low": (
                "USAID ADS 201.3.5.7 requires evidence that directly links "
                "programme activities to reported results. Your current score "
                "suggests an assertion without a demonstrated mechanism. "
                "Recommended fix: attach a completed USAID DQA form signed by "
                "a non-programme staff member and reference your programme's "
                "theory of change in the evidence description."
            ),
            "high": (
                "Your Directness score meets USAID DQA standards for "
                "programme evidence. Ensure your DQA form is filed in "
                "your Activity MEL system before submission."
            ),
        },
        "Verification": {
            "low": (
                "USAID ADS 201.3.5.7 Independence criterion requires that "
                "the person verifying results is not directly involved in "
                "programme implementation. Internal review only scores 2/5. "
                "Recommended fix: arrange an external spot-check or have a "
                "non-programme USAID staff member co-sign the DQA."
            ),
            "high": (
                "External verification detected. This meets USAID DQA "
                "Independence criterion. Retain verifier contact details "
                "for audit purposes."
            ),
        },
        "Recency": {
            "low": (
                "USAID DQA requires data collected within the reporting period. "
                "Evidence older than 12 months scores below 3/5. "
                "Recommended fix: collect updated data or clearly annotate "
                "why older data remains valid for this result."
            ),
            "high": "Evidence recency meets USAID DQA Timeliness criterion.",
        },
    },
    "FCDO": {
        "Directness": {
            "low": (
                "FCDO Evaluation Policy (January 2025) requires that results "
                "evidence demonstrates a plausible causal link between "
                "programme activities and reported outcomes. "
                "Recommended fix: include a brief contribution narrative "
                "(2–3 sentences) explaining HOW your programme caused this "
                "result, referencing your theory of change."
            ),
            "high": (
                "Causal mechanism evidence meets FCDO 2025 Evaluation Policy "
                "standards. Ensure contribution narrative is included in "
                "your Annual Review submission."
            ),
        },
        "Verification": {
            "low": (
                "FCDO EQuALS 2 quality standards require independent "
                "verification for results reported in Annual Reviews. "
                "Recommended fix: commission a short external spot-check "
                "or reference an independent evaluation that covers "
                "this result."
            ),
            "high": (
                "Independent verification meets FCDO EQuALS 2 quality "
                "standards. File verifier details with your FCDO "
                "Programme Officer."
            ),
        },
        "BeneficiaryVoice": {
            "low": (
                "FCDO Evaluation Policy (January 2025) requires an equity "
                "and inclusion lens on all programme results. No beneficiary "
                "voice evidence detected. Recommended fix: add a structured "
                "beneficiary feedback mechanism before your next FCDO "
                "Annual Review submission."
            ),
            "high": (
                "Beneficiary voice evidence meets FCDO 2025 equity and "
                "inclusion requirements."
            ),
        },
    },
    "GIZ": {
        "Directness": {
            "low": (
                "GIZ Results-Based Monitoring requires that reported results "
                "are traceable to specific programme outputs and activities. "
                "Recommended fix: reference the specific GIZ output number "
                "from your Results Matrix that this result corresponds to "
                "and attach supporting output documentation."
            ),
            "high": (
                "Output traceability meets GIZ Results-Based Monitoring "
                "standards. Ensure your Results Matrix is updated "
                "before reporting."
            ),
        },
        "Verification": {
            "low": (
                "GIZ monitoring standards require that reported data is "
                "verifiable by a third party. Internal records only score "
                "below threshold. Recommended fix: attach signed attendance "
                "sheets, certificates, or a third-party spot-check report."
            ),
            "high": "Verification meets GIZ third-party verifiability standard.",
        },
    },
    "World Bank": {
        "Directness": {
            "low": (
                "World Bank project reporting requires that PDO-level results "
                "are supported by evidence of causal contribution, not "
                "correlation only. Recommended fix: reference your Project "
                "Appraisal Document theory of change and include baseline "
                "and endline data in your evidence description."
            ),
            "high": (
                "Contribution evidence meets World Bank IEG RAP standards "
                "for project completion reporting."
            ),
        },
    },
}
