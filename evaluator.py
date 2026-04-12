"""
evaluator.py — Rule-based evaluation for Impact-Receipts.

Fully local, no API calls, no cost. Scores each submission across three
dimensions using deterministic rules. Returns the same dict structure as
the API version so app.py is unchanged.

To switch to Claude API later, swap this file for the API version.
"""

import re

# ---------------------------------------------------------------------------
# Evidence type quality tiers
# ---------------------------------------------------------------------------

# These types carry stronger evidentiary weight in MEL contexts
STRONG_EVIDENCE_TYPES = {
    "Third-party evaluation report",
    "Project dataset / survey data",
    "Survey summary / assessment report",
    "Government / administrative records",
}

# ---------------------------------------------------------------------------
# Review score lookup tables (maps dropdown values → points)
# ---------------------------------------------------------------------------

INTERNAL_REVIEW_POINTS = {
    "Not reviewed": 0,
    "Reviewed by M&E Officer": 1,
    "Reviewed by Program Manager": 2,
    "Reviewed by senior leadership or board": 3,
    "Reviewed by multiple internal stakeholders": 3,
}

EXTERNAL_REVIEW_POINTS = {
    "No external review": 0,
    "Reviewed by partner organisation": 1,
    "Reviewed by independent evaluator": 2,
    "Reviewed by donor representative": 2,
    "Third-party audit completed": 3,
}

# ---------------------------------------------------------------------------
# Public API  (same interface as the API version)
# ---------------------------------------------------------------------------

def evaluate_submission(submission: dict) -> dict:
    """
    Run rule-based evaluation on a submission dict.

    Returns a dict with keys:
      scores, key_issues, fixes, overall_label, label_rationale
    """
    clarity  = _score_clarity(submission)
    evidence = _score_evidence(submission.get("evidence", []))
    review   = _score_review(submission)

    scores = {
        "clarity_of_claim":     clarity,
        "strength_of_evidence": evidence,
        "independent_review":   review,
    }

    key_issues, fixes = _generate_issues_and_fixes(scores)
    label, _          = compute_confidence_label(scores)
    label_rationale   = _build_label_rationale(scores, label)

    return {
        "scores":          scores,
        "key_issues":      key_issues,
        "fixes":           fixes,
        "overall_label":   label,
        "label_rationale": label_rationale,
    }


def compute_confidence_label(scores: dict) -> tuple:
    """
    Derive the confidence label from dimension scores.
    Python-authoritative — the UI always uses this, not the stored label.

    Returns (label: str, hex_color: str).
    """
    dim_scores = [
        scores.get("clarity_of_claim",     {}).get("score", 1),
        scores.get("strength_of_evidence", {}).get("score", 1),
        scores.get("independent_review",   {}).get("score", 1),
    ]

    if any(s == 1 for s in dim_scores):
        return "Incomplete", "#C0392B"   # deep red
    if any(s == 2 for s in dim_scores):
        return "Weak",       "#E67E22"   # orange
    if all(s >= 4 for s in dim_scores):
        return "Strong",     "#27AE60"   # green
    return "Moderate",       "#F39C12"   # amber


# ---------------------------------------------------------------------------
# Dimension 1: Clarity of Claim
# ---------------------------------------------------------------------------

def _score_clarity(submission: dict) -> dict:
    """
    Score 1-5 based on how many of four key claim elements are present:
      1. A measurable quantity (number) in the result statement
      2. A timeframe
      3. A target group
      4. A geographic scope
    Score = elements_found + 1  (0 found → 1, 4 found → 5)
    """
    statement   = submission.get("result_statement", "").strip()
    timeframe   = submission.get("timeframe", "").strip()
    target_grp  = submission.get("target_group", "").strip()
    geography   = submission.get("geographic_scope", "").strip()

    def _is_set(val: str) -> bool:
        return bool(val) and val.lower() not in ("not specified", "")

    checks = {
        "measurable quantity": bool(re.search(r"\b\d[\d,]*\b", statement)),
        "timeframe":           _is_set(timeframe),
        "target group":        _is_set(target_grp),
        "geographic scope":    _is_set(geography),
    }

    missing = []
    for label, present in checks.items():
        if not present:
            missing.append(f"No {label} specified in the result claim")

    elements_found = sum(checks.values())
    score = max(1, min(5, elements_found + 1))

    found_labels   = [k for k, v in checks.items() if v]
    missing_labels = [k for k, v in checks.items() if not v]

    parts = []
    if found_labels:
        parts.append(f"Present: {', '.join(found_labels)}.")
    if missing_labels:
        parts.append(f"Missing: {', '.join(missing_labels)}.")
    rationale = " ".join(parts) or "No evaluable content in the result statement."

    return {"score": score, "rationale": rationale, "missing_elements": missing}


# ---------------------------------------------------------------------------
# Dimension 2: Strength of Evidence
# ---------------------------------------------------------------------------

