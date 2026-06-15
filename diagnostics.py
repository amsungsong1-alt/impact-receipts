"""
diagnostics.py — readiness bands, diagnostic-state classification, and
overview/score-explainer helpers for Impact-Receipts.

Pure, deterministic, no Streamlit dependency — moved out of app.py as part
of the modular refactor so it can be imported and tested headlessly.
"""

# ---------------------------------------------------------------------------
# 7-state diagnostic badge + 3-state readiness band
# ---------------------------------------------------------------------------

_DIAGNOSTIC_BADGE = {
    "STRONG":             {"bg": "#1B5E20", "text": "#FFFFFF", "subtitle": "Strong on both axes"},
    "MISLEADING":         {"bg": "#8A6500", "text": "#FFFFFF", "subtitle": "Sharpen the definition"},
    "UNDEREVIDENCED":     {"bg": "#8A6500", "text": "#FFFFFF", "subtitle": "Strengthen the evidence"},
    "NEEDS REFINEMENT":   {"bg": "#FFF9C4", "text": "#F57F17", "subtitle": "Specific gaps to address"},
    "FUNDAMENTALLY WEAK": {"bg": "#B71C1C", "text": "#FFFFFF", "subtitle": "Redefine the claim AND gather new evidence"},
    "INVALID INPUT":      {"bg": "#B71C1C", "text": "#FFFFFF", "subtitle": "Placeholder text detected — please provide real content"},
    "INCOMPLETE":         {"bg": "#9E9E9E", "text": "#FFFFFF", "subtitle": "Fill remaining fields"},
}

# Three-state "is this good enough to submit?" headline, collapsed from the
# 7-state diagnostic classification above.
_READINESS_BAND = {
    "STRONG":             "Submission-Ready",
    "NEEDS REFINEMENT":   "Needs Work",
    "MISLEADING":         "Needs Work",
    "UNDEREVIDENCED":     "Needs Work",
    "INCOMPLETE":         "Needs Work",
    "FUNDAMENTALLY WEAK": "Not Defensible",
    "INVALID INPUT":      "Not Defensible",
}

_READINESS_STYLE = {
    "Submission-Ready": {
        "bg": "#1B5E20", "icon": "✅",
        "caption": "Both evidence confidence and claim clarity clear the bar a donor "
                   "reviewer would apply. Read the gaps below, then submit.",
    },
    "Needs Work": {
        "bg": "#8A6500", "icon": "⚠️",
        "caption": "Defensible in places, but at least one dimension would draw a "
                   "reviewer's question. Close the flagged gaps first.",
    },
    "Not Defensible": {
        "bg": "#B71C1C", "icon": "⛔",
        "caption": "As written, this result would not survive a data quality "
                   "assessment. The gaps below are why — fix them before it goes "
                   "near a donor report.",
    },
}

# Shown under every readiness banner — keeps the headline from reading as a
# guarantee of donor approval.
_LIMITS_DISCLAIMER = (
    "This is improvement guidance, not a guarantee of approval. Impact-Receipts "
    "checks the evidence you entered against what donor reviewers typically look "
    "for — completeness, verifiability, clarity, and data-protection flags. It "
    "does not see your underlying data collection, judge your programme, or "
    "replace your donor's own assessment. A \"Submission-Ready\" result means the "
    "gaps it can detect are closed — not that approval is assured."
)


def _readiness_banner_html(diag_state: str) -> str:
    band = _READINESS_BAND.get(diag_state, "Needs Work")
    style = _READINESS_STYLE[band]
    return (
        f"<div style='background:{style['bg']};color:#FFFFFF;border-radius:10px;"
        f"padding:14px 20px;font-weight:700;text-align:center;margin:16px 0;font-size:1.1rem;"
        f"-webkit-print-color-adjust:exact;print-color-adjust:exact;'>"
        f"{style['icon']} {band} &mdash; {style['caption']}"
        f"</div>"
        f"<p style='color:#9E9E9E;font-size:0.75rem;text-align:center;margin:-8px 0 16px;'>"
        f"{_LIMITS_DISCLAIMER}</p>"
    )


# ---------------------------------------------------------------------------
# Diagnostic state classifier
# ---------------------------------------------------------------------------

