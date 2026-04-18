"""
evaluator.py — v2 Dual-Axis Confidence + Clarity scoring for Impact-Receipts.

Anchored in USAID DQA, OECD-DAC Evaluation Criteria, and Bond Evidence Principles.
Fully deterministic — same inputs always produce the same outputs. No API calls.

Two independent axes, each 0–5.0:
  Confidence  — how much should we trust the evidence?  (Directness + Verification + Recency)
  Clarity     — can someone else interpret this result the same way?  (5 sub-components)
"""

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Level → directness mapping (Section 4.1)
# ---------------------------------------------------------------------------

EVIDENCE_TYPE_DIRECTNESS = {
    # Current form labels
    "Attendance sheets / participant registers": 4,
    "Raw datasets or survey exports":            5,
    "Partner verification letters":              3,
    "Photos with metadata":                      4,
    "Tracer survey results":                     4,
    "Financial records":                         5,
    "Third-party audits":                        3,
    # Legacy / long-form labels (backward compat)
    "Partner verification letters or reports":   3,
    "Photos with metadata (timestamps, GPS)":    4,
    "Financial records / receipts":              5,
    "Third-party evaluation report":             3,
    "Survey summary / assessment report":        3,
    "Government / administrative records":       5,
    "Field observation notes":                   2,
    "Payroll records":                           5,
    "Other":                                     2,
}

# ---------------------------------------------------------------------------
# Verification level lookup tables (Section 4.2)
# ---------------------------------------------------------------------------

INTERNAL_REVIEW_LEVEL = {
    # Current form labels
    "Reviewed by MEL Officer":                   3,
    "Collected only (no review)":                2,
    "Not reviewed":                              0,
    # Legacy labels (backward compat)
    "Reviewed by M&E Officer":                   3,
    "Reviewed by Program Manager":               3,
    "Reviewed by senior leadership or board":    3,
    "Reviewed by multiple internal stakeholders": 3,
    "Other":                                     3,
}

EXTERNAL_REVIEW_LEVEL = {
    # Current form labels
    "Verified by independent third party":       5,
    "External partner review":                   4,
    "No external review":                        0,
    # Legacy labels (backward compat)
    "Reviewed by partner organisation":          4,
    "Reviewed by independent evaluator":         5,
    "Reviewed by donor representative":          5,
    "Third-party audit completed":               5,
    "Other":                                     4,
}

# ---------------------------------------------------------------------------
# Month parser helpers
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3,   "mar": 3, "april": 4,    "apr": 4,
    "may": 5,     "june": 6, "jun": 6,     "july": 7,  "jul": 7,
    "august": 8,  "aug": 8, "september": 9, "sep": 9,  "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _parse_month_year(text: str):
    """Return (year, month) int tuple from text like 'June 2024', or None."""
    if not text:
        return None
    text_l = text.lower()
    year_m = re.search(r"\b(20\d{2})\b", text_l)
    if not year_m:
        return None
    year = int(year_m.group(1))
    for name, num in _MONTH_MAP.items():
        if name in text_l:
            return (year, num)
    return None


def _parse_report_end_date(timeframe: str):
    """
    Extract the end month/year from a timeframe string like 'January–June 2025'.
    Returns the last parseable (year, month) found, or None.
    """
    if not timeframe:
        return None
    text_l = timeframe.lower()
    year_m = re.search(r"\b(20\d{2})\b", text_l)
    if not year_m:
        return None
    year = int(year_m.group(1))
    last_month = None
    for name, num in _MONTH_MAP.items():
        if name in text_l:
            if last_month is None or num > last_month:
                last_month = num
    if last_month is None:
        return None
    return (year, last_month)


# ---------------------------------------------------------------------------
# Core math functions (public, Section 4 / Appendix A)
# ---------------------------------------------------------------------------