def _score_evidence(evidence_items: list) -> dict:
    """
    Score 1-5 based on quantity and quality of evidence items.

    Each item can earn up to 4 quality points:
      +1  substantive description (> 30 chars)
      +1  recency / collection date provided
      +1  verifier / collector identified
      +1  evidence type is in the STRONG_EVIDENCE_TYPES tier

    Score is derived from (quality_points / max_possible):
      ratio ≥ 0.75 → 5 | ≥ 0.55 → 4 | ≥ 0.35 → 3 | else → 2
    A single item caps at 4 regardless of quality.
    Zero items → 1.
    """
    if not evidence_items:
        return {
            "score": 1,
            "rationale": "No evidence items were provided. This dimension cannot be evaluated.",
            "missing_elements": ["No evidence provided"],
        }

    n              = len(evidence_items)
    quality_points = 0
    item_issues    = []

    for i, item in enumerate(evidence_items, 1):
        desc     = item.get("description", "").strip()
        recency  = item.get("recency",     "").strip()
        verifier = item.get("verified_by", "").strip()
        ev_type  = item.get("type",        "")

        if len(desc) > 30:
            quality_points += 1
        else:
            item_issues.append(f"Item {i}: description is too vague or missing")

        if recency and recency.lower() not in ("", "not specified"):
            quality_points += 1
        else:
            item_issues.append(f"Item {i}: no collection date or recency stated")

        if verifier and verifier.lower() not in ("", "not specified"):
            quality_points += 1
        else:
            item_issues.append(f"Item {i}: no verifier or collector identified")

        if ev_type in STRONG_EVIDENCE_TYPES:
            quality_points += 1

    max_points = n * 4
    ratio      = quality_points / max_points

    if ratio >= 0.75:
        score = 5
    elif ratio >= 0.55:
        score = 4
    elif ratio >= 0.35:
        score = 3
    else:
        score = 2

    # A single evidence item cannot demonstrate the corroboration needed for a 5
    if n == 1:
        score = min(score, 4)

    if ratio >= 0.75:
        quality_summary = "Evidence is well-documented with specific descriptions, dates, and verifiers."
    elif ratio >= 0.55:
        quality_summary = "Evidence has good coverage but some items lack specificity or verification details."
    elif ratio >= 0.35:
        quality_summary = "Evidence exists but is missing important details on recency, verifiers, or description."
    else:
        quality_summary = "Evidence items lack key details needed to substantiate the claim."

    rationale = (
        f"{n} evidence item{'s' if n > 1 else ''} provided "
        f"({quality_points}/{max_points} quality points). "
        f"{quality_summary}"
    )

    return {
        "score":            score,
        "rationale":        rationale,
        "missing_elements": item_issues[:3],   # top 3 to keep it actionable
    }


# ---------------------------------------------------------------------------
# Dimension 3: Independent Review
# ---------------------------------------------------------------------------

def _score_review(submission: dict) -> dict:
    """
    Score 1-5 from combined internal + external review points (0-6 total):
      0 → 1 | 1 → 2 | 2 → 3 | 3-4 → 4 | 5-6 → 5
    """
    internal = submission.get("internal_review", "Not reviewed")
    external = submission.get("external_review", "No external review")

    int_pts  = INTERNAL_REVIEW_POINTS.get(internal, 0)
    ext_pts  = EXTERNAL_REVIEW_POINTS.get(external, 0)
    total    = int_pts + ext_pts

    score_map = {0: 1, 1: 2, 2: 3, 3: 4, 4: 4, 5: 5, 6: 5}
    score     = score_map.get(total, 5)

    missing = []
    if int_pts == 0:
        missing.append("No internal review has been conducted")
    if ext_pts == 0:
        missing.append("No external or independent review has been conducted")

    if total == 0:
        coverage = "No review of any kind has been conducted."
    elif total <= 2:
        coverage = "Some internal review has occurred but no independent external verification."
    elif total <= 4:
        coverage = "Good review coverage combining internal governance and external input."
    else:
        coverage = "Strong review coverage including independent external verification."

    rationale = (
        f"Internal review: \"{internal}\". "
        f"External review: \"{external}\". "
        f"{coverage}"
    )

    return {"score": score, "rationale": rationale, "missing_elements": missing}


# ---------------------------------------------------------------------------
# Issues and fixes generator
# ---------------------------------------------------------------------------