def get_diagnostic_state(
    confidence: float,
    clarity: float,
    content_issues: list | None = None,
    beneficiary_voice: str = "",
) -> tuple:
    if content_issues and len(content_issues) >= 2:
        return (
            "INVALID INPUT",
            "Inputs look like placeholder text — please provide real result and evidence details",
        )
    if confidence >= 4.0 and clarity >= 4.0:
        if beneficiary_voice == "No beneficiary voice captured":
            return (
                "NEEDS REFINEMENT",
                "Strong on both axes, but missing beneficiary voice — Bond Evidence Principles 2024 "
                "require voice & inclusion. Consider adding beneficiary feedback.",
            )
        return "STRONG", "Ready for submission"
    if confidence >= 3.5 and clarity < 3.0:
        return "MISLEADING", "Strong evidence but unclear claim — sharpen the definition"
    if confidence < 3.0 and clarity >= 3.5:
        return "UNDEREVIDENCED", "Clear claim but weak evidence — strengthen the verification chain"
    if confidence < 2.5 and clarity < 2.5:
        return "FUNDAMENTALLY WEAK", "Both axes show major gaps — redefine AND gather new evidence before submission"
    if confidence >= 3.0 and clarity >= 3.0:
        return "NEEDS REFINEMENT", "Acceptable on both axes — specific gaps to address before submission"
    return "INCOMPLETE", "Some inputs missing — fill in remaining fields for a full assessment"


# ---------------------------------------------------------------------------
# Score-band badges, verdict CSS, and per-criterion tip copy
# ---------------------------------------------------------------------------

_BRAND_BADGE = {
    "Strong":     {"bg": "#C8E6C9", "text": "#1B5E20"},
    "Acceptable": {"bg": "#FFF9C4", "text": "#F57F17"},
    "Weak":       {"bg": "#FFE0B2", "text": "#E65100"},
    "High Risk":  {"bg": "#FFCDD2", "text": "#B71C1C"},
}

_VERDICT_CSS = {
    "Strong KPI — well-positioned for submission":                         "",
    "Misleading KPI — sharpen the definition before submission":           "misleading",
    "Well-defined but weak evidence — strengthen the verification chain":  "weak-conf",
    "High risk — strengthen both axes before relying on this result":      "high-risk",
}


_DIRECTNESS_TIPS = {
    5: "Level 5 — Contribution rigorously established: alternative explanations considered and ruled out, or evidence triangulated across independent sources.",
    4: "Level 4 — Strong contribution signal: baseline/endline, comparison group, theory of change, or an independent evaluation.",
    3: "Level 3 — Programme records (attendance, logs, outputs) show the activity occurred, but not yet the contribution story.",
    2: "Level 2 — Perception-based evidence (surveys, interviews, self-report) — useful for triangulation, not standalone proof.",
    1: "Level 1 — No evidence yet linking activities to this result.",
}

_VERIFICATION_TIPS = {
    5: "Level 5 — Verified by an independent third party: highest possible assurance.",
    4: "Level 4 — External partner review conducted: strong external assurance.",
    3: "Level 3 — Reviewed internally by a MEL Officer: adequate internal review.",
    2: "Level 2 — Collected only, no formal review: evidence is unreviewed.",
    1: "Level 1 — No review conducted: evidence is unverified.",
    0: "Level 0 — No review conducted: evidence is unverified.",
}

_RECENCY_TIPS = {
    5: "Level 5 — Evidence collected within the same reporting month: highly current.",
    4: "Level 4 — Evidence collected within 3 months: acceptably recent.",
    3: "Level 3 — Evidence collected within 6 months: moderately recent.",
    2: "Level 2 — Evidence collected within 12 months: aging — consider refreshing.",
    1: "Level 1 — Evidence older than 12 months: recency is a significant concern.",
}

_CLARITY_TIPS = {
    "definition":  "Definition (max 1.25) — how precisely the result states who, what, where, and by when.",
    "definition_qualitative": "Narrative Definition (max 1.25) — whether a timeframe is stated, "
        "whose voice/representation is reflected, and consent/ethics are addressed.",
    "measurement": "Measurement (max 1.25) — whether a clear indicator, baseline, and target are stated.",
    "measurement_qualitative": "Sourcing & Triangulation (max 1.25) — whether case/respondent "
        "selection, triangulation, and bias mitigation are documented.",
    "integrity":   "Integrity (max 1.0) — data completeness, audit trail, and absence of unexplained gaps.",
    "scope":       "Scope (max 0.75) — whether geographic and demographic coverage matches the claim.",
    "governance":  "Governance (max 0.75) — whether a named owner and a decision use for the result are stated.",
}

