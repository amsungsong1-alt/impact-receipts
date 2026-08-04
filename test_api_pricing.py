"""
test_api_pricing.py — golden tests for utils/api_pricing.py (Laudon Ch.9
CRM, C4): per-model cost computation, usage logging, and the real
per-assessment cost average CLTV nets against.

No pytest, no network calls. Run with: python test_api_pricing.py
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.api_pricing as api_pricing


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    api_pricing.Base.metadata.create_all(engine)
    return engine


def run_pricing_loads_and_computes():
    failures = []
    pricing = api_pricing.load_model_pricing()
    if "models" not in pricing:
        failures.append("model_pricing.yaml is missing the expected 'models' key")

    cost = api_pricing.compute_cost_pesewas("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
    if not cost or cost <= 0:
        failures.append(f"expected a positive cost for a known model, got {cost}")

    zero_cost = api_pricing.compute_cost_pesewas("not-a-real-model", 1000, 1000)
    if zero_cost != 0.0:
        failures.append(f"expected 0.0 cost for an unknown model, got {zero_cost}")

    if api_pricing.compute_cost_pesewas("claude-haiku-4-5-20251001", 0, 0) != 0.0:
        failures.append("expected 0.0 cost for 0 tokens")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: model_pricing.yaml loads cleanly, compute_cost_pesewas gives a positive cost "
          "for a known model, 0.0 for an unknown model or zero tokens.")


def run_log_api_usage_and_average():
    failures = []
    original_get_engine = api_pricing._get_engine
    engine = _fresh_engine()
    api_pricing._get_engine = lambda: engine
    try:
        api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "irc_extraction", 1000, 500)
        api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "batch_extraction", 2000, 1000)
        # A non-assessment call site must not pollute the average.
        api_pricing.log_api_usage("a@example.com", "claude-haiku-4-5-20251001", "score_explanation_chat", 500, 100)

        with Session(engine) as session:
            rows = session.query(api_pricing.ApiUsageLog).count()
        if rows != 3:
            failures.append(f"expected 3 logged rows, got {rows}")

        avg = api_pricing.compute_average_cost_per_assessment("a@example.com")
        if avg is None or avg <= 0:
            failures.append(f"expected a positive average cost, got {avg}")

        # Confirm the chat call site was excluded from the average by comparing
        # against a manual average of just the two ASSESSMENT_CALL_SITES rows.
        with Session(engine) as session:
            assessment_costs = [
                r.estimated_cost_pesewas for r in session.query(api_pricing.ApiUsageLog)
                .filter(api_pricing.ApiUsageLog.call_site.in_(api_pricing.ASSESSMENT_CALL_SITES)).all()
            ]
        expected_avg = round(sum(assessment_costs) / len(assessment_costs), 4)
        if avg != expected_avg:
            failures.append(f"expected average {expected_avg} (assessment call sites only), got {avg}")

        if api_pricing.compute_average_cost_per_assessment("nobody@example.com") is not None:
            failures.append("expected None for an account with no usage logged")

        # Never raises with no engine.
        api_pricing._get_engine = lambda: None
        api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "irc_extraction", 100, 100)
        if api_pricing.compute_average_cost_per_assessment("a@example.com") is not None:
            failures.append("expected None with no engine configured")
    finally:
        api_pricing._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: log_api_usage/compute_average_cost_per_assessment — correct logging, "
          "assessment-only averaging, no-data and no-engine degradation verified.")


def run_p95_cost():
    failures = []
    original_get_engine = api_pricing._get_engine
    engine = _fresh_engine()
    api_pricing._get_engine = lambda: engine
    try:
        # 20 assessment-call-site rows, costs 1..20 pesewas -- p95 of a
        # sorted 1..20 list via round(0.95*19)=18 (0-indexed) -> value 19.
        for i in range(1, 21):
            api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "irc_extraction", i * 100, i * 10)
        # Can't force an exact cost value through log_api_usage() (it derives
        # cost from tokens via the YAML rates), so assert against the actual
        # logged distribution's own 95th percentile instead of a hardcoded number.
        with Session(engine) as session:
            all_costs = sorted(
                r.estimated_cost_pesewas for r in session.query(api_pricing.ApiUsageLog).all()
            )
        expected_p95 = all_costs[min(len(all_costs) - 1, max(0, round(0.95 * (len(all_costs) - 1))))]

        p95 = api_pricing.compute_p95_cost_per_assessment("a@example.com")
        if p95 != round(expected_p95, 4):
            failures.append(f"expected p95 {round(expected_p95, 4)}, got {p95}")

        avg = api_pricing.compute_average_cost_per_assessment("a@example.com")
        if avg is None or p95 is None or p95 < avg:
            failures.append(f"p95 ({p95}) should be >= the mean ({avg}) for an increasing cost distribution")

        if api_pricing.compute_p95_cost_per_assessment("nobody@example.com") is not None:
            failures.append("expected None p95 for an account with no usage logged")

        api_pricing._get_engine = lambda: None
        if api_pricing.compute_p95_cost_per_assessment("a@example.com") is not None:
            failures.append("expected None p95 with no engine configured")
    finally:
        api_pricing._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_p95_cost_per_assessment — correct 95th-percentile value, "
          ">= the mean for an increasing distribution, no-data and no-engine degradation verified.")


def run_cost_by_document_length_bucket():
    failures = []
    original_get_engine = api_pricing._get_engine
    engine = _fresh_engine()
    api_pricing._get_engine = lambda: engine
    try:
        # short: input_tokens <= 2000; medium: <= 8000; long: > 8000.
        api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "irc_extraction", 500, 100)
        api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "irc_extraction", 5000, 500)
        api_pricing.log_api_usage("a@example.com", "claude-sonnet-4-6", "batch_extraction", 10000, 1000)
        # A non-assessment call site must not appear in any bucket.
        api_pricing.log_api_usage("a@example.com", "claude-haiku-4-5-20251001", "score_explanation_chat", 20000, 2000)

        buckets = api_pricing.compute_cost_by_document_length_bucket("a@example.com")
        for name in ("short", "medium", "long"):
            if name not in buckets:
                failures.append(f"expected bucket {name!r} present in output")
        if buckets.get("short", {}).get("count") != 1:
            failures.append(f"expected 1 row in 'short', got {buckets.get('short')}")
        if buckets.get("medium", {}).get("count") != 1:
            failures.append(f"expected 1 row in 'medium', got {buckets.get('medium')}")
        if buckets.get("long", {}).get("count") != 1:
            failures.append(f"expected 1 row in 'long' (batch_extraction, 10000 tokens), got {buckets.get('long')}")
        for name in ("short", "medium", "long"):
            if buckets[name]["mean_cost_pesewas"] is None or buckets[name]["mean_cost_pesewas"] <= 0:
                failures.append(f"expected a positive mean for non-empty bucket {name!r}")

        empty_buckets = api_pricing.compute_cost_by_document_length_bucket("nobody@example.com")
        for name in ("short", "medium", "long"):
            if empty_buckets.get(name) != {"mean_cost_pesewas": None, "count": 0}:
                failures.append(f"expected an empty-but-present {name!r} bucket for a no-data account, got {empty_buckets.get(name)}")

        api_pricing._get_engine = lambda: None
        if api_pricing.compute_cost_by_document_length_bucket("a@example.com") != {}:
            failures.append("expected {} with no engine configured")
    finally:
        api_pricing._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_cost_by_document_length_bucket — correct short/medium/long assignment by "
          "input_tokens, non-assessment call sites excluded, empty buckets stay present not omitted, "
          "no-engine degradation verified.")


def run_subscription_breakeven():
    failures = []

    # Explicit cost figure -- no DB involved, pure arithmetic.
    breakeven = api_pricing.compute_subscription_breakeven_assessments(5000, cost_per_assessment_pesewas=200.0)
    if breakeven != 25.0:
        failures.append(f"expected breakeven 5000/200=25.0, got {breakeven}")

    if api_pricing.compute_subscription_breakeven_assessments(5000, cost_per_assessment_pesewas=0.0) is not None:
        failures.append("expected None breakeven for a zero cost-per-assessment (would divide by zero)")

    original_get_engine = api_pricing._get_engine
    api_pricing._get_engine = lambda: None
    try:
        if api_pricing.compute_subscription_breakeven_assessments(5000) is not None:
            failures.append("expected None breakeven when falling back to compute_average_cost_per_assessment() with no engine")
    finally:
        api_pricing._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_subscription_breakeven_assessments — correct division, zero-cost and "
          "no-data-fallback both degrade to None rather than dividing by zero or guessing.")


if __name__ == "__main__":
    run_pricing_loads_and_computes()
    run_log_api_usage_and_average()
    run_p95_cost()
    run_cost_by_document_length_bucket()
    run_subscription_breakeven()
