"""
framework_crosswalk.py — Framework Crosswalk Engine.

Given an already-scored result (an evaluate_submission() output), determines pass/fail per
criterion under 5 named external standards (USAID ADS 201/DQA, FCDO Evaluation Policy 2025,
Bond Evidence Principles 2024, OECD-DAC 2019, World Bank Results Framework), citing the
specific standard for each requirement and exact remediation for anything failing.

No Streamlit import, no API calls -- same UI-free discipline as evaluator.py/diagnostics.py.
Deterministic: the same evaluation dict always produces the same crosswalk result.

Distinct from diagnostics.py's DONOR_CROSSWALK/build_donor_crosswalk_html(), which is a
purely descriptive "which standard names relate to which criterion" reference table with no
pass/fail and no thresholds (that module's own docstring: "Display only... does not compute
or alter any score"). This module is the actionable counterpart -- it actually determines
whether a scored result passes each framework's cited criteria. The two coexist: the
descriptive table stays as a quick reference, this is the pass/fail report.

Threshold design: pass/fail reuses evaluator.get_what_to_fix()'s existing per-criterion
trigger conditions (the same logic already used app-wide for "what to fix" guidance) rather
than inventing framework-specific numeric bars not grounded in any real published document.
Frameworks differ in WHICH criteria they cite as requirements and HOW the remediation is
phrased/cited -- not in secretly different pass marks. A criterion a framework doesn't cite
in FRAMEWORKS below is absent from that framework's "criteria" dict entirely -- callers
(the UI layer) render that as "not directly assessed by this framework," never force-mapped
or silently treated as a pass.

Every citation below traces to a string already used elsewhere in this codebase
(evaluator.py, diagnostics.py, donor_templates.py, prompts.py, app.py's DONOR_GUIDANCE) or to
the named standard's own genuinely public criteria (OECD-DAC's 2019 Evaluation Criteria) --
nothing invented from nothing. Remediation text is adapted from evaluator.get_what_to_fix()'s
existing guidance for the same dimension, phrased with each framework's own vocabulary --
the underlying advice is not new, only the framing.
"""
from __future__ import annotations

from evaluator import DIMENSION_MAP

# Absolute pass/fail thresholds per dimension -- copied from the exact trigger conditions in
# evaluator.get_what_to_fix() (NOT a uniform 60%-of-max the way compute_systemic_gaps() is;
# these vary 60-80% of each dimension's max, matching what the app already tells users needs
# fixing today). Directness uses get_what_to_fix()'s harder/primary cutoff only (1.2), not
# its softer secondary one (2.0), for consistency with every other dimension having exactly
# one threshold.
_UNIVERSAL_THRESHOLDS: dict = {
    "Directness":   1.2,
    "Verification": 1.2,
    "Recency":      0.6,
    "Definition":   1.0,
    "Measurement":  1.0,
    "Integrity":    0.75,
    "Scope":        0.5,
    "Governance":   0.5,
}

# NESTA Level 3 ("evidence of causality... through use of a randomised
# controlled trial or comprehensive qualitative evaluation") is a
# meaningfully higher bar than the universal Directness threshold, which
# only requires evaluator.score_directness()'s level 2 (perception evidence)
# to pass. Framework-specific, not a generic per-framework override
# mechanism -- only NESTA's published standard is this much stricter than
# every other framework already in FRAMEWORKS on this one dimension.
_NESTA_THRESHOLD_OVERRIDES: dict = {"Directness": 2.0}