def compute_confidence(direct_level: int, verify_level: int, recency_level: int) -> float:
    direct_score  = (direct_level  / 5) * 2.0
    verify_score  = (verify_level  / 5) * 2.0
    recency_score = (recency_level / 5) * 1.0
    return round(direct_score + verify_score + recency_score, 1)


def compute_clarity(
    definition_yes_count: int,
    measurement_yes_count: int,
    missing_data: str,
    audit_trail: str,
    coverage: str,
    sample_ok: bool,
    governance_yes_count: int,
) -> float:
    definition  = (definition_yes_count  / 3) * 1.25
    measurement = (measurement_yes_count / 3) * 1.25
    integrity   = max(
        0,
        1.0
        - (0.5 if missing_data == "Significant" else 0.25 if missing_data == "Minor" else 0)
        - (0.25 if audit_trail == "No" else 0),
    )
    scope       = min(
        0.75,
        (0.4 if coverage == "Full" else 0.25 if coverage == "Partial" else 0)
        + (0.35 if sample_ok else 0),
    )
    governance  = (governance_yes_count / 3) * 0.75
    return round(definition + measurement + integrity + scope + governance, 2)


def interpret_score(score: float) -> tuple:
    """Return (label, meaning) for either axis."""
    if score >= 4.5:
        return "Strong",    "Low risk. Suitable for board/donor reporting."
    if score >= 3.5:
        return "Acceptable", "Minor gaps. Review the suggested fixes before submission."
    if score >= 2.5:
        return "Weak",      "Significant gaps. Strengthen before you submit."
    return "High Risk",     "Not yet defensible. Close the gaps below first."


# ---------------------------------------------------------------------------
# Signal functions (public)
# ---------------------------------------------------------------------------

def get_directness_level(evidence_type: str, description: str) -> int:
    """Map evidence type → directness level; downgrade if description flags gaps."""
    level = EVIDENCE_TYPE_DIRECTNESS.get(evidence_type, 2)
    desc_lower = (description or "").lower()
    if any(k in desc_lower for k in ("sample", "partial", "missing")):
        level = max(0, level - 1)
    return level


def _level_from_verifier(text: str) -> int:
    """Keyword-based level from the 'verified by' free-text field."""
    if not text or not text.strip():
        return 0
    t = text.lower()
    if any(k in t for k in ("government", "ministry", "district officer", "national", "third-party")):
        return 5
    if any(k in t for k in ("partner", "external", "independent", "evaluator", "donor", "ngo", "district")):
        return 4
    if any(k in t for k in ("m&e", "mel", "manager", "officer", "program", "field")):
        return 3
    return 2  # someone is named but role is unclear


def get_verification_level(
    internal_review: str,
    external_review: str,
    verifier_text: str,
) -> int:
    int_level = INTERNAL_REVIEW_LEVEL.get(internal_review, 0)
    ext_level = EXTERNAL_REVIEW_LEVEL.get(external_review, 0)
    ver_level = _level_from_verifier(verifier_text)
    level = max(int_level, ext_level, ver_level)
    # Override: if no formal review at all and no verifier named → force 1
    if int_level == 0 and ext_level == 0 and not (verifier_text or "").strip():
        level = 1
    return level


def get_recency_level(evidence_date: str, report_end_date) -> int:
    """
    Compute recency level from evidence_date string and report_end_date.
    report_end_date may be a string or an already-parsed (year, month) tuple.
    Returns 0 if dates cannot be parsed.
    """
    if not evidence_date:
        return 0
    ev = _parse_month_year(evidence_date)
    if ev is None:
        return 0

    if isinstance(report_end_date, tuple):
        rp = report_end_date
    elif isinstance(report_end_date, str):
        rp = _parse_month_year(report_end_date)
    else:
        rp = None

    if rp:
        months_between = abs((ev[0] - rp[0]) * 12 + (ev[1] - rp[1]))
    else:
        now = datetime.now()
        months_between = abs((now.year - ev[0]) * 12 + (now.month - ev[1]))

    if months_between == 0:
        return 5
    if months_between <= 3:
        return 4
    if months_between <= 6:
        return 3
    if months_between <= 12:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Clarity parameter derivation (private)
