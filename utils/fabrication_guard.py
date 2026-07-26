"""
utils/fabrication_guard.py — Laudon Ch.11, C5: fabrication guard as a hard gate.

Moved here from council.py (which still imports check_fabrication back for backward
compatibility — see the bottom of this module's docstring) so the guard is its own
inspectable, independently testable module rather than living inside the one file that
happens to make the AI calls it guards.

The guard is not a prompt instruction; it is code. Every numeral/year/percentage in an
AI-drafted statement must appear somewhere in the user's own submission fields (normalized
comparison) or the statement is withheld. This is the machine-checked backstop behind
council.py's synthesis prompt's own (soft, unenforceable) instruction not to invent numbers.

Non-negotiable rule (see CLAUDE.md): no AI feature may invent, estimate, or impute a number,
date, or fact the user didn't supply. This module is the enforcement mechanism.
"""
from __future__ import annotations
import re

_NUMERIC_TOKEN_RE = re.compile(r"\d[\d,]*\.?\d*%?")


def _extract_numeric_tokens(text: str) -> set[str]:
    """Extract normalized numeric tokens (ints, decimals, percentages) from text.

    Strips thousands-separator commas, a trailing '%', and a trailing '.' —
    the last of which handles a sentence-ending period glued onto a match
    (e.g. "...in 2025." must normalize to match a bare "2025" elsewhere)
    without touching a genuine decimal like "3.5".
    """
    if not text:
        return set()
    tokens = set()
    for raw in _NUMERIC_TOKEN_RE.findall(text):
        norm = raw.replace(",", "").rstrip("%").rstrip(".")
        if norm:
            tokens.add(norm)
    return tokens


def _submission_fact_text(submission: dict) -> str:
    """Concatenate the raw, untruncated user-supplied fields that count as
    'the source input' for fabrication checking. Deliberately does NOT reuse
    council._build_shared_context()'s output, which is truncated and also contains
    score-display numbers (e.g. "Confidence: 4.2/5.0") that are not project
    facts — checking against it risks both false negatives (truncated-away
    real facts) and false positives (a hallucinated number matching a score
    readout instead of an actual fact).
    """
    parts = []
    for key in (
        "result_statement", "target_group", "timeframe", "geographic_scope",
        "additional_context", "logframe_indicator", "logframe_target",
        "logframe_achievement", "beneficiary_voice", "bv_method_detail",
        "internal_review", "external_review",
    ):
        val = submission.get(key)
        if val:
            parts.append(str(val))

    for item in submission.get("evidence", []) or []:
        for key in ("type", "description", "recency", "verified_by"):
            val = item.get(key)
            if val:
                parts.append(str(val))

    for val in (submission.get("provenance_checklist") or {}).values():
        if isinstance(val, str) and val:
            parts.append(val)

    return "\n".join(parts)


def check_fabrication(draft: str, submission: dict) -> tuple[bool, list[str]]:
    """Check that every numeral/year/percentage in `draft` appears somewhere
    in the submission's own fields. Returns (is_clean, offending_tokens)."""
    if not draft:
        return True, []
    draft_tokens = _extract_numeric_tokens(draft)
    allowed_tokens = _extract_numeric_tokens(_submission_fact_text(submission))
    offending = sorted(draft_tokens - allowed_tokens)
    return (len(offending) == 0), offending


# Laudon Ch.11, C5: "the feature degrades to a structural suggestion" when a
# drafted field still fails the guard after every retry. One fallback per
# drafted field this module guards -- keyed by the same field names
# council.run_council_assessment() already uses in its "withheld" dict, so a
# caller can look this up directly by field name rather than another mapping.
_STRUCTURAL_FALLBACKS: dict = {
    "upgraded_result_statement": (
        "This sentence needs a denominator — you have not provided one. "
        "Add the specific number, date, or unit yourself; a suggested rewrite "
        "isn't shown here because it would have introduced a figure not in your evidence."
    ),
    "upgraded_evidence_statement": (
        "This description needs a source or sample size — you have not provided one. "
        "Add the specific detail yourself; a suggested rewrite isn't shown here because "
        "it would have introduced a figure not in your evidence."
    ),
}