# evaluator.py's 5-level Directness ladder and NESTA's 5 published levels
# measure different things and are NOT numerically aligned: evaluator asks
# "how directly does this evidence tie to the claimed result," NESTA asks
# "how rigorously is causality established." A perfect evaluator score does
# not imply NESTA Level 5 -- NESTA Levels 4-5 (independent evaluation +
# cost-effectiveness; multi-site replication with documented systems) test
# things this evaluator does not assess at all, so no evaluator level maps
# to them. Level descriptions per Nesta's own published Standards of
# Evidence (nesta.org.uk/feature/innovation-methods/standards-evidence/).
NESTA_DIRECTNESS_MAPPING: dict = {
    0: {
        "nesta_level": 0, "nesta_label": "Below Level 1 — no evidence",
        "rationale": "No evidence description or evidence type was provided.",
    },
    1: {
        "nesta_level": 0, "nesta_label": "Below Level 1 — no evidence",
        "rationale": (
            "An unhedged causal claim with no triangulation, comparison basis, or "
            "causal-link statement behind it does not clear even NESTA's Level 1 bar, "
            "which requires a coherent, evidenced theory of change, not an assertion."
        ),
    },
    2: {
        "nesta_level": 1, "nesta_label": "Level 1 — Theory of change",
        "rationale": (
            "Perception-based evidence alone (survey, interview, focus group) describes "
            "beneficiary experience but does not yet show measured change, which is "
            "what separates Level 1 from Level 2."
        ),
    },
    3: {
        "nesta_level": 1, "nesta_label": "Level 1 — Theory of change",
        "rationale": (
            "Programme records (attendance sheets, activity logs) show the activity "
            "took place, not that it caused a change in outcomes -- still Level 1."
        ),
    },
    4: {
        "nesta_level": 2, "nesta_label": "Level 2 — Data showing change",
        "rationale": (
            "A comparison/baseline basis or an explicit causal-link statement shows "
            "positive change is being captured, matching Level 2 -- but without a "
            "control/comparison group ruling out other explanations, it doesn't yet "
            "demonstrate causality (Level 3)."
        ),
    },
    5: {
        "nesta_level": 3, "nesta_label": "Level 3 — Causal impact",
        "rationale": (
            "Triangulated evidence, or a comparison basis combined with a causal-link "
            "statement, is the strongest signal this evaluator can detect -- roughly "
            "comparable to Level 3's causality bar, though NESTA Level 3 specifically "
            "expects an RCT or a comprehensive qualitative evaluation, which this "
            "evaluator cannot verify from a text description alone."
        ),
    },
}


def get_nesta_directness_mapping(direct_level: int) -> dict:
    """Maps one of evaluator.get_directness_level()'s 0-5 levels to its closest
    NESTA Standards of Evidence level, for display in the NESTA framework
    crosswalk. Returns the Level-0 ("no evidence") row for any level outside
    0-5 rather than raising, matching this module's degrade-gracefully
    convention."""
    return NESTA_DIRECTNESS_MAPPING.get(direct_level, NESTA_DIRECTNESS_MAPPING[0])