# ---------------------------------------------------------------------------

_STRUCTURED_EV_TYPES = {
    "Attendance sheets / participant registers",
    "Raw datasets or survey exports",
    "Financial records / receipts",
    "Government / administrative records",
    "Tracer survey results",
    "Payroll records",
}

_METHOD_KEYWORDS = (
    "session", "district", "kobo", "survey", "interview",
    "observation", "register", "signed", "collected", "verified",
    "training", "household", "sample",
)

_GEO_KEYWORDS = re.compile(
    r"\b(districts?|regions?|states?|counties?|villages?|wards?|zones?|sites?|provinces?|divisions?)\b",
    re.IGNORECASE,
)


def _derive_clarity_params(submission: dict) -> dict:
    statement       = submission.get("result_statement", "") or ""
    timeframe       = (submission.get("timeframe", "") or "").strip()
    target_group    = (submission.get("target_group", "") or "").strip()
    geographic_scope = (submission.get("geographic_scope", "") or "").strip()
    additional_ctx  = (submission.get("additional_context", "") or "").strip()
    internal_review = submission.get("internal_review", "Not reviewed") or "Not reviewed"
    external_review = submission.get("external_review", "No external review") or "No external review"

    ev_list    = submission.get("evidence", []) or []
    ev         = ev_list[0] if ev_list else {}
    ev_desc    = (ev.get("description", "") or "").strip()
    ev_type    = ev.get("type", "") or ""
    verified_by = (ev.get("verified_by", "") or "").strip()

    # --- Definition clarity (3 yes/no) ---
    has_number   = bool(re.search(r"\b\d[\d,]*\b", statement))
    has_timeframe = bool(timeframe and timeframe.lower() not in ("not specified",))
    has_target   = bool(target_group and target_group.lower() not in ("not specified",))
    definition_yes = sum([has_number, has_timeframe, has_target])

    # --- Measurement quality (3 yes/no) ---
    desc_lower = ev_desc.lower()
    has_method_desc    = len(ev_desc) > 50
    has_method_keyword = any(k in desc_lower for k in _METHOD_KEYWORDS)
    has_structured     = ev_type in _STRUCTURED_EV_TYPES
    measurement_yes    = sum([has_method_desc, has_method_keyword, has_structured])

    # --- Missing data ---
    if any(k in desc_lower for k in ("significant", "majority missing", "most data missing")):
        missing_data = "Significant"
    elif any(k in desc_lower for k in ("partial", "minor gap", "some missing", "not all", "incomplete")):
        missing_data = "Minor"
    else:
        missing_data = "None"

    # --- Audit trail ---
    audit_trail = "Yes" if verified_by else "No"

    # --- Coverage ---
    geo_text = geographic_scope + " " + statement
    geo_specific = bool(geographic_scope and geographic_scope.lower() not in ("not specified",))
    geo_detailed = bool(_GEO_KEYWORDS.search(geo_text))
    if geo_specific and geo_detailed:
        coverage = "Full"
    elif geo_specific:
        coverage = "Partial"
    else:
        coverage = "Limited"

    # --- Sample OK ---
    sample_ok = bool(re.search(r"\b\d[\d,]*\b", ev_desc)) or bool(verified_by)

    # --- Governance (3 yes/no) ---
    has_owner  = bool(verified_by)
    has_review = (
        internal_review not in ("Not reviewed",)
        or external_review not in ("No external review",)
    )
    has_context = bool(additional_ctx)
    governance_yes = sum([has_owner, has_review, has_context])

    return {
        "definition_yes_count":  definition_yes,
        "measurement_yes_count": measurement_yes,
        "missing_data":          missing_data,
        "audit_trail":           audit_trail,
        "coverage":              coverage,
        "sample_ok":             sample_ok,
        "governance_yes_count":  governance_yes,
    }