def structural_fallback_message(field_name: str) -> str:
    """Generic, field-aware fallback shown when a drafted field still fails
    the guard after every retry attempt — a structural nudge, never a
    fabricated rewrite. Returns a generic message for any field name not in
    the known set, rather than raising on an unrecognized caller."""
    return _STRUCTURAL_FALLBACKS.get(
        field_name,
        "A suggested rewrite isn't shown here because it would have introduced "
        "content not in your evidence. Add the missing detail yourself.",
    )


# ---------------------------------------------------------------------------
# Laudon Ch.11, C3: explanation-layer grounding.
#
# check_fabrication() (above) catches an INVENTED number not present anywhere
# in the submission. This catches a different failure mode specific to the
# Explanation layer: the model correctly avoids inventing a new number, but
# MISSTATES an existing one -- e.g. "your Directness score is 1.8" when the
# real stored value is 1.2. That's not fabrication in the check_fabrication()
# sense (1.8 might be a real number that appears elsewhere, like a max value
# or a target), it's a grounding error specific to score explanations.
#
# Deliberately narrow: only "<criterion> (score) is/was/scored/: <number>"
# phrasing is checked -- NOT any number appearing near a criterion name, since
# the rubric text itself legitimately mentions thresholds/max values near a
# criterion name (e.g. "you need Directness to reach 1.2 to pass"), and a
# broader check would flag that correct advice as a "mismatch."
# ---------------------------------------------------------------------------

_CRITERION_SCORE_KEYS: dict = {
    "Directness":   "direct_score",
    "Verification": "verify_score",
    "Recency":      "recency_score",
    "Definition":   "definition_score",
    "Measurement":  "measurement_score",
    "Integrity":    "integrity_score",
    "Scope":        "scope_score",
    "Governance":   "governance_score",
}

_SCORE_CLAIM_RE = re.compile(
    r"\b(" + "|".join(_CRITERION_SCORE_KEYS.keys()) + r")\b"
    r"(?:\s+score)?\s*(?:is|was|scored|:)\s*(\d+\.?\d*)",
    re.IGNORECASE,
)

_GROUNDING_TOLERANCE = 0.05  # accounts for display rounding, not a loose match


def check_score_grounding(text: str, ev: dict) -> tuple[bool, list[str]]:
    """Checks every "<criterion> is/was/scored/: <number>"-style claim in
    `text` against the real stored component value for that criterion in
    `ev`. Returns (is_grounded, mismatches) where each mismatch is a
    human-readable string naming the criterion, the stated value, and the
    actual value -- for a caller to append a correcting caption rather than
    silently trusting the reply."""
    if not text or not ev:
        return True, []
    conf_comp = ev.get("confidence_components", {}) or {}
    clar_comp = ev.get("clarity_components", {}) or {}
    mismatches = []
    for match in _SCORE_CLAIM_RE.finditer(text):
        criterion_raw, number_raw = match.group(1), match.group(2)
        criterion = next(
            (c for c in _CRITERION_SCORE_KEYS if c.lower() == criterion_raw.lower()), None
        )
        if not criterion:
            continue
        score_key = _CRITERION_SCORE_KEYS[criterion]
        real_value = conf_comp.get(score_key)
        if real_value is None:
            real_value = clar_comp.get(score_key)
        if real_value is None:
            continue
        try:
            stated_value = float(number_raw)
        except ValueError:
            continue
        if abs(stated_value - float(real_value)) > _GROUNDING_TOLERANCE:
            mismatches.append(
                f"{criterion}: stated {stated_value}, actual {real_value}"
            )
    return (len(mismatches) == 0), mismatches
