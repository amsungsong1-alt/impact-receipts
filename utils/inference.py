"""
utils/inference.py — Laudon Ch.11 expert-system inference engine (forward chaining).

Loads the declarative rule base under knowledge/rules/ (one YAML file per criterion) and
evaluates each rule's condition against an already-scored submission's confidence_components/
clarity_components dicts, producing a firing trace. This is deliberately NOT a rewrite of
evaluator.py's actual scoring formulas -- compute_confidence()/compute_clarity() remain the
tested, deterministic source of truth for the numbers themselves. This module re-describes
what evaluator.get_what_to_fix() already computes in a declarative, non-programmer-editable,
hot-reloadable shape, and adds the rule-base version + a structured trace get_what_to_fix()
doesn't produce today.

Conditions are evaluated by a small, closed-form comparison parser -- NOT an unrestricted
eval(). This file is meant to be hand-edited by a MEL specialist who isn't a programmer, and
hot-reloaded (re-read on every call, no caching); an arbitrary eval() over that trust boundary
would be a real security hole, not just an engineering shortcut avoided for style.

Supported condition grammar (deliberately tiny):
    "<key> <op> <number>" where op is one of < <= > >= ==
    "<clause> and <clause>" -- ANDs any number of the above clauses together
Unknown keys (missing from the components dict) make that clause False rather than raising --
matches this codebase's pervasive .get(key, default) degrade-gracefully convention.
"""
from __future__ import annotations
import os
import re
import operator

import yaml

_RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "rules")

_OPS = {
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "<":  operator.lt,
    ">":  operator.gt,
}
# Longest-first so "<=" isn't matched as "<" followed by a stray "=".
_CLAUSE_RE = re.compile(r"^\s*(\w+)\s*(<=|>=|==|<|>)\s*([\d.]+)\s*$")


def _eval_clause(clause: str, facts: dict) -> bool:
    m = _CLAUSE_RE.match(clause)
    if not m:
        return False
    key, op, value = m.group(1), m.group(2), float(m.group(3))
    if key not in facts or facts[key] is None:
        return False
    try:
        return _OPS[op](float(facts[key]), value)
    except (TypeError, ValueError):
        return False


def evaluate_condition(condition: str, facts: dict) -> bool:
    """Evaluates a rule's `condition` string against a flat facts dict (the
    merged confidence_components + clarity_components of one evaluation).
    "A and B" requires every clause to hold; a single clause is just itself."""
    if not condition:
        return False
    clauses = [c.strip() for c in condition.split(" and ")]
    return all(_eval_clause(c, facts) for c in clauses)


def load_rule_base() -> list:
    """Reads every YAML file under knowledge/rules/ fresh on each call --
    deliberately no caching, so a hand-edited rule takes effect on the very
    next request with no restart/redeploy (Section D's "hot-reloadable"
    requirement). Returns a flat list of rule dicts across all criteria.
    Malformed/missing files degrade to an empty list for that file rather
    than crashing the whole rule base -- matches this codebase's
    degrade-gracefully convention for anything that can fail at runtime."""
    rules = []
    if not os.path.isdir(_RULES_DIR):
        return rules
    for fname in sorted(os.listdir(_RULES_DIR)):
        if not fname.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(_RULES_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or []
            if isinstance(loaded, list):
                rules.extend(loaded)
        except Exception:
            continue
    return rules


def get_rule_base_version(rules: list | None = None) -> str:
    """The rule base's version is the version string shared by its rules --
    every rule in this initial transcription carries the same version, so
    the first one found is authoritative. Returns "unversioned" if the rule
    base is empty (never raises -- an assessment must still be scoreable
    even if the rule base fails to load)."""
    rules = rules if rules is not None else load_rule_base()
    for r in rules:
        v = r.get("version")
        if v:
            return v
    return "unversioned"


def apply_rules(confidence_components: dict, clarity_components: dict) -> dict:
    """Forward-chaining inference: evaluates every loaded rule's condition
    against the merged facts (confidence_components + clarity_components of
    one already-scored submission) and returns the firing trace.

    Read-only over already-computed scores -- never touches raw submission
    text, never recomputes confidence_score/clarity_score. Extraction and
    scoring stay separated (see knowledge base module docstring); this
    function only ever sees the numbers evaluator.py already produced.

    Returns {"trace": [{"rule_id", "criterion", "fired", "rationale",
    "source"}, ...], "rule_base_version": str}. The trace includes every
    loaded rule (fired True or False), not just the ones that fired --
    "reconstructable from stored data alone" (Section C1's acceptance
    criterion) requires knowing what was checked, not only what matched.
    """
    rules = load_rule_base()
    facts = {**(confidence_components or {}), **(clarity_components or {})}
    trace = []
    for rule in rules:
        fired = evaluate_condition(rule.get("condition", ""), facts)
        trace.append({
            "rule_id": rule.get("id", ""),
            "criterion": rule.get("criterion", ""),
            "fired": fired,
            "rationale": rule.get("rationale", "") if fired else "",
            "source": rule.get("source", ""),
        })
    return {"trace": trace, "rule_base_version": get_rule_base_version(rules)}