# ---------------------------------------------------------------------------
# Scoring Transparency Layer
#
# One constant holding plain-language copy for each of the eight scoring
# criteria: what it measures, why a donor reviewer cares, what weak vs.
# strong evidence looks like, and concrete actions to improve it. Used by
# render_how_scoring_works_panel() and render_personalized_weakness_panel()
# in app.py. Editing this dict changes explanatory text only — no scoring math.
# ---------------------------------------------------------------------------
_SCORING_GUIDE = {
    "directness": {
        "label": "Directness", "axis": "confidence", "max_score": 2.0,
        "definition": "How directly the evidence shows the programme contributed to this result, "
                      "not just that an activity took place.",
        "why_it_matters": "Donor reviewers ask 'how do you know this happened because of you?' — "
                          "weak directness is one of the most common reasons results get challenged "
                          "in a data quality assessment.",
        "weak_example": "\"We trained 200 farmers\" — describes an activity, with no link to any "
                        "change in their practices or outcomes.",
        "strong_example": "A before/after comparison (and, where possible, a comparison group) "
                          "showing the change occurred specifically among those reached by the programme.",
        "improve_actions": [
            "Add a baseline and endline measurement for the same group.",
            "Where possible, compare against a group that did not receive the intervention.",
            "Name plausible alternative explanations for the change and explain why they don't account for it.",
        ],
    },
    "verification": {
        "label": "Verification", "axis": "confidence", "max_score": 2.0,
        "definition": "Whether the evidence has been reviewed or checked by someone other than "
                      "the person who collected it.",
        "why_it_matters": "Unreviewed self-reported data is the easiest thing for a donor or "
                          "auditor to flag — independent review is the cheapest credibility boost available.",
        "weak_example": "Data collected by the field officer and reported as-is, with no review step.",
        "strong_example": "Data reviewed internally by a MEL Officer, and spot-checked or "
                          "validated by an external partner or evaluator.",
        "improve_actions": [
            "Have a MEL Officer or supervisor review the evidence before it's reported (internal review).",
            "Ask a partner organisation, government counterpart, or evaluator to validate a sample (external review).",
            "Record who reviewed it and when, so the review is itself documented.",
        ],
    },
    "recency": {
        "label": "Recency", "axis": "confidence", "max_score": 1.0,
        "definition": "How recently the evidence was collected relative to the reporting period.",
        "why_it_matters": "Stale evidence reads as 'this might no longer be true' — donors expect "
                          "results to reflect the current reporting period, not last year's data.",
        "weak_example": "The evidence cited is more than 12 months old relative to this report.",
        "strong_example": "The evidence was collected within the same reporting month, or at "
                          "most within the last 3 months.",
        "improve_actions": [
            "Refresh data collection so the cited evidence falls within the current reporting period.",
            "If older evidence is the best available, say so explicitly and explain why.",
            "Build recurring (e.g. quarterly) data collection into the workplan so evidence doesn't age out.",
        ],
    },
    "definition": {
        "label": "Definition", "axis": "clarity", "max_score": 1.25,
        "definition": "How precisely the result states who changed, what changed, where, and by when.",
        "why_it_matters": "OECD-DAC Relevance (2019) asks whether what was measured is what was "
                          "intended — a vague claim can't be checked against an indicator at all.",
        "weak_example": "\"Farmers' livelihoods improved\" — no who, no measurable what, no timeframe.",
        "strong_example": "\"650 smallholder farmers in the Upper East Region increased maize "
                          "yields by 30% between the 2025 and 2026 harvests.\"",
        "improve_actions": [
            "State who was affected (group, number, location).",
            "State what specifically changed, in measurable terms.",
            "State the timeframe the claim covers.",
        ],
        # --- Qualitative evidence variant (Case study / Outcome harvesting / Beneficiary narrative) ---
        "qualitative_label": "Narrative Definition",
        "qualitative_definition": "Whether a timeframe is stated, whose voice/representation is "
                                  "reflected in the narrative, and consent/ethics are addressed.",
        "qualitative_weak_example": "A beneficiary story is reported with no date, no indication "
                                    "of who is represented, and no mention of consent.",
        "qualitative_strong_example": "The narrative states when the change happened, makes clear "
                                      "whose experience it represents (and how representative that "
                                      "is), and confirms consent/ethics were addressed.",
        "qualitative_improve_actions": [
            "State the timeframe the narrative or case relates to.",
            "Make clear whose voice is represented, and how that relates to the wider beneficiary group.",
            "Confirm consent was obtained and any identifying details were handled appropriately.",
        ],
    },
    "measurement": {
        "label": "Measurement", "axis": "clarity", "max_score": 1.25,
        "definition": "Whether the result is tied to a clear indicator with a stated baseline and target.",
        "why_it_matters": "USAID ADS 201.3.5.7 (Precision) — without a baseline and target, a "
                          "reviewer has no way to judge whether the reported change is meaningful.",
        "weak_example": "A percentage or count is reported with no baseline to compare it against.",
        "strong_example": "\"Baseline: 40% adoption (2024). Target: 65% by 2026. Achieved: 62% (2026).\"",
        "improve_actions": [
            "State the indicator being used and link it to the logframe.",
            "Record the baseline value and the target value alongside the achieved value.",
            "Use the same definition and unit of measure as the baseline, so the comparison is valid.",
        ],
        # --- Qualitative evidence variant (Case study / Outcome harvesting / Beneficiary narrative) ---
        "qualitative_label": "Sourcing & Triangulation",
        "qualitative_definition": "Whether case/respondent selection, triangulation, and bias "
                                  "mitigation are documented for qualitative evidence.",
        "qualitative_weak_example": "A single success story is reported with no explanation of "
                                    "how that case was chosen or whether it's representative.",
        "qualitative_strong_example": "The case/respondent selection method is documented, the "
                                      "account is corroborated by another source, and "
                                      "selection or social-desirability bias is explicitly addressed.",
        "qualitative_improve_actions": [
            "Document how cases or respondents were selected — not just convenience or 'the most positive story'.",
            "Cross-check the account against another source or method (triangulation/substantiation).",
            "Note and address possible recall, social-desirability, or success-story bias.",
        ],
    },
    "integrity": {
        "label": "Integrity", "axis": "clarity", "max_score": 1.0,
        "definition": "Whether the underlying data is complete, has an audit trail, and is free "
                      "from unexplained gaps.",
        "why_it_matters": "USAID ADS 201.3.5.7 (Integrity) and Bond Evidence Principles 2024 "
                          "(Transparency) — gaps or unexplained data quality issues are a common "
                          "trigger for a deeper donor audit.",
        "weak_example": "Significant missing data with no audit trail showing how figures were derived.",
        "strong_example": "Minimal-to-no missing data, with a clear audit trail from raw records "
                          "to the reported figure, and an adequate sample.",
        "improve_actions": [
            "Document and explain any missing or excluded data points.",
            "Keep a record of how raw data became the reported figure (audit trail).",
            "Check that the sample size is adequate for the claim being made.",
        ],
    },
    "scope": {
        "label": "Scope", "axis": "clarity", "max_score": 0.75,
        "definition": "Whether the geographic and demographic coverage described matches the claim.",
        "why_it_matters": "OECD-DAC Coherence (2019) — a claim that overstates its coverage "
                          "(e.g. implying national reach from a pilot district) is a classic "
                          "'misleading KPI' flag.",
        "weak_example": "A result from one pilot district is reported without naming that limited scope.",
        "strong_example": "The result explicitly states the geographic area and population group "
                          "it applies to, matching what the evidence actually covers.",
        "improve_actions": [
            "Name the specific geographic area(s) the result covers.",
            "Name the specific population/demographic group covered.",
            "Make sure the claim's wording doesn't imply broader coverage than the evidence supports.",
        ],
    },
    "governance": {
        "label": "Governance", "axis": "clarity", "max_score": 0.75,
        "definition": "Whether there is a named, accountable owner for this result and its evidence.",
        "why_it_matters": "Classical audit Traceability and FCDO Evaluation Policy (Jan 2025) — "
                          "reviewers want to know who to ask if they have questions about this result.",
        "weak_example": "No named owner for the result or its supporting evidence.",
        "strong_example": "A named role/person owns the result, and a stated decision "
                          "(e.g. report to donor, inform programme adjustment) depends on it.",
        "improve_actions": [
            "Name the role or person accountable for this result and its evidence.",
            "State what decision this result feeds into (e.g. donor report, programme adjustment).",
            "Make sure that owner is the one who reviewed/signs off on the evidence (links to Verification).",
        ],
    },
}