FRAMEWORKS: dict = {
    "USAID": {
        "label": "USAID ADS 201 / DQA",
        "criteria": {
            "Directness": {
                "citation": "ADS 201.3.5.7 — Validity",
                "remediation": (
                    "Add a primary record — signed attendance sheets, payroll records, "
                    "or a KoboToolbox export — so your evidence directly ties to the "
                    "claim, and add a sentence linking it to your theory of change."
                ),
            },
            "Verification": {
                "citation": "ADS 201.3.5.7 — Reliability",
                "remediation": (
                    "Name an internal reviewer or an external partner who checked this data "
                    "— DQA Reliability requires a consistent, verifiable collection "
                    "process, not a self-reported figure."
                ),
            },
            "Recency": {
                "citation": "ADS 201.3.5.7 — Timeliness",
                "remediation": (
                    "Confirm your evidence date is within 6 months of the reporting period "
                    "end, or attach more recent confirmatory evidence."
                ),
            },
            "Measurement": {
                "citation": "ADS 201.3.5.7 — Precision",
                "remediation": (
                    "Describe your collection method and sampling approach in the evidence "
                    "description — DQA Precision requires enough methodological detail "
                    "to judge the margin of error."
                ),
            },
            "Integrity": {
                "citation": "ADS 201.3.5.7 — Integrity",
                "remediation": (
                    "Close data gaps with original source records, or disclose the "
                    "limitation transparently — DQA Integrity requires safeguards "
                    "against transcription error or manipulation."
                ),
            },
        },
    },
    "FCDO": {
        "label": "FCDO Evaluation Policy 2025",
        "criteria": {
            "Directness": {
                "citation": "FCDO Evaluation Policy (January 2025)",
                "remediation": (
                    "Strengthen your contribution case — note what else could explain "
                    "this result and how you ruled it out, or triangulate with a second "
                    "independent data source."
                ),
            },
            "Verification": {
                "citation": "FCDO EQuALS 2 quality standards",
                "remediation": (
                    "Name an internal reviewer or an external partner — EQuALS 2 "
                    "assesses the rigor of the evidence behind a finding, not just the "
                    "finding itself."
                ),
            },
            "Definition": {
                "citation": "FCDO EQuALS 2 quality standards",
                "remediation": (
                    "Add the missing unit, timeframe, or target group to your result "
                    "statement so the reporting is clear enough to assess under EQuALS 2."
                ),
            },
            "Measurement": {
                "citation": "FCDO EQuALS 2 quality standards",
                "remediation": (
                    "Describe your collection method and sampling approach — EQuALS 2 "
                    "requires the methodology behind a finding to be visible, not assumed."
                ),
            },
            "Governance": {
                "citation": "FCDO Evaluation Policy (January 2025)",
                "remediation": (
                    "Name an owner for this result and describe the decision it will inform "
                    "— FCDO's policy centres evaluation use for decision-making, not "
                    "reporting alone."
                ),
            },
        },
    },
    "Bond": {
        "label": "Bond Evidence Principles 2024",
        "criteria": {
            "Verification": {
                "citation": "Bond Evidence Principles 2024 — Triangulation",
                "remediation": (
                    "Name an internal reviewer or an external partner, and cross-check this "
                    "finding against a second independent source — Triangulation is one "
                    "of Bond's core evidence principles."
                ),
            },
            "Integrity": {
                "citation": "Bond Evidence Principles 2024 — Transparency",
                "remediation": (
                    "Close data gaps with original source records, or disclose the "
                    "limitation transparently — Bond's Transparency principle requires "
                    "limitations to be stated, not hidden."
                ),
            },
            "Measurement": {
                "citation": "Bond Evidence Principles 2024 — Appropriateness",
                "remediation": (
                    "Describe your collection method and sampling approach in the evidence "
                    "description — Bond's Appropriateness principle requires methods to "
                    "be fit for the context, which can't be judged without knowing them."
                ),
            },
        },
    },
    "OECD-DAC": {
        "label": "OECD-DAC 2019 Evaluation Criteria",
        "criteria": {
            "Directness": {
                "citation": "OECD-DAC 2019 — Effectiveness",
                "remediation": (
                    "Add a primary record so your evidence directly shows the result was "
                    "achieved — Effectiveness asks whether the intervention's "
                    "objectives were actually reached, not just plausible."
                ),
            },
            "Definition": {
                "citation": "OECD-DAC 2019 — Relevance",
                "remediation": (
                    "Add the missing unit, timeframe, or target group to your result "
                    "statement — Relevance asks whether what was measured is what was "
                    "intended, which requires a precise claim."
                ),
            },
            "Scope": {
                "citation": "OECD-DAC 2019 — Coherence",
                "remediation": (
                    "State the sites and groups included and excluded — an overstated "
                    "claim about coverage is inconsistent with Coherence's requirement that "
                    "findings not exceed what the evidence supports."
                ),
            },
            "Governance": {
                "citation": "OECD-DAC 2019 — Sustainability",
                "remediation": (
                    "Name an owner for this result and describe the decision it will inform "
                    "— Sustainability requires a clear line from evidence to continued "
                    "use, which needs an accountable owner."
                ),
            },
        },
    },
    "World Bank": {
        "label": "World Bank Results Framework",
        "criteria": {
            "Directness": {
                "citation": "World Bank — PDO Achievement",
                "remediation": (
                    "Add a primary record — signed attendance sheets, payroll records, "
                    "or a KoboToolbox export — so your evidence directly demonstrates "
                    "PDO (Project Development Objective) achievement, not just activity "
                    "completion."
                ),
            },
            "Verification": {
                "citation": "World Bank IEG RAP standards",
                "remediation": (
                    "Name an internal reviewer or an external partner — IEG's "
                    "independent evaluation standards require verifiable evidence, not "
                    "self-reported figures."
                ),
            },
            "Definition": {
                "citation": "World Bank Results Framework",
                "remediation": (
                    "Add the missing unit, timeframe, or target group to your result "
                    "statement — indicators in a Results Framework must be precisely "
                    "defined to be tracked consistently."
                ),
            },
            "Measurement": {
                "citation": "World Bank Results Framework",
                "remediation": (
                    "Describe your collection method and sampling approach — the "
                    "Results Framework requires a defined measurement methodology per "
                    "indicator."
                ),
            },
        },
    },
    "NESTA": {
        "label": "NESTA Standards of Evidence",
        # Only Directness/Verification/Measurement are cited -- NESTA's published
        # standard doesn't address Recency/Definition/Scope/Governance, and no
        # genuinely public NESTA language was found to ground an Integrity
        # citation either, so Integrity is deliberately left out rather than
        # force-mapped (see this module's docstring: no citation invented from
        # nothing).
        "criteria": {
            "Directness": {
                "citation": "NESTA Standards of Evidence — Level 3 (causal impact via RCT or comprehensive qualitative evaluation)",
                "remediation": (
                    "Add a comparison/control group basis or a rigorous qualitative "
                    "evaluation design so your evidence demonstrates causality, not "
                    "just a plausible link — NESTA Level 3 requires evidence the "
                    "observed effect is actually caused by your intervention, not "
                    "merely correlated with it."
                ),
            },
            "Verification": {
                "citation": "NESTA Standards of Evidence — Level 4 (independent evaluation)",
                "remediation": (
                    "Name an internal reviewer or, ideally, commission an independent "
                    "evaluation — NESTA Level 4 requires an independent evaluation to "
                    "validate the impact, not a self-reported figure."
                ),
            },
            "Measurement": {
                "citation": "NESTA Standards of Evidence — Level 2 (data showing change)",
                "remediation": (
                    "Describe your collection method and sampling approach — NESTA "
                    "Level 2 requires data collection that shows positive change among "
                    "the people your intervention reaches, not just an activity count."
                ),
            },
        },
    },
}


