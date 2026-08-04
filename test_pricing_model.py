"""
test_pricing_model.py — golden tests for scripts/pricing_model.py (Laudon
Ch.10, C2/C6). Pure arithmetic over fixed inputs -- no DB, no network, no
dependency on knowledge/cltv_assumptions.yaml's current contents (each test
supplies its own explicit assumptions dict so a future edit to that file
can't silently break this suite). Run with: python test_pricing_model.py
"""

import scripts.pricing_model as pm


_ASSUMPTIONS = {
    "price_mix": {"per_use_share": 0.6, "subscription_share": 0.4},
    "price_ghs": {"per_use": 5, "monthly": 50, "annual": 500, "agency": 200},
    "credit_pack": {"assessments": 10, "price_ghs": 40},
    "subscription_fair_use": {"included_assessments_per_month": 15, "overage_price_ghs": 3},
    "concessional_tiers": [
        {"org_type": "CBO/Government", "discount_pct": 60},
        {"org_type": "National NGO", "discount_pct": 30},
        {"org_type": "International NGO (INGO)", "discount_pct": 0},
    ],
}


def run_current_split():
    failures = []
    scenario = pm.model_current_split(_ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=3)
    # revenue = 0.6*(3*500) + 0.4*5000 = 900 + 2000 = 2900 pesewas
    if scenario["revenue_pesewas"] != 2900.0:
        failures.append(f"expected revenue 2900.0, got {scenario['revenue_pesewas']}")
    if scenario["cost_pesewas"] != 450.0:
        failures.append(f"expected cost 450.0, got {scenario['cost_pesewas']}")
    if scenario["gross_margin_pct"] != round(100 * (2900 - 450) / 2900, 1):
        failures.append(f"gross margin computed incorrectly: {scenario['gross_margin_pct']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: model_current_split — correct blended revenue/cost/margin arithmetic.")


def run_subscription_fair_use():
    failures = []
    # Usage below the cap -- no overage charged.
    below_cap = pm.model_subscription_fair_use(_ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=10)
    if below_cap["revenue_pesewas"] != 5000.0:
        failures.append(f"expected flat monthly revenue 5000.0 below the cap, got {below_cap['revenue_pesewas']}")

    # Usage above the cap -- overage charged for the excess only.
    above_cap = pm.model_subscription_fair_use(_ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=20)
    # 20 - 15 = 5 overage units * 300 pesewas = 1500, + 5000 base = 6500
    if above_cap["revenue_pesewas"] != 6500.0:
        failures.append(f"expected revenue 6500.0 (5000 base + 5*300 overage), got {above_cap['revenue_pesewas']}")
    if above_cap["cost_pesewas"] != 3000.0:
        failures.append(f"expected cost 3000.0 (20*150), got {above_cap['cost_pesewas']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: model_subscription_fair_use — flat revenue below the cap, correct overage billing above it.")


def run_credit_packs():
    failures = []
    scenario = pm.model_credit_packs(_ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=3)
    # effective price = 4000/10 = 400 pesewas/assessment; revenue = 3*400 = 1200
    if scenario["revenue_pesewas"] != 1200.0:
        failures.append(f"expected revenue 1200.0 (3 * GHS4.00 effective), got {scenario['revenue_pesewas']}")
    if "4.00" not in scenario["behavior_incentivized"]:
        failures.append("expected the effective per-assessment price (GHS 4.00) to appear in the behavior note")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: model_credit_packs — correct effective per-assessment price and revenue.")


def run_limited_free_tier():
    failures = []
    cached = pm.model_limited_free_tier(cost_per_assessment=150.0, cached_demo=True)
    if cached["cost_pesewas"] != 0.0:
        failures.append(f"a cached demo must have zero cost, got {cached['cost_pesewas']}")
    if cached["revenue_pesewas"] != 0.0:
        failures.append("free tier revenue must always be 0")
    if cached["gross_margin_pct"] is not None:
        failures.append("gross margin on zero revenue must be None, not a computed/misleading percentage")

    live = pm.model_limited_free_tier(cost_per_assessment=150.0, cached_demo=False)
    if live["cost_pesewas"] != 150.0:
        failures.append(f"a live-scored free assessment must cost exactly cost_per_assessment, got {live['cost_pesewas']}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: model_limited_free_tier — cached demo is genuinely zero-cost, live-scored has a real "
          "bounded cost, gross margin never fabricated for zero revenue.")


def run_concessional_tiers_and_cannibalization():
    failures = []
    results = pm.model_concessional_tiers(_ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=3)
    if len(results) != 3:
        failures.append(f"expected 3 concessional tier results, got {len(results)}")
    cbo = next((r for r in results if "CBO/Government" in r["name"]), None)
    if cbo is None or cbo["revenue_pesewas"] != 2000.0:  # 5000 * (1 - 0.6)
        failures.append(f"expected CBO/Government tier revenue 2000.0 (40% of monthly), got {cbo}")

    # Cannibalization: at 3 assessments/cycle, CBO/Government's discounted
    # price (GHS 20/mo = GHS 6.67/assessment) is far cheaper per-assessment
    # than Agency (GHS 200/mo = GHS 66.67/assessment) -- must be flagged.
    warnings = pm.check_cannibalization(results, _ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=3)
    if not any("incentive to self-declare" in w for w in warnings):
        failures.append(f"expected a cannibalization warning for the CBO/Government tier undercutting Agency, got {warnings}")

    # No concessional tiers -> no warnings, never an error.
    if pm.check_cannibalization([], _ASSUMPTIONS, cost_per_assessment=150.0, assessments_per_cycle=3) != []:
        failures.append("expected no warnings when there are no concessional tiers to check")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: model_concessional_tiers/check_cannibalization — correct discounted pricing per tier, "
          "and a genuine cannibalization risk is actually detected, not just structurally present.")


def run_synthetic_fallback_never_raises():
    """get_real_or_synthetic_cost_per_assessment() must degrade to the
    labeled synthetic constant, never raise, when no DB is reachable (the
    default state for this test run)."""
    failures = []
    cost, is_real = pm.get_real_or_synthetic_cost_per_assessment()
    if cost <= 0:
        failures.append(f"expected a positive fallback cost, got {cost}")
    # is_real may legitimately be True if this happens to run somewhere with
    # SUPABASE_DB_URL configured and real data present -- only assert the
    # function never raises and always returns a positive number either way.

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: get_real_or_synthetic_cost_per_assessment — never raises, always returns a positive cost.")


def run_main_never_raises():
    """The full script's main() must run end-to-end without raising, using
    whatever real/synthetic data is available in this environment."""
    failures = []
    try:
        exit_code = pm.main()
    except Exception as e:
        failures.append(f"main() must never raise, got {e!r}")
    else:
        if exit_code != 0:
            failures.append(f"expected exit code 0, got {exit_code}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: main() runs end-to-end without raising.")


if __name__ == "__main__":
    run_current_split()
    run_subscription_fair_use()
    run_credit_packs()
    run_limited_free_tier()
    run_concessional_tiers_and_cannibalization()
    run_synthetic_fallback_never_raises()
    run_main_never_raises()