# ---------------------------------------------------------------------------
# Donor framework crosswalk
#
# One row per scoring criterion (keys match _SCORING_GUIDE), mapping each to
# the USAID Data Quality Assessment (DQA) standard(s) and Bond Evidence
# Principle(s) it satisfies, with a one-line rationale. "eu" is a placeholder
# (OECD-DAC criteria) pending a reviewed mapping — see DONOR_PROFILES.
# Display only: adding/editing a donor framework here does not change any
# sub-score.
# ---------------------------------------------------------------------------
DONOR_CROSSWALK = {
    "directness": {
        "dqa": ["Validity"],
        "bond": ["Appropriateness"],
        "eu": [],
        "rationale": "Directness checks whether the evidence measures the programme's "
                      "contribution to the result — DQA Validity asks whether data "
                      "measures what it claims to measure.",
    },
    "verification": {
        "dqa": ["Reliability", "Integrity"],
        "bond": ["Triangulation"],
        "eu": [],
        "rationale": "Independent review reduces measurement error (Reliability) and "
                      "guards against misreporting (Integrity); Bond calls this "
                      "Triangulation.",
    },
    "recency": {
        "dqa": ["Timeliness"],
        "bond": [],
        "eu": [],
        "rationale": "DQA Timeliness requires data current enough to inform decisions; "
                      "Bond has no dedicated recency principle.",
    },
    "definition": {
        "dqa": ["Validity", "Precision"],
        "bond": [],
        "eu": [],
        "rationale": "A precisely scoped result (who/what/where/when) is both valid "
                      "and precise under DQA; Bond does not separately assess wording.",
    },
    "measurement": {
        "dqa": ["Precision"],
        "bond": [],
        "eu": [],
        "rationale": "A stated indicator, baseline, and target is exactly what DQA "
                      "Precision evaluates.",
    },
    "integrity": {
        "dqa": ["Integrity"],
        "bond": ["Transparency"],
        "eu": [],
        "rationale": "Complete data with an audit trail satisfies DQA Integrity and "
                      "Bond's Transparency principle.",
    },
    "scope": {
        "dqa": ["Validity"],
        "bond": [],
        "eu": [],
        "rationale": "Coverage matching the claim (right population/area) is part of "
                      "DQA Validity; Bond has no separate scope principle.",
    },
    "governance": {
        "dqa": ["Integrity"],
        "bond": ["Transparency", "Accountability"],
        "eu": [],
        "rationale": "A named, accountable owner supports DQA Integrity and Bond's "
                      "Transparency/Accountability principle.",
    },
}

