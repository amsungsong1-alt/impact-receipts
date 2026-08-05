"""
utils/impact_linked_readiness.py — Impact-Linked Readiness Module (MVP).

Impact-linked finance (impact-linked loans, SIINC premium payments,
outcomes-based repayment) ties an enterprise's financial terms directly to
verified social outcomes. The whole mechanism lives or dies on credible,
verifiable INDICATOR-level evidence -- a narrower, higher-stakes question
than "is this donor report credible" (what evaluate_submission() answers).

This module checks whether ONE specific contractual indicator (e.g. "3,000
farmers onboarded, verified") is defensible enough for a funder to put real
money on. Deliberately a separate module, not folded into evaluator.py or
invoked inside evaluate_submission() -- this is a distinct product surface
(funders, not donors), run on-demand, and keeping it structurally separate
makes "never touches confidence_score/clarity_score" true by construction,
not just a convention to remember.

Fully deterministic, no AI/LLM call anywhere -- AI-judgment scoring would be
unacceptable in a financially contractual context. Every check is
flag-never-correct, same contract as evaluator.check_data_quality_flags().

Deliberately NOT built in this MVP pass (see docs -- flagged, not silently
skipped): any new schema/columns for custody location, collector identity,
or retention duration (Check 5's real gap); any new field for "aggregation
method" (Check 2's real gap -- shipped as an always-missing chain link
instead of guessing); baseline-timing/collector integrity and
target-plausibility-given-trajectory checks (out of scope for this MVP).
"""
from __future__ import annotations

from evaluator import (
    _extract_leading_number, _DISAGGREGATION_BONUS, get_indicator_maturity,
)

# A deliberately small, extensible list of unit tokens recognized in a
# logframe target/indicator string -- absence of any of these near the
# target number is what "ambiguous/absent units" actually means for Check 1.
# Not exhaustive by design; a real gap here is a false negative (missed
# flag), never a false positive (a real unit wrongly flagged as missing),
# since the check only ever WARNS, never blocks.
_UNIT_TOKENS = [
    "%", "percent", "households", "farmers", "beneficiaries", "participants",
    "people", "individuals", "students", "teachers", "staff", "communities",
    "villages", "schools", "clinics", "facilities", "usd", "ghs", "kg",
    "tonnes", "hectares", "days", "months", "years", "jobs", "loans",
]


