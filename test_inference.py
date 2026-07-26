"""
test_inference.py — golden tests for utils/inference.py (Laudon Ch.11 expert-system
inference engine: loads knowledge/rules/*.yaml, evaluates rule conditions against
already-scored components, produces a firing trace).

No pytest, no network calls. Run with: python test_inference.py
"""

import evaluator
import test_app
from utils import inference


def run_rule_base_loads_cleanly():
    failures = []
    rules = inference.load_rule_base()
    if len(rules) != 10:
        failures.append(f"expected 10 rules across the 8 criterion YAML files, got {len(rules)}")

    expected_criteria = {"Directness", "Verification", "Recency", "Definition",
                          "Measurement", "Integrity", "Scope", "Governance"}
    got_criteria = {r.get("criterion") for r in rules}
    if got_criteria != expected_criteria:
        failures.append(f"expected rules covering {expected_criteria}, got {got_criteria}")

    for r in rules:
        for key in ("id", "criterion", "condition", "rationale", "source", "version"):
            if key not in r:
                failures.append(f"rule {r.get('id', '?')} is missing required key {key!r}")
        if not isinstance(r.get("id"), str) or not r["id"]:
            failures.append(f"rule has a missing/non-string id: {r}")

    ids = [r["id"] for r in rules]
    if len(ids) != len(set(ids)):
        failures.append(f"duplicate rule ids found: {ids}")

    version = inference.get_rule_base_version(rules)
    if version != "2026.07.1":
        failures.append(f"expected rule base version '2026.07.1', got {version!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: rule base loads cleanly — 10 rules, all 8 criteria covered, required keys present, unique ids.")


def run_condition_parser():
    """The tiny closed-form comparison parser -- never an eval(). Confirms
    single clauses, AND-chains, unknown keys, and malformed conditions all
    degrade safely rather than raising."""
    failures = []

    cases = [
        ("direct_score < 1.2", {"direct_score": 1.0}, True),
        ("direct_score < 1.2", {"direct_score": 1.5}, False),
        ("direct_score >= 1.2 and direct_score < 2.0", {"direct_score": 1.5}, True),
        ("direct_score >= 1.2 and direct_score < 2.0", {"direct_score": 1.0}, False),
        ("direct_score >= 1.2 and direct_score < 2.0", {"direct_score": 2.0}, False),
        ("verify_score == 2.0", {"verify_score": 2.0}, True),
        ("nonexistent_key < 5", {"direct_score": 1.0}, False),  # missing key -> False, never raises
        ("not a real condition", {"direct_score": 1.0}, False),  # malformed -> False, never raises
        ("", {"direct_score": 1.0}, False),  # empty condition -> False
    ]
    for condition, facts, expected in cases:
        got = inference.evaluate_condition(condition, facts)
        if got != expected:
            failures.append(f"evaluate_condition({condition!r}, {facts}) expected {expected}, got {got}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: condition parser — single clauses, AND-chains, and malformed/missing-key inputs all handled safely.")


def run_apply_rules_agrees_with_get_what_to_fix():
    """The firing trace must agree with evaluator.get_what_to_fix()'s live
    triggers for every golden fixture -- the two must match by construction
    (the YAML is a transcription of get_what_to_fix()'s own conditions), so
    disagreement here means the transcription has drifted from the live
    Python triggers and the YAML needs updating."""
    failures = []
    _CONF_CRITERIA = {"Directness", "Verification", "Recency"}
    _CLAR_CRITERIA = {"Definition", "Measurement", "Integrity", "Scope", "Governance"}

    for case_name, sub in test_app.CASES.items():
        ev = evaluator.evaluate_submission(sub)
        result = inference.apply_rules(ev["confidence_components"], ev["clarity_components"])

        conf_fixes = sum(1 for f in ev["fixes"] if f["dimension"] == "confidence")
        clar_fixes = sum(1 for f in ev["fixes"] if f["dimension"] == "clarity")
        conf_fired = sum(1 for t in result["trace"] if t["fired"] and t["criterion"] in _CONF_CRITERIA)
        clar_fired = sum(1 for t in result["trace"] if t["fired"] and t["criterion"] in _CLAR_CRITERIA)

        if conf_fixes != conf_fired:
            failures.append(
                f"{case_name}: confidence fixes[] count ({conf_fixes}) != rule-trace fired count "
                f"({conf_fired}) -- YAML rule base has drifted from get_what_to_fix()'s live triggers"
            )
        if clar_fixes != clar_fired:
            failures.append(
                f"{case_name}: clarity fixes[] count ({clar_fixes}) != rule-trace fired count "
                f"({clar_fired}) -- YAML rule base has drifted from get_what_to_fix()'s live triggers"
            )

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: firing trace agrees with get_what_to_fix()'s live triggers across all 12 golden fixtures.")


def run_wiring_is_additive_and_deterministic():
    """evaluate_submission() must expose rule_trace/rule_base_version without
    changing any existing score, and repeated calls on the same input must
    produce an identical trace (Section C1's determinism acceptance
    criterion)."""
    failures = []
    ev1 = evaluator.evaluate_submission(test_app.CASES["strong"])
    ev2 = evaluator.evaluate_submission(test_app.CASES["strong"])

    if "rule_trace" not in ev1 or "rule_base_version" not in ev1:
        failures.append("evaluate_submission() did not populate rule_trace/rule_base_version")
    if ev1.get("rule_trace") != ev2.get("rule_trace"):
        failures.append("identical input produced two different firing traces -- not deterministic")
    if ev1.get("confidence_score") != evaluator.evaluate_submission(test_app.CASES["strong"])["confidence_score"]:
        failures.append("confidence_score changed across identical calls after adding rule_trace wiring")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: rule_trace/rule_base_version wiring is additive and deterministic.")


def run_degrades_gracefully_on_missing_rules_dir():
    """load_rule_base() must return [] (not raise) when knowledge/rules/
    doesn't exist -- matches this codebase's degrade-gracefully convention,
    and apply_rules() must still return a valid (empty) trace."""
    failures = []
    original_dir = inference._RULES_DIR
    inference._RULES_DIR = "/nonexistent/path/that/does/not/exist"
    try:
        rules = inference.load_rule_base()
        if rules != []:
            failures.append(f"expected [] for a missing rules directory, got {rules}")
        result = inference.apply_rules({"direct_score": 1.0}, {"definition_score": 1.0})
        if result["trace"] != []:
            failures.append(f"expected an empty trace when the rule base can't load, got {result['trace']}")
        if result["rule_base_version"] != "unversioned":
            failures.append(f"expected 'unversioned' when the rule base can't load, got {result['rule_base_version']!r}")
    finally:
        inference._RULES_DIR = original_dir

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: missing rules directory degrades to an empty trace / 'unversioned', never raises.")


if __name__ == "__main__":
    run_rule_base_loads_cleanly()
    run_condition_parser()
    run_apply_rules_agrees_with_get_what_to_fix()
    run_wiring_is_additive_and_deterministic()
    run_degrades_gracefully_on_missing_rules_dir()