# ---------------------------------------------------------------------------
# What To Fix engine (public, Section 7)
# ---------------------------------------------------------------------------

def get_what_to_fix(confidence_components: dict, clarity_components: dict) -> list:
    """
    Return a list of dicts with keys: dimension, message, score_impact.
    Triggers use action verbs and show score impact. No forbidden words.
    """
    fixes = []

    direct_score  = confidence_components.get("direct_score", 0)
    verify_score  = confidence_components.get("verify_score", 0)
    recency_score = confidence_components.get("recency_score", 0)
    verify_level  = confidence_components.get("verify_level", 0)

    # Confidence triggers
    if direct_score < (3 / 5) * 2.0:
        fixes.append({
            "dimension": "confidence",
            "message": (
                "Add a primary record — signed attendance sheets, payroll records, or a "
                "KoboToolbox export — so your evidence directly ties to the claim."
            ),
            "score_impact": "+up to 0.8 on Confidence",
        })

    if verify_score < (3 / 5) * 2.0:
        current  = round(verify_score, 1)
        potential = round((4 / 5) * 2.0, 1)
        gain      = round(potential - current, 1)
        fixes.append({
            "dimension": "confidence",
            "message": (
                f"Name an internal reviewer or an external partner. "
                f"Doing so moves your verification score from {current} to {potential}."
            ),
            "score_impact": f"+{gain} on Confidence",
        })

    if recency_score < (3 / 5) * 1.0:
        fixes.append({
            "dimension": "confidence",
            "message": (
                "Confirm your evidence date is within 6 months of the reporting period end, "
                "or attach more recent confirmatory evidence."
            ),
            "score_impact": "+up to 0.4 on Confidence",
        })

    # Clarity sub-scores
    def_count  = clarity_components.get("definition_yes_count", 0)
    meas_count = clarity_components.get("measurement_yes_count", 0)
    missing_data = clarity_components.get("missing_data", "None")
    audit_trail  = clarity_components.get("audit_trail", "Yes")
    coverage     = clarity_components.get("coverage", "Full")
    sample_ok    = clarity_components.get("sample_ok", True)
    gov_count    = clarity_components.get("governance_yes_count", 0)

    def_score  = (def_count  / 3) * 1.25
    meas_score = (meas_count / 3) * 1.25
    integrity  = max(0, 1.0
        - (0.5 if missing_data == "Significant" else 0.25 if missing_data == "Minor" else 0)
        - (0.25 if audit_trail == "No" else 0))
    cov_score  = 0.4 if coverage == "Full" else 0.25 if coverage == "Partial" else 0
    scope      = min(0.75, cov_score + (0.35 if sample_ok else 0))
    gov_score  = (gov_count / 3) * 0.75

    if def_score < 1.0:
        missing_count = 3 - def_count
        impact = round(missing_count * (1.25 / 3), 2)
        fixes.append({
            "dimension": "clarity",
            "message": (
                "Add the missing unit, timeframe, or target group to your result statement "
                "so any reader interprets it the same way you do."
            ),
            "score_impact": f"+{impact} on Clarity",
        })

    if meas_score < 1.0:
        fixes.append({
            "dimension": "clarity",
            "message": (
                "Describe your collection method and sampling approach in the evidence description "
                "— specify the instrument used and how participants were selected."
            ),
            "score_impact": "+up to 0.83 on Clarity",
        })

    if integrity < 0.75:
        fixes.append({
            "dimension": "clarity",
            "message": (
                "Close data gaps with original source records, "
                "or disclose the limitation transparently in the evidence description."
            ),
            "score_impact": "+up to 0.75 on Clarity",
        })

    if scope < 0.5:
        fixes.append({
            "dimension": "clarity",
            "message": (
                "State the sites and groups included and excluded "
                "so the reader can correctly interpret the coverage."
            ),
            "score_impact": "+up to 0.75 on Clarity",
        })

    if gov_score < 0.5:
        fixes.append({
            "dimension": "clarity",
            "message": (
                "Name an owner for this result and describe the decision it will inform — "
                "without ownership the result is not actionable."
            ),
            "score_impact": "+up to 0.5 on Clarity",
        })

    return fixes


