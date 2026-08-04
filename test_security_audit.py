"""
test_security_audit.py — golden tests for scripts/security_audit.py's pure
logic (Laudon Ch.8 hardening, C9). The individual checks themselves either
reuse already-tested logic (check_rls_coverage delegates to
utils.rls_coverage, covered by test_rls_coverage.py) or shell out to
external tools (gitleaks, pip-audit) that this repo's test suite
deliberately never calls over the network (see CLAUDE.md) -- so this file
covers the ranking/report logic that IS pure and fast: severity ordering
and the report's exit code.

Run with: python test_security_audit.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from security_audit import Weakness, CheckResult, _severity_score, print_report


def run_severity_score_orders_high_impact_above_low():
    low = Weakness("x", "low/low", "Low", "Low", "-")
    high = Weakness("x", "high/high", "High", "Very High", "-")
    medium = Weakness("x", "medium/medium", "Medium", "Medium", "-")
    assert _severity_score(high) > _severity_score(medium) > _severity_score(low)
    print("PASS: run_severity_score_orders_high_impact_above_low")


def run_print_report_exit_code_reflects_weaknesses(capsys=None):
    clean_results = [CheckResult("Check A", "OK", []), CheckResult("Check B", "SKIPPED", note="n/a")]
    assert print_report(clean_results) == 0, "no weaknesses across any check should exit 0"

    dirty_results = [CheckResult("Check A", "WEAKNESS", [
        Weakness("x", "something's wrong", "High", "High", "fix it"),
    ])]
    assert print_report(dirty_results) == 1, "any weakness should exit 1"
    print("PASS: run_print_report_exit_code_reflects_weaknesses")


def run_print_report_ranks_most_severe_first(capsys=None):
    import io
    import contextlib
    results = [
        CheckResult("Check A", "WEAKNESS", [
            Weakness("a", "low severity finding", "Low", "Low", "eventually"),
        ]),
        CheckResult("Check B", "WEAKNESS", [
            Weakness("b", "high severity finding", "High", "Very High", "immediately"),
        ]),
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_report(results)
    output = buf.getvalue()
    high_pos = output.find("high severity finding")
    low_pos = output.find("low severity finding")
    assert high_pos != -1 and low_pos != -1, "both findings should appear in the report"
    assert high_pos < low_pos, "the high-severity finding should be listed before the low-severity one"
    print("PASS: run_print_report_ranks_most_severe_first")


if __name__ == "__main__":
    run_severity_score_orders_high_impact_above_low()
    run_print_report_exit_code_reflects_weaknesses()
    run_print_report_ranks_most_severe_first()
    print("\nAll test_security_audit.py tests passed.")