def _generate_issues_and_fixes(scores: dict) -> tuple:
    """
    Produce a matched list of (issue, fix) pairs based on dimension scores
    and their missing_elements. Returns (key_issues, fixes), max 5 each.
    """
    issues = []
    fixes  = []

    # --- Clarity issues ---
    clarity_missing = scores["clarity_of_claim"]["missing_elements"]
    for m in clarity_missing:
        if "quantity" in m.lower():
            issues.append(
                "The result statement does not include a measurable number or quantity."
            )
            fixes.append(
                "Revise the statement to include a specific figure, "
                "e.g. '1,240 farmers trained' instead of 'farmers were trained'."
            )
        elif "timeframe" in m.lower():
            issues.append("No timeframe is specified for when this result was achieved.")
            fixes.append(
                "Add a bounded timeframe, e.g. 'between January and June 2024'."
            )
        elif "target group" in m.lower():
            issues.append("The target group who benefited is not defined.")
            fixes.append(
                "Specify who was reached, "
                "e.g. 'female-headed smallholder households under 2 hectares'."
            )
        elif "geographic" in m.lower():
            issues.append("No geographic scope is stated for this result.")
            fixes.append(
                "Add the location, e.g. 'Kwara State, Nigeria' or 'northern district'."
            )

    # --- Evidence issues ---
    ev_score   = scores["strength_of_evidence"]["score"]
    ev_missing = scores["strength_of_evidence"]["missing_elements"]

    if ev_score == 1:
        issues.append("No evidence has been provided to support this result.")
        fixes.append(
            "Add at least one evidence item — even an attendance register "
            "or a partner report significantly strengthens the claim."
        )
    elif ev_score == 2:
        if any("description" in m.lower() for m in ev_missing):
            issues.append(
                "Evidence descriptions are too vague to substantiate the claim."
            )
            fixes.append(
                "For each evidence item, write a specific description: "
                "what it contains, sample size, and how it was collected."
            )
        if any("date" in m.lower() or "recency" in m.lower() for m in ev_missing):
            issues.append(
                "Evidence items are missing collection dates or recency information."
            )
            fixes.append(
                "Add a collection date for each evidence item "
                "(e.g. 'June 2024') so reviewers can assess relevance."
            )
    elif ev_score == 3:
        if any("verifier" in m.lower() or "verified" in m.lower() for m in ev_missing):
            issues.append(
                "Some evidence items do not identify who collected or verified them."
            )
            fixes.append(
                "Name the verifier for each evidence item, "
                "e.g. 'Field M&E Officer' or 'Partner organisation data team'."
            )

    # --- Review issues ---
    rev_score   = scores["independent_review"]["score"]
    rev_missing = scores["independent_review"]["missing_elements"]

    if rev_score == 1:
        issues.append(
            "This result has not been reviewed by anyone, internal or external."
        )
        fixes.append(
            "Have at least one colleague (M&E Officer or Program Manager) "
            "review the result and evidence before submission."
        )
    elif rev_score == 2:
        if "No external or independent review" in " ".join(rev_missing):
            issues.append(
                "The result has only minimal internal review and no external validation."
            )
            fixes.append(
                "Request a review from a partner organisation or an independent evaluator "
                "before submitting to a donor."
            )
    elif rev_score == 3:
        if "No external" in " ".join(rev_missing):
            issues.append(
                "The result relies on internal review only — no external validation exists."
            )
            fixes.append(
                "For high-stakes submissions, seek an external spot-check "
                "or a partner sign-off on the supporting evidence."
            )

    return issues[:5], fixes[:5]


# ---------------------------------------------------------------------------
# Label rationale
# ---------------------------------------------------------------------------

def _build_label_rationale(scores: dict, label: str) -> str:
    dim_scores = [
        scores["clarity_of_claim"]["score"],
        scores["strength_of_evidence"]["score"],
        scores["independent_review"]["score"],
    ]
    low  = min(dim_scores)
    high = max(dim_scores)

    if label == "Strong":
        return (
            f"All three dimensions score {low}–{high}/5. "
            "The result is clearly stated, well-evidenced, and has been reviewed. "
            "It is ready for submission with only minor polish needed."
        )
    if label == "Moderate":
        weak_dims = [
            name for name, s in zip(
                ["Clarity", "Evidence", "Review"], dim_scores
            ) if s == 3
        ]
        return (
            f"The result is submittable but needs specific fixes. "
            f"Weakest area{'s' if len(weak_dims) > 1 else ''}: "
            f"{', '.join(weak_dims) if weak_dims else 'see dimension scores'}."
        )
    if label == "Weak":
        weak_dims = [
            name for name, s in zip(
                ["Clarity", "Evidence", "Review"], dim_scores
            ) if s == 2
        ]
        return (
            f"One or more dimensions score 2/5 "
            f"({', '.join(weak_dims)}). "
            "Significant strengthening is needed before this result can be submitted."
        )
    # Incomplete
    incomplete_dims = [
        name for name, s in zip(
            ["Clarity", "Evidence", "Review"], dim_scores
        ) if s == 1
    ]
    return (
        f"Critical information is missing in: "
        f"{', '.join(incomplete_dims)}. "
        "The result cannot be meaningfully evaluated without these elements."
    )


# ---------------------------------------------------------------------------
# Smoke test — run directly to verify the logic works end-to-end
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    test = {
        "result_statement": (
            "500 smallholder farmers in Kano State, Nigeria adopted improved "
            "seed varieties between January and June 2024."
        ),
        "target_group":      "Smallholder farmers with less than 2 hectares",
        "timeframe":         "January–June 2024",
        "geographic_scope":  "Kano State, Nigeria",
        "evidence": [
            {
                "type":        "Attendance sheet / participant register",
                "description": "Paper attendance registers from 10 training sessions, all 500 participants by name and village.",
                "recency":     "June 2024",
                "verified_by": "Field M&E Officer",
            }
        ],
        "internal_review": "Reviewed by M&E Officer",
        "external_review": "No external review",
        "additional_context": "",
    }

    result = evaluate_submission(test)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    label, color = compute_confidence_label(result["scores"])
    print(f"\nLabel: {label}  |  Color: {color}")
