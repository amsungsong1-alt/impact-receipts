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


if __name__ == "__main__":
    run_pricing_loads_and_computes()
    run_log_api_usage_and_average()
