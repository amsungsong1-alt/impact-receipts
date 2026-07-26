"""
utils/interrogator.py — Laudon Ch.11, C4: Donor Interrogator, a bounded
question-selection agent (session-only this phase; see Ch.11 Phase 3 plan).

Not a free-form LLM agent -- select_questions() only ever chooses among
pre-authored, donor-grounded questions in knowledge/donor_questions.yaml
(hot-reloadable, same convention as utils/inference.py::load_rule_base() /
utils/taxonomy.py::load_taxonomy()) and never generates new question text,
so it carries zero of the fabrication risk a free-generation approach would.

For each *fired* rule (a weak criterion, from utils.inference.apply_rules()'s
trace), looks up (donor, criterion) in the YAML. Declines gracefully --
never invents filler -- when either no donor-specific question exists for
that (donor, criterion) pair, or the submission's relevant evidence field is
itself uncertain (utils.extraction_schema.is_uncertain()) -- there is
nothing real to ask about yet.
"""
from __future__ import annotations
import os

import yaml

from utils.extraction_schema import is_uncertain

_QUESTIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "donor_questions.yaml"
)

# Which evidence-dict field grounds each criterion's question -- if that
# field is itself uncertain/missing, there's nothing real to ask about yet.
# Criteria absent here (Definition/Measurement/Integrity/Scope/Governance)
# have no donor_questions.yaml content either, so they fall through to the
# "no question on file" decline path below without needing a special case.
_CRITERION_FIELD = {
    "Directness": "description",
    "Verification": "verified_by",
    "Recency": "recency",
}


def load_donor_questions() -> dict:
    """Re-reads knowledge/donor_questions.yaml fresh on every call --
    hot-reloadable, same convention as utils/inference.py::load_rule_base().
    Returns {} if the file is missing or malformed rather than raising."""
    if not os.path.isfile(_QUESTIONS_PATH):
        return {}
    try:
        with open(_QUESTIONS_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _first_evidence(submission: dict) -> dict:
    ev_list = (submission or {}).get("evidence", []) or []
    return ev_list[0] if ev_list else {}


def select_questions(rule_trace: list, donor: str, submission: dict) -> list:
    """For each fired rule in rule_trace, selects one donor-grounded question
    per distinct criterion (a criterion can have more than one rule fire
    against it -- only the first is used). Returns a list of:
      {"criterion", "question", "declined": False, "source"} on a match, or
      {"criterion", "declined": True, "reason"} when there's nothing real to
      ask -- either the relevant evidence field is uncertain, or this donor
      has no question on file for that criterion.
    Never raises: an unknown donor, an empty/malformed trace, or a missing
    YAML file all degrade to an empty or all-declined list.
    """
    bank = load_donor_questions().get("questions", {})
    donor_bank = bank.get(donor, {}) if isinstance(bank, dict) else {}
    evidence = _first_evidence(submission)

    seen_criteria = set()
    results = []
    for entry in (rule_trace or []):
        if not entry.get("fired"):
            continue
        criterion = entry.get("criterion", "")
        if not criterion or criterion in seen_criteria:
            continue
        seen_criteria.add(criterion)

        field_name = _CRITERION_FIELD.get(criterion)
        if field_name is not None and is_uncertain(evidence.get(field_name, "")):
            results.append({
                "criterion": criterion,
                "declined": True,
                "reason": (
                    f"Your evidence's {field_name.replace('_', ' ')} field isn't filled in "
                    "yet — nothing to ask about until it is."
                ),
            })
            continue

        q = donor_bank.get(criterion) if isinstance(donor_bank, dict) else None
        if not q or not q.get("question"):
            results.append({
                "criterion": criterion,
                "declined": True,
                "reason": f"No {donor or 'this donor'}-specific question on file for {criterion} yet.",
            })
            continue

        results.append({
            "criterion": criterion,
            "question": q["question"].strip(),
            "declined": False,
            "source": q.get("source", ""),
        })
    return results