# ---------------------------------------------------------------------------
# Public API — evaluate_submission
# ---------------------------------------------------------------------------

def evaluate_submission(submission: dict) -> dict:
    """
    Run v2 dual-axis evaluation on a submission dict.

    Returns a dict with all score components, labels, verdict, and fixes.
    Backward-compat keys (scores, overall_label, label_rationale, key_issues)
    are included so existing app.py report builders continue to work.
    """
    ev_list  = submission.get("evidence", []) or []
    ev       = ev_list[0] if ev_list else {}

    ev_type     = ev.get("type", "") or ""
    ev_desc     = (ev.get("description", "") or "").strip()
    verified_by = (ev.get("verified_by", "") or "").strip()
    ev_date     = (ev.get("recency", "") or "").strip()

    internal_review = submission.get("internal_review", "Not reviewed") or "Not reviewed"
    external_review = submission.get("external_review", "No external review") or "No external review"
    timeframe       = submission.get("timeframe", "") or ""

    report_end = _parse_report_end_date(timeframe)

    # Confidence axis
    direct_level  = get_directness_level(ev_type, ev_desc)
    verify_level  = get_verification_level(internal_review, external_review, verified_by)
    recency_level = get_recency_level(ev_date, report_end)

    direct_score  = round((direct_level  / 5) * 2.0, 2)
    verify_score  = round((verify_level  / 5) * 2.0, 2)
    recency_score = round((recency_level / 5) * 1.0, 2)

    confidence_score = compute_confidence(direct_level, verify_level, recency_level)
    confidence_label, confidence_meaning = interpret_score(confidence_score)

    confidence_components = {
        "direct_level":  direct_level,
        "direct_score":  direct_score,
        "verify_level":  verify_level,
        "verify_score":  verify_score,
        "recency_level": recency_level,
        "recency_score": recency_score,
    }

    # Clarity axis
    clarity_params = _derive_clarity_params(submission)

    def_score_c  = round((clarity_params["definition_yes_count"]  / 3) * 1.25, 2)
    meas_score_c = round((clarity_params["measurement_yes_count"] / 3) * 1.25, 2)
    miss         = clarity_params["missing_data"]
    audit        = clarity_params["audit_trail"]
    integ        = round(max(0, 1.0
        - (0.5 if miss == "Significant" else 0.25 if miss == "Minor" else 0)
        - (0.25 if audit == "No" else 0)), 2)
    cov          = clarity_params["coverage"]
    sok          = clarity_params["sample_ok"]
    scope_c      = round(min(0.75,
        (0.4 if cov == "Full" else 0.25 if cov == "Partial" else 0)
        + (0.35 if sok else 0)), 2)
    gov_score_c  = round((clarity_params["governance_yes_count"] / 3) * 0.75, 2)

    clarity_score = compute_clarity(**clarity_params)
    clarity_label, clarity_meaning = interpret_score(clarity_score)

    clarity_components = {
        **clarity_params,
        "definition_score":  def_score_c,
        "measurement_score": meas_score_c,
        "integrity_score":   integ,
        "scope_score":       scope_c,
        "governance_score":  gov_score_c,
    }

    # Combined verdict (Section 3)
    conf_high = confidence_score >= 3.5
    clar_high = clarity_score   >= 3.5
    _verdicts = {
        (True,  True):  "Strong KPI — ready to submit",
        (True,  False): "Misleading KPI — sharpen the definition before submission",
        (False, True):  "Well-defined but weak evidence — strengthen the verification chain",
        (False, False): "High risk — do not submit until both axes are addressed",
    }
    verdict = _verdicts[(conf_high, clar_high)]

    fixes = get_what_to_fix(confidence_components, clarity_components)

    label_rationale = (
        f"Confidence: {confidence_score}/5.0 ({confidence_label}) — {confidence_meaning} "
        f"Clarity: {clarity_score}/5.0 ({clarity_label}) — {clarity_meaning} "
        f"Combined: {verdict}."
    )

    return {
        # v2 primary keys
        "confidence_score":      confidence_score,
        "clarity_score":         clarity_score,
        "confidence_label":      confidence_label,
        "clarity_label":         clarity_label,
        "confidence_meaning":    confidence_meaning,
        "clarity_meaning":       clarity_meaning,
        "confidence_components": confidence_components,
        "clarity_components":    clarity_components,
        "verdict":               verdict,
        "fixes":                 fixes,
        # backward-compat keys
        "scores": {
            "overall":     {"score": confidence_score, "label": confidence_label, "meaning": confidence_meaning},
            "confidence":  {"score": confidence_score, "label": confidence_label},
            "clarity":     {"score": clarity_score,    "label": clarity_label},
        },
        "overall_label":   confidence_label,
        "label_rationale": label_rationale,
        "key_issues":      [],
    }


