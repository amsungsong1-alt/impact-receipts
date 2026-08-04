"""
utils/extraction_schema.py — Laudon Ch.11 knowledge management, C2: extraction/scoring
separation, formalized.

Confirmed by direct audit (see the Ch.11 plan's Section B): every AI extraction call site in
this app (Instant Report Check's single-document extraction, CSV Portfolio's batch
extraction) already produces a fixed-shape JSON dict consumed by evaluator.evaluate_submission()
as plain data -- no extraction prompt ever mentions a score, and scoring never touches raw
text. This module doesn't change that separation; it validates the shape of what the LLM
returns *before* any field reaches session_state/a submission dict, and gives extraction call
sites a shared way to flag which extracted fields are uncertain -- so a rule can handle that
uncertainty explicitly (Section C2's own phrasing) rather than the field silently being treated
as a confident answer.

"Uncertain" here reuses the extraction prompts' own existing "Not found" sentinel (already the
practice at both call sites -- confirmed via audit: a "Not found"/empty value is already never
written into a submission field, so it already falls through to whatever evaluator.py's
scoring does for a genuinely missing field, never a guessed one) -- this module formalizes
that signal into something callers can inspect, rather than changing what already happens to a
missing field.
"""
from __future__ import annotations

# The extraction prompts' documented top-level sections (see app.py's
# INSTANT_CHECK_SYSTEM_PROMPT / BATCH_EXTRACTION_SYSTEM_PROMPT for the schema
# these mirror). Each maps to the Python type its value must be if present --
# not every key is required on every response (a short document may
# legitimately have nothing to say about, e.g., funder_readiness_inputs).
_EXPECTED_SECTION_TYPES: dict = {
    "result_basics": dict,
    "logframe_linkage": dict,
    "evidence_verification": dict,
    "funder_readiness_inputs": dict,
    "documents_referenced": list,
    "evidence_strengthening_checks": list,
    "extraction_metadata": dict,
    "results": list,  # multi-result path only
}

# The literal sentinel every extraction prompt is instructed to return for a
# field it couldn't find -- see INSTANT_CHECK_SYSTEM_PROMPT's Rule 14 ("For
# any of the above not found in the document, return 'Not found'").
UNCERTAIN_SENTINEL = "Not found"


def validate_extraction(data) -> tuple[bool, list[str]]:
    """Lightweight shape check on a parsed extraction response, run
    immediately after json.loads() and before any field is used. Does NOT
    require every section to be present (a real document can legitimately
    be missing whole sections) -- only that whatever sections ARE present
    have the right basic shape. Returns (is_valid, errors); is_valid is
    False only when the response is unusable altogether (not a dict, or a
    present section has the wrong type), matching this codebase's
    fail-closed-to-the-existing-fallback convention rather than rejecting
    partial-but-usable extractions.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return False, [f"top-level extraction response must be a JSON object, got {type(data).__name__}"]

    for section, expected_type in _EXPECTED_SECTION_TYPES.items():
        if section not in data:
            continue
        if not isinstance(data[section], expected_type):
            errors.append(
                f"'{section}' must be a {expected_type.__name__}, got {type(data[section]).__name__}"
            )

    return (len(errors) == 0), errors


def is_uncertain(value) -> bool:
    """True if an extracted field's value is the model's own "couldn't find
    this" sentinel, empty, or whitespace-only -- the same check every
    extraction call site already applies ad hoc before writing a field into
    session_state, formalized here as one shared function."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == "" or value.strip() == UNCERTAIN_SENTINEL
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def mark_uncertain_fields(flat_fields: dict) -> dict:
    """Given a flat {field_name: extracted_value} dict, returns
    {field_name: bool} flagging which are uncertain -- for a rule (or a UI
    caption) to handle explicitly, rather than the caller re-deriving the
    same "Not found"/empty check independently at each extraction site."""
    return {name: is_uncertain(value) for name, value in flat_fields.items()}


# ---------------------------------------------------------------------------
# council.py's synthesis output (Laudon Ch.8 hardening, C1): this is model
# output too -- a narrative synthesis rather than a structured extraction --
# but the same principle applies: validate its shape before it's used, don't
# just trust that syntactically-valid JSON also has the shape the caller
# expects. Schema mirrors council.run_council_assessment()'s own documented
# return-shape docstring exactly.
# ---------------------------------------------------------------------------

_COUNCIL_SYNTHESIS_BRIEF_TYPES: dict = {
    "what_score_means": str,
    "what_to_change": list,
    "how_long": str,
    "projected_status": str,
}


def validate_council_synthesis(data) -> tuple[bool, list[str]]:
    """Shape check on council.py's parsed synthesis JSON (the
    upgraded_result_statement/upgraded_evidence_statement/
    reporting_team_brief response), run immediately after json.loads() and
    before any of it is shown to a user or passed to check_fabrication().
    Same fail-closed-on-unusable, tolerant-of-missing-optional-parts
    convention as validate_extraction() above -- a synthesis response that
    passes json.loads() but comes back with, say, upgraded_result_statement
    as a list instead of a string (a prompt-injection attempt via document
    content, or just a model hiccup) must not reach check_fabrication() or
    the UI as if it were the documented shape."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return False, [f"synthesis response must be a JSON object, got {type(data).__name__}"]

    for key in ("upgraded_result_statement", "upgraded_evidence_statement"):
        if key in data and not isinstance(data[key], str):
            errors.append(f"'{key}' must be a string, got {type(data[key]).__name__}")

    if "reporting_team_brief" in data:
        brief = data["reporting_team_brief"]
        if not isinstance(brief, dict):
            errors.append(f"'reporting_team_brief' must be an object, got {type(brief).__name__}")
        else:
            for field, expected_type in _COUNCIL_SYNTHESIS_BRIEF_TYPES.items():
                if field in brief and not isinstance(brief[field], expected_type):
                    errors.append(
                        f"'reporting_team_brief.{field}' must be a {expected_type.__name__}, "
                        f"got {type(brief[field]).__name__}"
                    )

    return (len(errors) == 0), errors
