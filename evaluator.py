"""
evaluator.py — v3.0 Dual-Axis Confidence + Clarity scoring for Impact-Receipts.

Anchored in USAID ADS 201.3.5.7, OECD-DAC Evaluation Criteria 2019,
Bond Evidence Principles 2024, FCDO Evaluation Policy January 2025,
and World Bank IEG Process Tracing 2025.
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

# Data-collection & traceability checklist bonus (Section 4.2)
_TRACEABILITY_BONUS = {
    "Yes — an auditor could retrieve the original records":      0.20,
    "Partially — some records would take effort to locate":      0.10,
    "No / not sure":                                              0.0,
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

def score_directness(evidence_description: str, evidence_type: str) -> float:
    """
    5-step Contribution Evidence Ladder.
    Anchored in: World Bank IEG Process Tracing (2025), 3ie Contribution Analysis.
    Returns 1.0–5.0.
    """
    text = ((evidence_description or "") + " " + (evidence_type or "")).lower()

    if any(kw in text for kw in [
        "alternative explanation", "ruled out", "counterfactual",
        "contribution analysis", "process trace", "triangulat",
        "multiple independent sources", "cross-checked", "corroborat",
        "outcome harvest",
    ]):
        return 5.0

    if any(kw in text for kw in [
        "theory of change", "toc", "outcome data", "baseline",
        "endline", "comparison group", "control", "independent evaluation",
        "case stud",
    ]):
        return 4.0

    if any(kw in text for kw in [
        "attendance", "register", "records", "log", "activity report",
        "minutes", "signed", "programme records", "output data",
    ]):
        return 3.0

    if any(kw in text for kw in [
        "survey", "interview", "focus group", "fgd", "observation",
        "beneficiary feedback", "self-report", "perception",
    ]):
        return 2.0

    return 1.0


def get_directness_level(evidence_type: str, description: str) -> int:
    """Thin wrapper around score_directness for backward compatibility."""
    return int(score_directness(description, evidence_type))


def score_beneficiary_voice(evidence_description: str, evidence_type: str) -> float:
    """
    Beneficiary Voice Bonus Dimension (0.0–0.5).
    Anchored in: Bond Evidence Principles 2024 (Voice & Inclusion),
                 60 Decibels Lean Data Methodology,
                 FCDO Evaluation Policy January 2025 (Equity & Inclusion lens).
    """
    text = ((evidence_description or "") + " " + (evidence_type or "")).lower()

    if any(kw in text for kw in [
        "phone survey", "beneficiary survey", "lean data", "third party",
        "independent feedback", "benchmark", "60 decibels", "client voice",
    ]):
        return 0.5

    if any(kw in text for kw in [
        "focus group", "fgd", "post-training survey", "exit survey",
        "participant feedback", "community feedback", "beneficiary interview",
        "client feedback", "community meeting",
    ]):
        return 0.35

    if any(kw in text for kw in [
        "beneficiar", "participant said", "community said", "client said",
        "expressed satisfaction", "reported", "mentioned by",
    ]):
        return 0.15

    return 0.0


_BV_DROPDOWN_SCORES = {
    "Direct beneficiary feedback collected (e.g., Lean Data survey, focus groups, NPS)": 0.5,
    "Beneficiary representatives consulted (community leaders, beneficiary committees)": 0.3,
    "Anecdotal beneficiary quotes only (uncollected, not systematic)": 0.1,
    "No beneficiary voice captured": 0.0,
    "Not applicable to this result type": 0.0,
}


def compute_beneficiary_voice_bonus(beneficiary_voice: str) -> float:
    """
    Returns 0.0–0.5 bonus based on explicit dropdown selection.
    Anchored in Bond Evidence Principles 2024 + 60 Decibels Lean Data.
    """
    return _BV_DROPDOWN_SCORES.get(beneficiary_voice, 0.0)


_TEST_PATTERNS = {"test", "abc", "xxx", "asdf", "qwerty", "lorem", "placeholder", "sample"}


def validate_content_quality(
    result_statement: str,
    evidence_description: str,
    verifier: str,
) -> tuple:
    """
    Returns (quality_multiplier: float, issues: list[str]).
    Multiplier is applied to confidence_score after normal calculation in evaluate_submission().
    compute_confidence() is not touched.
    """
    result  = (result_statement or "").strip()
    ev_desc = (evidence_description or "").strip()
    verif   = (verifier or "").strip()

    multiplier = 1.0
    issues: list = []

    if len(result) < 20:
        multiplier *= 0.3
        issues.append("Result statement is too short (under 20 characters)")

    if len(ev_desc) < 30:
        multiplier *= 0.3
        issues.append("Evidence description is too short (under 30 characters)")

    if len(verif) < 5:
        multiplier *= 0.5
        issues.append("Verifier name is too short or missing detail")

    combined = f"{result} {ev_desc} {verif}".lower()
    test_hits = sum(1 for p in _TEST_PATTERNS if p in combined)
    if test_hits >= 2:
        multiplier *= 0.2
        issues.append("Multiple placeholder/test words detected — please provide real content")

    if result and not any(c.isdigit() for c in result):
        multiplier *= 0.6
        issues.append("Result statement has no numbers — quantified claims score higher")

    return round(multiplier, 2), issues


def evaluate_logframe_linkage(
    indicator: str,
    target: str,
    achievement: str,
    result_statement: str,
) -> dict:
    """
    Checks whether a reported result is tied to an approved logframe indicator.
    Anchored in OECD-DAC 2019 Coherence + USAID DQA Validity.
    Returns {score, state, issues, rationale}.
    """
    indicator   = (indicator or "").strip()
    target      = (target or "").strip()
    achievement = (achievement or "").strip()
    result      = (result_statement or "").strip()

    if not indicator:
        return {
            "score": 0.0,
            "state": "MISSING",
            "issues": [
                "No logframe indicator linked. Donors will not be able to verify this "
                "result against your approved Technical Proposal."
            ],
            "rationale": (
                "OECD-DAC 2019 + USAID DQA: Every reported result must trace to an "
                "approved indicator. Score: 0.0/1.0"
            ),
        }

    score = 0.4
    issues = []

    if not target:
        issues.append(
            "Original target is missing. Donors compare achievements against approved "
            "targets, not internal revised numbers."
        )
    else:
        score += 0.3

    if not achievement:
        issues.append(
            "Actual achievement number is missing. Quantify with % vs target where possible."
        )
    else:
        score += 0.3
        ach_nums = re.findall(r"\d[\d,]*", achievement)
        res_nums = re.findall(r"\d[\d,]*", result)
        if ach_nums and res_nums and not any(n in res_nums for n in ach_nums):
            issues.append(
                "The number in your achievement field does not match any number in your "
                "result statement. Reconcile these to avoid donor flags."
            )
            score -= 0.2

    score = round(max(0.0, score), 2)
    if score >= 0.85:
        state = "STRONG"
    else:
        state = "WEAK"

    return {
        "score": score,
        "state": state,
        "issues": issues,
        "rationale": (
            f"OECD-DAC 2019 + USAID DQA — Logframe linkage "
            f"{'complete and consistent' if state == 'STRONG' else 'partial — gaps exist'}. "
            f"Score: {score:.1f}/1.0"
        ),
    }


def validate_reporting_period(evidence_date, period_start, period_end) -> tuple:
    """
    Checks that evidence_date falls within the stated reporting period.
    Returns (is_valid: bool, message: str, severity: "OK"|"WARNING"|"ERROR").
    All three date args must be date objects; returns (True, "", "OK") if any is None.
    """
    if not evidence_date or not period_start or not period_end:
        return (True, "", "OK")

    if period_start > period_end:
        return (
            False,
            "Reporting period start is AFTER reporting period end. Check your dates.",
            "ERROR",
        )

    if evidence_date < period_start:
        days = (period_start - evidence_date).days
        return (
            False,
            (
                f"Evidence is dated {days} day(s) BEFORE the reporting period started. "
                "Donors may flag this as outside-scope evidence. Confirm this evidence "
                "is relevant to this reporting period."
            ),
            "WARNING",
        )

    if evidence_date > period_end:
        days = (evidence_date - period_end).days
        return (
            False,
            (
                f"Evidence is dated {days} day(s) AFTER the reporting period ended. "
                "This is a common rejection cause. Either revise the reporting period "
                "or flag this evidence as 'post-period validation'."
            ),
            "WARNING",
        )

    return (True, "Evidence date falls within the reporting period.", "OK")


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


# ---------------------------------------------------------------------------
# Evidence Ladder (rule-based tier classification — no score impact)
# ---------------------------------------------------------------------------

EVIDENCE_LADDER_TIERS = ["Basic", "Moderate", "Stronger"]

EVIDENCE_LADDER_KEYWORDS = {
    "Basic": [
        "attendance", "registration form", "registration", "sign-in", "sign in sheet",
        "activity log", "activity report", "participant register", "photo",
    ],
    "Moderate": [
        "follow-up survey", "follow up survey", "tracer survey", "self-report",
        "self report", "self-reported", "testimonial", "feedback survey",
    ],
    "Stronger": [
        "business record", "regulatory record", "tax record", "license", "permit",
        "mentor verification", "mentor report", "baseline", "endline",
        "external evaluation", "third-party evaluation", "independent evaluation",
        "contribution analysis", "comparison group", "control group",
    ],
}

# Evidence-type selectbox label -> ladder tier (structured signal, in addition
# to free-text keyword matches)
EVIDENCE_TYPE_LADDER_TIER = {
    "Attendance sheets / participant registers": "Basic",
    "Photos with metadata": "Basic",
    "Tracer survey results": "Moderate",
    "Financial records": "Stronger",
    "Third-party audits": "Stronger",
    "Partner verification letters": "Stronger",
    "Raw datasets or survey exports": "Stronger",
}

EVIDENCE_LADDER_SUGGESTIONS = {
    "Basic": (
        "Your evidence base is mainly **Basic** tier (attendance, registration, "
        "logs, photos). To move up to **Moderate**, add a follow-up survey or "
        "participant testimonial that captures self-reported outcomes."
    ),
    "Moderate": (
        "Your evidence base is mainly **Moderate** tier (self-reported surveys, "
        "testimonials). To move up to **Stronger**, add baseline/endline data, "
        "a mentor verification report, or an external evaluation."
    ),
    "Stronger": (
        "Your evidence base already includes **Stronger**-tier sources. To "
        "strengthen further, add a comparison group or a contribution analysis "
        "that rules out alternative explanations."
    ),
    None: (
        "No recognizable evidence sources were detected. Describe your evidence "
        "(e.g., attendance records, follow-up surveys, baseline/endline data) "
        "to get an Evidence Ladder assessment."
    ),
}


def get_evidence_ladder(ev_type: str, ev_desc: str, verifier_text: str = "") -> dict:
    """Rule-based classification of evidence sources into Basic/Moderate/Stronger
    tiers. Deterministic keyword matching only — no score impact."""
    text = " ".join([ev_type or "", ev_desc or "", verifier_text or ""]).lower()

    matches = {tier: [] for tier in EVIDENCE_LADDER_TIERS}
    for tier, keywords in EVIDENCE_LADDER_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matches[tier].append(kw)

    type_tier = EVIDENCE_TYPE_LADDER_TIER.get(ev_type)
    counts = {tier: len(matches[tier]) for tier in EVIDENCE_LADDER_TIERS}
    if type_tier:
        counts[type_tier] += 1

    if all(c == 0 for c in counts.values()):
        dominant = None
    else:
        # Tie-break toward the lower tier: don't over-credit a single
        # high-tier mention if Basic-tier evidence is just as prevalent.
        dominant = max(EVIDENCE_LADDER_TIERS, key=lambda t: (counts[t], -EVIDENCE_LADDER_TIERS.index(t)))

    return {
        "tier_counts": counts,
        "tier_matches": matches,
        "dominant_tier": dominant,
        "suggestion": EVIDENCE_LADDER_SUGGESTIONS[dominant],
    }


# ---------------------------------------------------------------------------
# Funder Readiness flags — Limitations disclosure & Learning/Adaptation
# (informational only — no score impact, v3.2 weighting unchanged)
# ---------------------------------------------------------------------------

LIMITATIONS_KEYWORDS = [
    "limitation", "limitations", "cannot conclude", "cannot confirm",
    "cannot attribute", "does not capture", "not generalizable",
    "caveat", "small sample size", "self-reported and may",
]

LEARNING_KEYWORDS = [
    "we learned", "lesson learned", "lessons learned", "we adapted",
    "we adjusted", "we revised", "as a result, we", "going forward, we will",
    "we changed our approach",
]


def get_funder_readiness_flags(result_statement: str, evidence_description: str) -> dict:
    """Rule-based detection of limitations-disclosure and learning/adaptation
    language. Informational only — does not affect any score."""
    text = " ".join([result_statement or "", evidence_description or ""]).lower()

    limitations_hits = [kw for kw in LIMITATIONS_KEYWORDS if kw in text]
    learning_hits = [kw for kw in LEARNING_KEYWORDS if kw in text]

    return {
        "limitations": {"detected": bool(limitations_hits), "matched": limitations_hits},
        "learning":    {"detected": bool(learning_hits),    "matched": learning_hits},
    }


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


def get_provenance_bonus(checklist: dict) -> float:
    """
    Data-collection & traceability checklist bonus (0.0-0.6), added to the
    Verification score (capped at 2.0 overall).
    Anchored in USAID ADS 201.3.5.7 — Reliability + Precision.
    """
    checklist = checklist or {}
    bonus = 0.0
    if checklist.get("sampling_documented"):
        bonus += 0.15
    if checklist.get("double_counting_checked"):
        bonus += 0.15
    if checklist.get("recall_bias_considered"):
        bonus += 0.10
    bonus += _TRACEABILITY_BONUS.get(checklist.get("auditor_traceable", ""), 0.0)
    return round(bonus, 2)


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
# Indicator Maturity (rule-based count-only detection + rewrite templates)
# ---------------------------------------------------------------------------

_INDICATOR_VERB_BEHAVIOR = {
    "trained":     "applying the skills/practices from the training",
    "supported":   "sustaining the support received",
    "reached":     "adopting the promoted practice",
    "disbursed":   "using the funds for their intended purpose",
    "distributed": "using the items for their intended purpose",
    "enrolled":    "remaining enrolled or completing the program",
    "registered":  "actively using the registration or service",
    "served":      "sustaining the benefit received",
    "assisted":    "sustaining the benefit received",
}

_COUNT_ONLY_INDICATOR_RE = re.compile(
    r"\bnumber of\s+(?P<group>[a-z][a-z\s\-/]*?)\s+"
    r"(?P<verb>trained|supported|reached|disbursed|distributed|enrolled|registered|served|assisted)\b",
    re.IGNORECASE,
)

_ALREADY_PROPORTIONAL_RE = re.compile(r"%|\bpercent\b|\bpercentage\b|\brate of\b", re.IGNORECASE)


def get_indicator_maturity(indicator_text: str) -> dict:
    """Rule-based check for count-only ('Number of X trained/...') indicators.
    Returns a comparison ladder + a small Measurement-score adjustment
    (clamped by the caller to the existing 0-1.25 Measurement range)."""
    text = (indicator_text or "").strip()
    if not text:
        return {"flagged": False, "rows": [], "adjustment": 0.0}

    match = _COUNT_ONLY_INDICATOR_RE.search(text)
    if not match:
        already_proportional = bool(_ALREADY_PROPORTIONAL_RE.search(text))
        return {"flagged": False, "rows": [], "adjustment": 0.1 if already_proportional else 0.0}

    group = match.group("group").strip()
    verb  = match.group("verb").lower()
    behavior = _INDICATOR_VERB_BEHAVIOR.get(verb, "sustaining the benefit received")

    rows = [
        ("Common (count-only)",       match.group(0)),
        ("Strong (proportional)",     f"% of {group} {verb}"),
        ("Stronger (behavior-based)", f"% of {group} {behavior} after [timeframe]"),
        ("Stronger (verified)",       f"% of {group} with verified [records/improvement]"),
    ]

    return {"flagged": True, "group": group, "verb": verb, "rows": rows, "adjustment": -0.15}


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

# Evidence types scored on sourcing rigor, triangulation, and bias
# mitigation (Qualitative Evidence Track) instead of measurement precision.
_QUALITATIVE_EV_TYPES = {
    "Case study",
    "Outcome harvesting",
    "Beneficiary narrative or testimony",
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
    is_qualitative = ev_type in _QUALITATIVE_EV_TYPES
    if is_qualitative:
        qual_checklist = submission.get("qualitative_rigor_checklist", {}) or {}
        measurement_yes = sum([
            bool(qual_checklist.get("sourcing_documented")),
            bool(qual_checklist.get("triangulated")),
            bool(qual_checklist.get("bias_considered")),
        ])
    else:
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
        "is_qualitative":        is_qualitative,
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
        _gain = round(2.0 - direct_score, 2)
        fixes.append({
            "dimension": "confidence",
            "message": (
                "Add a primary record — signed attendance sheets, payroll records, or a "
                "KoboToolbox export — so your evidence directly ties to the claim."
            ),
            "score_impact": f"+up to {_gain} on Confidence",
            "score_impact_value": _gain,
        })
    elif direct_score < 2.0:
        _gain = round(2.0 - direct_score, 2)
        fixes.append({
            "dimension": "confidence",
            "message": (
                "Strengthen your contribution case — note what else could explain "
                "this result and how you ruled it out, or triangulate with a "
                "second independent data source."
            ),
            "score_impact": f"+up to {_gain} on Confidence",
            "score_impact_value": _gain,
        })

    if verify_score < (3 / 5) * 2.0:
        current   = round(verify_score, 1)
        potential = round((4 / 5) * 2.0, 1)
        gain      = round(potential - current, 1)
        fixes.append({
            "dimension": "confidence",
            "message": (
                f"Name an internal reviewer or an external partner. "
                f"Doing so moves your verification score from {current} to {potential}."
            ),
            "score_impact": f"+{gain} on Confidence",
            "score_impact_value": gain,
        })

    provenance_bonus = confidence_components.get("provenance_bonus", 0.0)
    if provenance_bonus < 0.6 and verify_score < 2.0:
        _gain = round(min(0.6 - provenance_bonus, 2.0 - verify_score), 2)
        if _gain > 0:
            fixes.append({
                "dimension": "confidence",
                "message": (
                    "Strengthen your data chain — document your sampling method, "
                    "confirm there's no double-counting across activities, note how "
                    "recall or enumerator bias was addressed, and confirm an auditor "
                    "could retrieve the original records."
                ),
                "score_impact": f"+up to {_gain} on Confidence",
                "score_impact_value": _gain,
            })

    if recency_score < (3 / 5) * 1.0:
        _gain = round(1.0 - recency_score, 2)
        fixes.append({
            "dimension": "confidence",
            "message": (
                "Confirm your evidence date is within 6 months of the reporting period end, "
                "or attach more recent confirmatory evidence."
            ),
            "score_impact": f"+up to {_gain} on Confidence",
            "score_impact_value": _gain,
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
            "score_impact_value": impact,
        })

    if meas_score < 1.0:
        _gain = round(1.25 - meas_score, 2)
        if clarity_components.get("is_qualitative"):
            _meas_message = (
                "Document how cases or respondents were selected (not just convenience), "
                "note what this evidence was cross-checked against, and describe how "
                "recall, social-desirability, or selection bias was addressed."
            )
        else:
            _meas_message = (
                "Describe your collection method and sampling approach in the evidence description "
                "— specify the instrument used and how participants were selected."
            )
        fixes.append({
            "dimension": "clarity",
            "message": _meas_message,
            "score_impact": f"+up to {_gain} on Clarity",
            "score_impact_value": _gain,
        })

    if integrity < 0.75:
        _gain = round(1.0 - integrity, 2)
        fixes.append({
            "dimension": "clarity",
            "message": (
                "Close data gaps with original source records, "
                "or disclose the limitation transparently in the evidence description."
            ),
            "score_impact": f"+up to {_gain} on Clarity",
            "score_impact_value": _gain,
        })

    if scope < 0.5:
        _gain = round(0.75 - scope, 2)
        fixes.append({
            "dimension": "clarity",
            "message": (
                "State the sites and groups included and excluded "
                "so the reader can correctly interpret the coverage."
            ),
            "score_impact": f"+up to {_gain} on Clarity",
            "score_impact_value": _gain,
        })

    if gov_score < 0.5:
        _gain = round(0.75 - gov_score, 2)
        fixes.append({
            "dimension": "clarity",
            "message": (
                "Name an owner for this result and describe the decision it will inform — "
                "without ownership the result is not actionable."
            ),
            "score_impact": f"+up to {_gain} on Clarity",
            "score_impact_value": _gain,
        })

    fixes.sort(key=lambda x: x.get("score_impact_value", 0), reverse=True)
    return fixes


def get_score_rationale(dimension: str, level: int, current_score: float, max_score: float) -> str:
    """
    Returns a one-line rationale for a sub-score, anchored to a named standard.
    Used in Screen 2 st.metric help= parameters.
    """
    _rationales = {
        "directness": {
            "standard": "USAID ADS 201.3.5.7 — Validity; Bond Evidence Principles — Triangulation",
            "interpretations": {
                5: "Contribution rigorously established — alternative explanations considered and ruled out, or evidence triangulated across independent sources.",
                4: "Strong contribution signal — baseline/endline, comparison group, theory of change, or an independent evaluation.",
                3: "Programme records (attendance, logs, outputs) show the activity occurred, but not yet the contribution story.",
                2: "Perception-based evidence (surveys, interviews, self-report) — useful for triangulation, not standalone proof.",
                1: "Very weak proxy — estimates or back-calculated figures.",
                0: "No supporting evidence provided.",
            },
        },
        "verification": {
            "standard": "USAID ADS 201.3.5.7 — Integrity + Audit Independence Principle; Reliability + Precision (data provenance)",
            "interpretations": {
                5: "Independent third-party verification documented (gold standard).",
                4: "External partner review with limited audit depth.",
                3: "Internal cross-check by reviewer other than data collector.",
                2: "Data collected but not formally reviewed.",
                1: "Self-reported by the same person who claims it.",
                0: "No review of any kind detected.",
            },
        },
        "recency": {
            "standard": "USAID ADS 201.3.5.7 — Timeliness",
            "interpretations": {
                5: "Evidence dated within 1 month of reporting period — fully current.",
                4: "Evidence dated within 3 months — slight lag, still highly relevant.",
                3: "Evidence dated within 6 months — moderate lag noted.",
                2: "Evidence dated within 12 months — outdated, from previous cycle.",
                1: "Evidence over 12 months old — very weak relevance to current period.",
                0: "Evidence date unknown — cannot assess timeliness.",
            },
        },
    }
    _clarity_rationales = {
        "definition":        ("OECD-DAC 2019 — Relevance + USAID Validity",
                              "Checks whether the unit, timeframe, target group, and inclusion criteria are explicit enough that any reader interprets the result the same way."),
        "measurement":       ("USAID ADS 201.3.5.7 — Reliability + Bond Appropriateness 2024",
                              "Checks whether the collection method is structured, sampling approach disclosed, and bias controls stated."),
        "integrity":         ("USAID ADS 201.3.5.7 — Integrity",
                              "Checks for completeness of data, audit trail existence, and disclosure of any missing data."),
        "scope":             ("USAID ADS 201.3.5.7 — Precision + Bond Voice & Inclusion 2024",
                              "Checks coverage adequacy across sites and defensibility of the sample."),
        "governance":        ("OECD-DAC 2019 — Usefulness Principle",
                              "Checks whether there's a clear owner and decision the result will inform."),
        "beneficiary_voice": ("Bond Evidence Principles 2024 + 60 Decibels Lean Data",
                              "Checks whether beneficiaries themselves contributed to or validated the evidence."),
    }

    if dimension in _rationales:
        r = _rationales[dimension]
        interp = r["interpretations"].get(level, "")
        return f"{r['standard']}: {interp} Score: {current_score:.1f}/{max_score}"
    if dimension in _clarity_rationales:
        std, interp = _clarity_rationales[dimension]
        return f"{std}: {interp} Score: {current_score:.2f}/{max_score}"
    return f"Score: {current_score}/{max_score}"


def get_recency_diagnostic(evidence_date, report_end_date=None) -> str:
    """
    Returns a plain-English string explaining the recency calculation.
    Displayed below the Evidence Date field on Screen 1.
    """
    from datetime import date as _date
    if not evidence_date:
        return "Evidence date not provided — cannot assess timeliness. Recency: 0.0/1.0"
    if not report_end_date:
        report_end_date = _date.today()
    try:
        months_gap = (
            (report_end_date.year - evidence_date.year) * 12
            + (report_end_date.month - evidence_date.month)
        )
    except AttributeError:
        return "Evidence date format unrecognised — cannot assess timeliness."
    if months_gap <= 1:
        return (f"Evidence age: {months_gap} month(s) — fully current. Scores 1.0/1.0 on Recency. "
                "(USAID DQA: data within 1 month is gold standard.)")
    if months_gap <= 3:
        return (f"Evidence age: {months_gap} months — slight lag, highly relevant. Scores 0.8/1.0 on Recency. "
                "(USAID DQA: 1–3 month lag acceptable for full reporting.)")
    if months_gap <= 6:
        return f"Evidence age: {months_gap} months — moderate lag noted. Scores 0.6/1.0 on Recency."
    if months_gap <= 12:
        return (f"Evidence age: {months_gap} months — outdated, previous cycle. Scores 0.4/1.0 on Recency. "
                "(USAID DQA: data over 12 months loses currency.)")
    return (f"Evidence age: {months_gap} months — very weak relevance. Scores 0.2/1.0 on Recency. "
            "Confirm this still reflects current state.")


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
    evidence_ladder = get_evidence_ladder(ev_type, ev_desc, verified_by)
    funder_readiness = get_funder_readiness_flags(
        " ".join([
            submission.get("result_statement", "") or "",
            submission.get("learning_notes", "") or "",
            submission.get("limitations_notes", "") or "",
        ]),
        ev_desc,
    )

    direct_score  = round((direct_level  / 5) * 2.0, 2)
    recency_score = round((recency_level / 5) * 1.0, 2)

    provenance_bonus = get_provenance_bonus(submission.get("provenance_checklist", {}))
    verify_score = round(min(2.0, (verify_level / 5) * 2.0 + provenance_bonus), 2)

    confidence_score = round(direct_score + verify_score + recency_score, 1)

    result_stmt = submission.get("result_statement", "") or ""
    quality_multiplier, content_issues = validate_content_quality(result_stmt, ev_desc, verified_by)

    linkage_result = evaluate_logframe_linkage(
        submission.get("logframe_indicator", "") or "",
        submission.get("logframe_target", "") or "",
        submission.get("logframe_achievement", "") or "",
        result_stmt,
    )
    raw_confidence_score = confidence_score
    confidence_score = round(confidence_score * quality_multiplier, 1)
    confidence_label, confidence_meaning = interpret_score(confidence_score)

    bv_field = submission.get("beneficiary_voice", "")
    bv_bonus = (compute_beneficiary_voice_bonus(bv_field) if bv_field
                else score_beneficiary_voice(ev_desc, ev_type))

    confidence_components = {
        "direct_level":  direct_level,
        "direct_score":  direct_score,
        "verify_level":  verify_level,
        "verify_score":  verify_score,
        "recency_level": recency_level,
        "recency_score": recency_score,
        "bv_bonus":      bv_bonus,
        "provenance_bonus": provenance_bonus,
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

    clarity_score = compute_clarity(**{k: v for k, v in clarity_params.items() if k != "is_qualitative"})

    # Indicator Maturity: small clamped bonus/penalty on Measurement + Clarity
    indicator_maturity = get_indicator_maturity(submission.get("logframe_indicator", "") or "")
    meas_adj = indicator_maturity["adjustment"]
    if meas_adj:
        meas_score_c  = round(min(1.25, max(0.0, meas_score_c  + meas_adj)), 2)
        clarity_score = round(min(5.0,  max(0.0, clarity_score + meas_adj)), 2)

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
        (True,  True):  "Strong KPI — well-positioned for submission",
        (True,  False): "Misleading KPI — sharpen the definition before submission",
        (False, True):  "Well-defined but weak evidence — strengthen the verification chain",
        (False, False): "High risk — strengthen both axes before relying on this result",
    }
    verdict = _verdicts[(conf_high, clar_high)]

    fixes = get_what_to_fix(confidence_components, clarity_components)

    label_rationale = (
        f"Confidence: {confidence_score}/5.0 ({confidence_label}) — {confidence_meaning} "
        f"Clarity: {clarity_score}/5.0 ({clarity_label}) — {clarity_meaning} "
        f"Combined: {verdict}."
    )

    return {
        # v3.0 primary keys
        "confidence_score":         confidence_score,
        "raw_confidence_score":     raw_confidence_score,
        "content_quality_multiplier": quality_multiplier,
        "content_issues":           content_issues,
        "logframe_linkage":         linkage_result,
        "clarity_score":            clarity_score,
        "confidence_label":      confidence_label,
        "clarity_label":         clarity_label,
        "confidence_meaning":    confidence_meaning,
        "clarity_meaning":       clarity_meaning,
        "confidence_components": confidence_components,
        "clarity_components":    clarity_components,
        "evidence_ladder":       evidence_ladder,
        "indicator_maturity":    indicator_maturity,
        "funder_readiness":      funder_readiness,
        "beneficiary_voice_bonus": bv_bonus,
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