# Display order + labels for the crosswalk table, matching the original
# static table's rows.
_CROSSWALK_ROW_ORDER = [
    ("directness",  "Confidence &rarr; Directness"),
    ("verification", "Confidence &rarr; Verification"),
    ("recency",      "Confidence &rarr; Recency"),
    ("definition",   "Clarity &rarr; Definition"),
    ("measurement",  "Clarity &rarr; Measurement"),
    ("integrity",    "Clarity &rarr; Integrity (\"Ethics\")"),
    ("governance",   "Clarity &rarr; Governance (\"Compliance\")"),
]

# Beneficiary Voice is a Confidence bonus, not one of the eight scoring
# criteria, so it isn't in DONOR_CROSSWALK — its mapping (Validity / Voice &
# Inclusion) is handled directly in build_donor_crosswalk_html() below.

# Donor-profile selector options, in display order. Each profile selects
# which framework column(s) from DONOR_CROSSWALK to show, with a column
# header label. Adding a donor profile = adding one entry here (and, if it
# needs a new framework key, filling that key in for each criterion above).
DONOR_PROFILES = {
    "Generic": {
        "label": "Generic (USAID DQA + Bond)",
        "frameworks": [("dqa", "USAID DQA standard(s)"), ("bond", "Bond Evidence Principle")],
    },
    "USAID": {
        "label": "USAID DQA",
        "frameworks": [("dqa", "USAID DQA standard(s)")],
    },
    "FCDO-Bond": {
        "label": "FCDO / Bond Evidence Principles",
        "frameworks": [("bond", "Bond Evidence Principle")],
    },
    "EU": {
        "label": "EU / OECD-DAC",
        "frameworks": [("eu", "OECD-DAC criterion")],
    },
}