def _has_unit_token(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(token in lowered for token in _UNIT_TOKENS)


def check_indicator_contractibility(submission: dict) -> list:
    """Is this ONE indicator defined tightly enough to condition a financial
    instrument on? Returns a list of {"check", "status": "pass"|"flag",
    "message"} dicts -- always one entry per concept (not just failures), so
    a funder-facing certificate shows what WAS checked, not only problems.
    Never raises on a missing/empty submission dict; never touches any score."""
    submission = submission or {}
    indicator = (submission.get("logframe_indicator", "") or "").strip()
    target = (submission.get("logframe_target", "") or "").strip()
    baseline = (submission.get("logframe_baseline", "") or "").strip()
    disaggregation_status = submission.get("disaggregation_status", "") or ""
    provenance = submission.get("provenance_checklist", {}) or {}

    checks = []

    if not (_has_unit_token(target) or _has_unit_token(indicator)):
        checks.append({
            "check": "units", "status": "flag",
            "message": (
                f"Target ({target!r}) has no recognizable unit (%, households, farmers, "
                "USD, etc.) — a funder needs an unambiguous unit before conditioning "
                "financial terms on this figure."
            ),
        })
    else:
        checks.append({"check": "units", "status": "pass", "message": "A unit is stated or implied."})

    if disaggregation_status not in _DISAGGREGATION_BONUS or _DISAGGREGATION_BONUS.get(disaggregation_status, 0.0) == 0.0:
        checks.append({
            "check": "disaggregation", "status": "flag",
            "message": (
                "No disaggregation rule stated for this indicator — a funder-grade "
                "indicator should specify how the figure breaks down (e.g. by sex, "
                "age, location)."
            ),
        })
    else:
        checks.append({"check": "disaggregation", "status": "pass", "message": "A disaggregation rule is stated."})

    if provenance.get("collection_tool_named") != "Yes":
        checks.append({
            "check": "verification_method", "status": "flag",
            "message": (
                "No data-collection tool/method confirmed as named for this indicator — "
                "a funder needs to know HOW this figure would be verified, not just what "
                "it claims."
            ),
        })
    else:
        checks.append({"check": "verification_method", "status": "pass", "message": "A collection tool/method is named."})

    if not baseline:
        checks.append({
            "check": "baseline", "status": "flag",
            "message": (
                (f"Target ({target!r}) is stated with no baseline" if target else "No baseline is stated")
                + " — impact-linked deals typically pay on CHANGE from a baseline; without "
                "one, the target can't be verified as a real improvement."
            ),
        })
    else:
        checks.append({"check": "baseline", "status": "pass", "message": "Both baseline and target are stated."})

    return checks


def trace_evidence_chain(submission: dict) -> list:
    """Structured 5-link evidence-chain trace for one indicator: definition
    -> collection instrument -> sampling approach -> raw records ->
    aggregation method. Reads the SAME provenance_checklist dict
    get_provenance_adjustment() reads -- no new checklist. Returns a list of
    {"link", "present": bool, "detail"} dicts in canonical chain order.
    aggregation_method is ALWAYS present=False -- no field anywhere captures
    it; an honest MVP gap, not a guess."""
    submission = submission or {}
    provenance = submission.get("provenance_checklist", {}) or {}

    contractibility = check_indicator_contractibility(submission)
    definition_present = all(c["status"] == "pass" for c in contractibility)

    traceable_answer = provenance.get("auditor_traceable", "")
    if traceable_answer == "Yes — an auditor could retrieve the original records":
        raw_records_present, raw_records_detail = True, "An auditor could retrieve the original records (self-declared)."
    elif traceable_answer == "Partially — some records would take effort to locate":
        raw_records_present, raw_records_detail = False, "Records are only PARTIALLY traceable (self-declared)."
    else:
        raw_records_present, raw_records_detail = False, "Records are not confirmed traceable to an auditor."

    return [
        {
            "link": "definition", "present": definition_present,
            "detail": (
                "The indicator passes all contractibility checks." if definition_present
                else "The indicator has at least one contractibility flag (see Check 1)."
            ),
        },
        {
            "link": "collection_instrument", "present": provenance.get("collection_tool_named") == "Yes",
            "detail": "Data-collection tool/method confirmed named." if provenance.get("collection_tool_named") == "Yes"
                      else "No data-collection tool/method confirmed named.",
        },
        {
            "link": "sampling_approach", "present": provenance.get("sampling_documented") == "Yes",
            "detail": "Sampling/selection approach confirmed documented." if provenance.get("sampling_documented") == "Yes"
                      else "No sampling/selection approach confirmed documented.",
        },
        {"link": "raw_records", "present": raw_records_present, "detail": raw_records_detail},
        {
            "link": "aggregation_method", "present": False,
            "detail": (
                "Not currently captured — ImpactProof does not yet ask how raw records "
                "were aggregated into this reported figure."
            ),
        },
    ]


def assess_verification_readiness(submission: dict) -> dict:
    """Self-declared verification-readiness signal for one indicator.
    Deliberately weaker than Checks 1/2: no custody-location, collector-
    identity, or retention-duration schema exists in this codebase today, so
    this reuses the existing auditor_traceable checklist answer and labels
    it unmistakably as self-declared, never as independently confirmed."""
    submission = submission or {}
    provenance = submission.get("provenance_checklist", {}) or {}
    traceable_answer = provenance.get("auditor_traceable", "")

    if traceable_answer == "Yes — an auditor could retrieve the original records":
        traceable = True
    elif traceable_answer == "Partially — some records would take effort to locate":
        traceable = False
    else:
        traceable = None

    return {
        "signal": "self_declared",
        "traceable": traceable,
        "basis": "Reported by the submitting organisation, not independently confirmed.",
        "gap": (
            "ImpactProof does not currently track custody location, collector identity, "
            "or retention duration for this indicator's records — these would need to be "
            "confirmed directly with the organisation before a funder relies on this signal."
        ),
    }


def _traffic_light(items: list, present_key: str = "present") -> str:
    """items: a list of dicts each carrying a boolean under present_key.
    green = all present, red = none present, amber = anything in between."""
    if not items:
        return "amber"
    flags = [bool(item.get(present_key)) for item in items]
    if all(flags):
        return "green"
    if not any(flags):
        return "red"
    return "amber"


def generate_readiness_certificate(submission: dict) -> dict:
    """Assembles all three checks into one indicator-level result. Traffic-
    light per check (red/amber/green -- deliberately not numeric, to avoid
    false comparability with the 0-5 confidence/clarity axes), a flattened
    named-gaps list, and a disclaimer. Never reads or returns
    confidence_score/clarity_score -- this is a structurally separate
    product surface from evaluate_submission(), not a replacement or an
    extension of it."""
    submission = submission or {}

    contractibility = check_indicator_contractibility(submission)
    contractibility_light = _traffic_light(
        [{"present": c["status"] == "pass"} for c in contractibility]
    )

    chain = trace_evidence_chain(submission)
    chain_light = _traffic_light(chain)

    verification = assess_verification_readiness(submission)
    verification_light = "green" if verification["traceable"] is True else "amber" if verification["traceable"] is False else "red"

    gaps = [c["message"] for c in contractibility if c["status"] == "flag"]
    gaps += [link["detail"] for link in chain if not link["present"]]
    gaps.append(verification["gap"])

    return {
        "indicator": submission.get("logframe_indicator", ""),
        "contractibility": {"light": contractibility_light, "checks": contractibility},
        "evidence_chain": {"light": chain_light, "links": chain},
        "verification_readiness": {"light": verification_light, **verification},
        "gaps": gaps,
        "disclaimer": (
            "Pre-verification diagnostic, not a verified-impact claim, not independent "
            "assurance. Deterministic, rule-based checks only — no AI judgement is "
            "involved. A human/independent verifier should still confirm any figure "
            "before it's relied on in a financial agreement."
        ),
    }
