"""
prompts.py — Frozen prompt templates for Impact-Receipts.

SYSTEM_PROMPT is never modified at runtime. It is the stable cache anchor:
cache_control is applied to this block in evaluator.py so repeated calls
within a session hit the prompt cache (saving ~80% of input token cost).

The user prompt is assembled fresh per submission via build_user_prompt().
Claude is instructed to return ONLY valid JSON — no prose, no fences.

NOTE: The CTA label used in app.py is "Run My Confidence Check" (not "Evaluate
This Result"). This file drives the API path only — the current production
path uses rule-based scoring in evaluator.py and does not call these prompts.
"""

# ---------------------------------------------------------------------------
# SYSTEM PROMPT  (stable, cacheable — do not interpolate variables here)
# ---------------------------------------------------------------------------
# Length target: 2048+ tokens to qualify for claude-sonnet-4-6 prompt caching.
# The full scoring rubric and field-by-field guidance below achieves this.

SYSTEM_PROMPT = """You are an expert MEL (Monitoring, Evaluation, and Learning) evaluator \
working inside Impact-Receipts, a pre-submission verification tool for NGO staff. \
Your role is to stress-test a single reported result claim before it is submitted \
to a donor, board, or government counterpart.

You evaluate every submission across exactly three dimensions. You are rigorous, \
specific, and constructive. You never invent data, infer missing information, or \
fill gaps with assumptions. If information is absent, you note it as absent.

===========================================================================
DIMENSION 1: CLARITY OF CLAIM
===========================================================================
A strong claim answers four questions without ambiguity:
  (a) WHAT was achieved? — a measurable unit or outcome (e.g. "1,240 farmers
      adopted improved seed varieties", not "many farmers were supported")
  (b) WHO was reached or benefited? — a defined target group with enough
      specificity to be verified (e.g. "female-headed households under 2
      hectares", not "community members")
  (c) WHEN did this happen? — a bounded timeframe (e.g. "January–June 2024",
      not "recently" or "during the project period")
  (d) WHERE did this happen? — a geographic scope (e.g. "Kwara State, Nigeria",
      not "project area")

Scoring rubric for Clarity of Claim:
  5 — All four elements (what, who, when, where) are explicitly stated and
      unambiguous. The claim is self-contained.
  4 — Three of four elements are explicit. The missing one is easily inferred
      from context without guessing.
  3 — Two of four elements are explicit. The claim is partially verifiable
      but would require clarification before submission.
  2 — Only one element is explicit. The claim is vague and unlikely to satisfy
      a donor or independent reviewer without significant revision.
  1 — No measurable claim is present. The statement is aspirational, narrative,
      or entirely non-specific. This dimension cannot be evaluated.

===========================================================================
DIMENSION 2: STRENGTH OF EVIDENCE
===========================================================================
Evidence that strongly supports a result has these characteristics:
  (a) DIRECT — it specifically measures the claimed outcome, not a proxy
      or activity (e.g. adoption survey data, not just training attendance)
  (b) RECENT — collected during or immediately after the claimed timeframe,
      not years earlier
  (c) SPECIFIC — names the collection method, sample size, or coverage
      (e.g. "registers covering 1,240 participants by name and village",
      not "registers were kept")
  (d) VERIFIED — collected or reviewed by someone with appropriate authority
      (M&E officer, independent evaluator, partner organization, auditor)
  (e) SUFFICIENT — the volume and type of evidence is proportionate to the
      scale of the claim

Scoring rubric for Strength of Evidence:
  5 — Multiple pieces of direct, recent, verified, and specific evidence.
      The evidence would withstand scrutiny from an independent evaluator.
  4 — At least one strong direct evidence item with good specificity and
      recency. Minor gaps (e.g. no external verification) but credible overall.
  3 — Evidence exists but is indirect, partially dated, or lacks specificity.
      A reviewer would ask follow-up questions before accepting the result.
  2 — Evidence is weak, anecdotal, or only indirectly related to the claim.
      The result cannot be verified from what is provided.
  1 — No evidence is provided, or the provided description is so vague that
      it cannot be assessed. This dimension cannot be evaluated.

===========================================================================
DIMENSION 3: INDEPENDENT REVIEW
===========================================================================
Independent review adds a layer of assurance that the result has been
scrutinised by someone outside the team that generated it. Levels:
  (a) NONE — No review has occurred beyond the person who produced the figure.
  (b) INTERNAL — A colleague, M&E officer, or program manager within the
      same organisation has reviewed the result and evidence.
  (c) SENIOR INTERNAL — Senior leadership, a board member, or a cross-
      functional team has reviewed and signed off.
  (d) EXTERNAL — A partner organisation, independent evaluator, or donor
      representative has reviewed the result.
  (e) VERIFIED — A formal third-party verification or independent evaluation has confirmed it.

Scoring rubric for Independent Review:
  5 — External review or third-party verification completed. The result has been validated by
      a party with no stake in the outcome.
  4 — Senior internal review AND at least one external review. Strong
      internal governance with some external assurance.
  3 — Reviewed by M&E officer or program manager. Adequate internal review
      for routine reporting but not sufficient for high-stakes submission.
  2 — Only the person who produced the figure has reviewed it, or the
      review status is unclear.
  1 — No review of any kind has been conducted or reported. This dimension
      cannot be evaluated.

===========================================================================
OVERALL LABEL DERIVATION
===========================================================================
The overall label is derived from the three dimension scores as follows:

  STRONG     — All three dimension scores are 4 or 5. The result is ready
               for submission with only minor polish needed.
  MODERATE   — At least two dimension scores are 3 or above, and no score
               is 1. The result is submittable but requires specific fixes.
  WEAK       — One or more dimension scores are 2, and no score is 1.
               The result needs significant strengthening before submission.
  INCOMPLETE — One or more dimension scores are 1. A critical element is
               missing and the result cannot be meaningfully evaluated
               in that dimension without additional information.

===========================================================================
OUTPUT RULES
===========================================================================
1. Evaluate ONLY the information provided in the user message.
2. Do not infer, assume, or hallucinate any data, evidence, dates, or context.
3. If a field says "Not specified", treat it as absent — score accordingly.
4. Key issues must be specific (reference the actual submitted text).
5. Fixes must be actionable: tell the user exactly what to add or change.
6. Your entire response must be a single valid JSON object.
7. Do NOT wrap the JSON in markdown fences or add any prose before or after.
8. Maximum 5 items in key_issues. Maximum 5 items in fixes.
9. One fix per issue — they should correspond in order.
"""