def compute_confidence_label(scores: dict) -> tuple:
    """
    Derive confidence label from a scores dict.
    Accepts both v2 format (scores["overall"]) and v1 format (dimension keys).
    Returns (label, hex_color).
    """
    if "overall" in scores:
        label = scores["overall"]["label"]
    elif "confidence" in scores:
        label = scores["confidence"]["label"]
    else:
        # v1 fallback: derive from the three dimension scores
        dim_scores = [
            scores.get("clarity_of_claim",     {}).get("score", 1),
            scores.get("strength_of_evidence", {}).get("score", 1),
            scores.get("independent_review",   {}).get("score", 1),
        ]
        if any(s == 1 for s in dim_scores):
            label = "High Risk"
        elif any(s == 2 for s in dim_scores):
            label = "Weak"
        elif all(s >= 4 for s in dim_scores):
            label = "Strong"
        else:
            label = "Acceptable"

    color_map = {
        "Strong":    "#1B5E20",
        "Acceptable": "#F57F17",
        "Weak":      "#E65100",
        "High Risk": "#B71C1C",
    }
    return label, color_map.get(label, "#9E9E9E")


# ---------------------------------------------------------------------------
# Smoke test — python evaluator.py to verify Section 8 example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    test = {
        "result_statement": (
            "Trained 487 smallholder farmers in climate-smart agriculture "
            "across 3 districts in Northern Ghana between January and June 2025."
        ),
        "target_group":      "Smallholder farmers",
        "timeframe":         "January–June 2025",
        "geographic_scope":  "3 districts in Northern Ghana",
        "evidence": [
            {
                "type":        "Attendance sheets / participant registers",
                "description": (
                    "Signed attendance sheets from 12 training sessions across 3 districts "
                    "in Northern Ghana, verified by District Agriculture Officer."
                ),
                "recency":     "July 2025",
                "verified_by": "District Agriculture Officer",
            }
        ],
        "internal_review":    "Not reviewed",
        "external_review":    "No external review",
        "additional_context": "",
    }

    result = evaluate_submission(test)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    c  = result["confidence_score"]
    cl = result["clarity_score"]
    print(f"\nConfidence: {c}/5.0  ({result['confidence_label']})")
    print(f"Clarity:    {cl}/5.0  ({result['clarity_label']})")
    print(f"Verdict:    {result['verdict']}")

    assert c  == 4.0, f"Expected confidence 4.0, got {c}"
    assert cl == 4.5, f"Expected clarity 4.5, got {cl}"
    print("\nPASS: Section 8 example matches document.")