def evaluate_frameworks(evaluation: dict) -> dict:
    """Given one evaluate_submission() output, returns per-framework pass/fail using the
    universal thresholds (mirrors get_what_to_fix()'s exact trigger conditions -- see module
    docstring) against evaluator.DIMENSION_MAP's components.

    Returns {framework_key: {"label": str, "overall_ready": bool, "rows": [...]}}, where each
    row is {"criterion", "pass", "citation", "current_value", "max_value", "remediation"
    (only present if pass is False)}. Only criteria the framework actually cites appear in
    "rows" -- a criterion with no entry for a given framework is not included, since forcing
    a citation for every framework x criterion pair where the source material doesn't support
    one would itself be a form of fabrication. Callers rendering all 8 DIMENSION_MAP criteria
    per framework should treat any criterion absent from "rows" as "not directly assessed by
    this framework."

    Never raises -- returns {} for a falsy/malformed evaluation, matching this codebase's
    degrade-gracefully convention."""
    if not evaluation:
        return {}
    try:
        results = {}
        for fw_key, fw in FRAMEWORKS.items():
            rows = []
            overall_ready = True
            for dim_name, dim_info in fw["criteria"].items():
                if dim_name not in DIMENSION_MAP:
                    continue
                comp_key, score_key, max_val = DIMENSION_MAP[dim_name]
                comp = evaluation.get(comp_key) or {}
                if score_key not in comp:
                    continue
                current = comp.get(score_key) or 0
                threshold = (
                    _NESTA_THRESHOLD_OVERRIDES.get(dim_name, _UNIVERSAL_THRESHOLDS.get(dim_name, 0))
                    if fw_key == "NESTA" else
                    _UNIVERSAL_THRESHOLDS.get(dim_name, 0)
                )
                passed = current >= threshold
                if not passed:
                    overall_ready = False
                row = {
                    "criterion": dim_name,
                    "pass": passed,
                    "citation": dim_info["citation"],
                    "current_value": current,
                    "max_value": max_val,
                }
                if not passed:
                    row["remediation"] = dim_info["remediation"]
                rows.append(row)
            results[fw_key] = {
                "label": fw["label"],
                "overall_ready": overall_ready,
                "rows": rows,
            }
        return results
    except Exception:
        return {}