# ---------------------------------------------------------------------------
# USER PROMPT BUILDER  (assembled fresh per submission)
# ---------------------------------------------------------------------------

def build_user_prompt(submission: dict) -> str:
    """
    Assemble a structured evaluation prompt from the submission dict.

    Expected submission keys:
        result_statement, target_group, timeframe, geographic_scope,
        evidence (list of dicts), internal_review, external_review,
        additional_context (optional)
    """
    evidence_block = _format_evidence(submission.get("evidence", []))

    return f"""Evaluate the following submitted result and return a JSON object \
matching the schema at the end of this message.

=== SUBMITTED RESULT ===

Result Statement:
{submission.get("result_statement", "Not provided")}

Target Group:
{submission.get("target_group", "Not specified")}

Timeframe:
{submission.get("timeframe", "Not specified")}

Geographic Scope:
{submission.get("geographic_scope", "Not specified")}

=== SUPPORTING EVIDENCE ===

{evidence_block}

=== REVIEW STATUS ===

Internal Review: {submission.get("internal_review", "Not specified")}
External Review: {submission.get("external_review", "Not specified")}

=== ADDITIONAL CONTEXT ===

{submission.get("additional_context") or "None provided."}

=== REQUIRED JSON OUTPUT ===

Return exactly this JSON structure. No markdown. No prose. JSON only.

{{
  "scores": {{
    "clarity_of_claim": {{
      "score": <integer 1-5>,
      "rationale": "<2-3 sentences referencing the submitted text>",
      "missing_elements": ["<specific missing item>", "..."]
    }},
    "strength_of_evidence": {{
      "score": <integer 1-5>,
      "rationale": "<2-3 sentences referencing the submitted text>",
      "missing_elements": ["<specific missing item>", "..."]
    }},
    "independent_review": {{
      "score": <integer 1-5>,
      "rationale": "<2-3 sentences referencing the submitted text>",
      "missing_elements": ["<specific missing item>", "..."]
    }}
  }},
  "key_issues": [
    "<specific issue 1>",
    "<specific issue 2>",
    "<up to 5 issues>"
  ],
  "fixes": [
    "<actionable fix for issue 1>",
    "<actionable fix for issue 2>",
    "<one fix per issue, same order>"
  ],
  "overall_label": "<Strong | Moderate | Weak | Incomplete>",
  "label_rationale": "<1-2 sentences explaining the label>"
}}
"""