def build_donor_crosswalk_html(profile_key: str) -> str:
    """Build the donor framework crosswalk table for the selected profile.

    Display only — annotates existing sub-scores with the donor-standard(s)
    they satisfy; does not compute or alter any score.
    """
    profile = DONOR_PROFILES.get(profile_key, DONOR_PROFILES["Generic"])
    frameworks = profile["frameworks"]

    header_cells = "".join(f"<th>{header}</th>" for _, header in frameworks)
    rows_html = []
    for key, row_label in _CROSSWALK_ROW_ORDER:
        entry = DONOR_CROSSWALK[key]
        cells = []
        for fw_key, _ in frameworks:
            values = entry.get(fw_key) or []
            cells.append(" + ".join(values) if values else "&mdash;")
        cell_html = "".join(f"<td>{c}</td>" for c in cells)
        rows_html.append(f"<tr><td>{row_label}</td>{cell_html}</tr>")

    # Beneficiary Voice row only has "dqa"/"bond" mappings (Validity / Voice &
    # Inclusion); for single-framework profiles, show whichever of those
    # matches the selected framework, else "—".
    bv_map = {"dqa": "Validity", "bond": "Voice &amp; Inclusion"}
    bv_cells = []
    for fw_key, _ in frameworks:
        bv_cells.append(bv_map.get(fw_key, "&mdash;"))
    bv_cell_html = "".join(f"<td>{c}</td>" for c in bv_cells)
    rows_html.append(f"<tr><td>Beneficiary Voice (Confidence bonus)</td>{bv_cell_html}</tr>")

    return (
        "<table style='width:100%;font-size:0.8rem;'>"
        f"<tr><th>Impact-Receipts sub-score</th>{header_cells}</tr>"
        + "".join(rows_html)
        + "</table>"
    )


def _axis_badge_html(label: str, score: float, max_score: float) -> str:
    b = _BRAND_BADGE.get(label, {"bg": "#F5F5F5", "text": "#212121"})
    return (
        f"<div class='axis-badge' style='background:{b['bg']};color:{b['text']};'>"
        f"{score}/{max_score} &nbsp; <strong>{label.upper()}</strong>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Overview score values + chart
# ---------------------------------------------------------------------------

def _overview_score_values(ev):
    """Return (confidence, clarity, ethics_pct, compliance_pct) each 0–100.

    Ethics maps to the Integrity component (max 1.0) and Compliance maps to
    the Governance component (max 0.75) of the Clarity score, so the two
    axes reflect distinct evaluator metrics rather than a single combined value.
    """
    conf = min(100.0, round(ev.get("raw_confidence_score", 0) * 20, 1))
    clar = min(100.0, round(ev.get("clarity_score", 0) * 20, 1))
    clar_comp = ev.get("clarity_components", {})
    integ = clar_comp.get("integrity_score", 0)
    gov   = clar_comp.get("governance_score", 0)
    eth   = min(100.0, round(integ / 1.0 * 100, 1))
    comp  = min(100.0, round(gov / 0.75 * 100, 1))
    return conf, clar, eth, comp


def _build_overview_chart_b64(conf, clar, eth, comp):
    """Build a simple horizontal bar chart (0-100) as base64 PNG, summarizing
    the four headline diagnostic scores.

    Replaces an earlier radar chart that overlaid Confidence/Clarity with a
    "Clarity breakdown" (Ethics/Compliance) shape sharing the Clarity vertex —
    that overlap made the chart hard to read. Four independent bars, each
    clearly labeled and color-coded by score band, communicate the same
    information without the ambiguity.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io as _io_r
        import base64 as _b64

        labels = [
            "Confidence\n(evidence quality)",
            "Clarity\n(result definition)",
            "Ethics\n(data integrity)",
            "Compliance\n(consent & data protection)",
        ]
        values = [conf, clar, eth, comp]

        def _band_color(v):
            if v >= 75:
                return "#1B5E20"
            if v >= 50:
                return "#8A6500"
            return "#C62828"

        colors = [_band_color(v) for v in values]

        fig, ax = plt.subplots(figsize=(5.2, 2.8))
        y_pos = list(range(len(labels)))
        ax.barh(y_pos, values, color=colors, height=0.55)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(0, 100)
        ax.set_xlabel("Score out of 100", fontsize=8, color="#616161")
        ax.tick_params(axis="x", labelsize=8, colors="#616161")
        ax.tick_params(axis="y", length=0)
        for spine in ["top", "right", "left"]:
            ax.spines[spine].set_visible(False)
        for i, v in enumerate(values):
            label_x = v - 4 if v >= 12 else v + 2
            ha = "right" if v >= 12 else "left"
            color = "white" if v >= 12 else "#212121"
            ax.text(label_x, i, f"{v:.0f}", va="center", ha=ha,
                    fontsize=9, fontweight="bold", color=color)
        ax.grid(axis="x", alpha=0.25)
        plt.tight_layout()
        buf = _io_r.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return _b64.b64encode(buf.read()).decode()
    except Exception:
        return ""