def _format_evidence(evidence: list) -> str:
    """Format a list of evidence dicts into readable text for the prompt."""
    if not evidence:
        return "No evidence provided."

    lines = []
    for i, item in enumerate(evidence, 1):
        lines.append(
            f"Item {i}:\n"
            f"  Type:        {item.get('type', 'Not specified')}\n"
            f"  Description: {item.get('description', 'Not specified')}\n"
            f"  Date/Recency:{item.get('recency', 'Not specified')}\n"
            f"  Verified by: {item.get('verified_by', 'Not specified')}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Score rationale tooltip anchors (v3.0) — imported by app.py help= strings
# ---------------------------------------------------------------------------

TOOLTIP_DIRECTNESS = (
    "Scores how directly your evidence links programme activities to the reported result. "
    "Anchored in World Bank IEG Process Tracing standards (2025) and 3ie Contribution Analysis."
)

TOOLTIP_VERIFICATION = (
    "Scores the independence and credibility of whoever verified this result. "
    "Anchored in USAID ADS 201.3.5.7 Data Quality Assessment — Independence criterion "
    "and classical audit principle of verifier independence."
)

TOOLTIP_RECENCY = (
    "Scores how recent your evidence is relative to the result timeframe. "
    "USAID DQA requires evidence collected within 12 months for full score. "
    "Anchored in USAID ADS 201.3.5.7 — Timeliness criterion."
)

TOOLTIP_DEFINITION = (
    "Scores how precisely the result is defined. "
    "Anchored in OECD-DAC Evaluation Criterion: Relevance (2019) — "
    "is what was measured what was intended?"
)

TOOLTIP_MEASUREMENT = (
    "Scores whether the result uses a verifiable, quantifiable indicator. "
    "Anchored in USAID ADS 201.3.5.7 — Precision criterion."
)

TOOLTIP_INTEGRITY = (
    "Scores whether the data collection process is free from manipulation risk. "
    "Anchored in USAID ADS 201.3.5.7 — Integrity criterion and "
    "Bond Evidence Principles (2024) — Transparency."
)

TOOLTIP_SCOPE = (
    "Scores whether the result specifies who was affected, where, and under what conditions. "
    "Anchored in OECD-DAC Evaluation Criterion: Coherence (2019)."
)

TOOLTIP_GOVERNANCE = (
    "Scores whether there is an accountable owner for this result and its evidence. "
    "Anchored in classical audit principle of Traceability and "
    "FCDO Evaluation Policy (January 2025) — accountability for evidence."
)

# ---------------------------------------------------------------------------
# Beneficiary Voice Bonus strings (v3.0)
# ---------------------------------------------------------------------------

BENEFICIARY_VOICE_TOOLTIP = (
    "Scores whether your evidence includes the perspectives of people the programme serves. "
    "Anchored in Bond Evidence Principles 2024 (Voice & Inclusion) and "
    "60 Decibels Lean Data Methodology. No competitor scores this at pre-submission stage — "
    "it is your fastest route to a higher evidence quality rating with FCDO and GIZ donors."
)

BENEFICIARY_VOICE_WHATTOFIX = {
    0.0: (
        "No beneficiary voice detected. Add a structured feedback mechanism "
        "(e.g., post-activity survey, focus group discussion) to earn up to "
        "0.35 bonus points. FCDO's 2025 Evaluation Policy requires evidence "
        "of equity and inclusion in programme results."
    ),
    0.15: (
        "Beneficiary voice mentioned but not systematically collected. "
        "Formalise your feedback method (structured survey or FGD with "
        "documentation) to move from 0.15 to 0.35 bonus points."
    ),
    0.35: (
        "Good — structured beneficiary feedback detected. To reach maximum "
        "0.5 bonus points, use an independently administered feedback tool "
        "(e.g., phone survey by a non-programme enumerator)."
    ),
    0.5: (
        "Excellent — independently collected or benchmarked beneficiary "
        "feedback detected. This is the gold standard for Voice & Inclusion "
        "per Bond Evidence Principles 2024."
    ),
}

# ---------------------------------------------------------------------------
# FCDO citation (v3.0)
# ---------------------------------------------------------------------------

FCDO_CITATION = (
    "FCDO Evaluation Policy (reviewed January 2025), "
    "UK Foreign, Commonwealth & Development Office. "
    "https://www.gov.uk/government/publications/fcdo-evaluation-policy-2025"
)

# Updated methodology stack display string
METHODOLOGY_STACK = (
    "Impact-Receipts v3.0 dual-axis scoring "
    "(USAID ADS 201.3.5.7 / OECD-DAC 2019 / Bond Evidence Principles 2024 / "
    "FCDO Evaluation Policy January 2025 / World Bank IEG 2025)"
)
