"""
scripts/pricing_model.py — Laudon Ch.10, C2/C6: pricing-scenario comparison.

A scenario-modeling tool, not a UI, and NEVER a mechanism for changing a live
price. It reads:
  - real, measured cost data from utils/api_pricing.py (falls back to a
    clearly-labeled SYNTHETIC EXAMPLE distribution if SUPABASE_DB_URL isn't
    reachable or there's no data yet -- never silently presents a guess as
    real);
  - pricing ASSUMPTIONS (never live prices) from knowledge/cltv_assumptions.yaml.

It never imports app.py (which would execute the whole Streamlit page) and
never touches PRICE_PER_CHECK_GHS/PRICE_MONTHLY_GHS/PRICE_AGENCY_GHS/
PRICE_ANNUAL_GHS or any Paystack Plan object -- per Laudon Ch.10's explicit
brief: "Do not ship a pricing change from this prompt." This script produces
numbers and a recommendation with its reasoning; a pricing DECISION is made
by a person, with this output in front of them, separately.

Run:
    python scripts/pricing_model.py
"""
from __future__ import annotations
import os

import yaml

_ASSUMPTIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge", "cltv_assumptions.yaml",
)

# Used only when no real cost data is reachable -- clearly labeled wherever
# it's printed, never presented as a measurement.
_SYNTHETIC_COST_PER_ASSESSMENT_PESEWAS = 150.0
_SYNTHETIC_USAGE_DISTRIBUTION = [1, 2, 3, 3, 4, 6, 10]  # assessments/cycle, illustrative only


def load_assumptions() -> dict:
    """Hot-reload, same convention as every other knowledge/*.yaml consumer
    in this codebase. Returns {} on a missing/malformed file rather than
    raising."""
    if not os.path.isfile(_ASSUMPTIONS_PATH):
        return {}
    try:
        with open(_ASSUMPTIONS_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def get_real_or_synthetic_cost_per_assessment() -> tuple[float, bool]:
    """Returns (cost_pesewas, is_real). Tries the real, measured mean cost
    from utils/api_pricing.py first; falls back to the labeled synthetic
    constant only if no engine is configured or there's no data yet."""
    try:
        from utils.api_pricing import compute_average_cost_per_assessment
        real = compute_average_cost_per_assessment()
        if real:
            return real, True
    except Exception:
        pass
    return _SYNTHETIC_COST_PER_ASSESSMENT_PESEWAS, False


def _gross_margin_pct(revenue: float, cost: float) -> float | None:
    if revenue <= 0:
        return None
    return round(100.0 * (revenue - cost) / revenue, 1)


def model_current_split(assumptions: dict, cost_per_assessment: float, assessments_per_cycle: float) -> dict:
    """The live model today: blended pay-per-use + subscription revenue,
    same formula utils/crm.py::compute_cltv() already uses -- reproduced
    here (not imported) since this script must never depend on
    Streamlit-adjacent app state, matching evaluator.py's own UI-free
    discipline."""
    price_mix = assumptions.get("price_mix", {})
    price_ghs = assumptions.get("price_ghs", {})
    per_use_share = price_mix.get("per_use_share", 0.6)
    subscription_share = price_mix.get("subscription_share", 0.4)
    per_use_price_pesewas = price_ghs.get("per_use", 5) * 100
    monthly_price_pesewas = price_ghs.get("monthly", 50) * 100

    revenue = (
        per_use_share * (assessments_per_cycle * per_use_price_pesewas)
        + subscription_share * monthly_price_pesewas
    )
    cost = assessments_per_cycle * cost_per_assessment
    return {
        "name": "Current split (pay-per-use + subscription, current mix)",
        "revenue_pesewas": round(revenue, 2),
        "cost_pesewas": round(cost, 2),
        "gross_margin_pct": _gross_margin_pct(revenue, cost),
        "behavior_incentivized": (
            "Rewards infrequent users staying pay-per-use and frequent users converting to "
            "subscription -- no cap, so a subscriber who runs far more than "
            f"{assessments_per_cycle:.0f}/cycle silently erodes margin with no visibility to us."
        ),
    }


def model_subscription_fair_use(assumptions: dict, cost_per_assessment: float, assessments_per_cycle: float) -> dict:
    fair_use = assumptions.get("subscription_fair_use", {})
    price_ghs = assumptions.get("price_ghs", {})
    monthly_price_pesewas = price_ghs.get("monthly", 50) * 100
    included = fair_use.get("included_assessments_per_month", 15)
    overage_price_pesewas = fair_use.get("overage_price_ghs", 3) * 100

    overage_units = max(0, assessments_per_cycle - included)
    revenue = monthly_price_pesewas + overage_units * overage_price_pesewas
    cost = assessments_per_cycle * cost_per_assessment
    return {
        "name": f"Subscription + fair-use cap ({included}/mo) + overage (GHS {overage_price_pesewas/100:.2f}/extra)",
        "revenue_pesewas": round(revenue, 2),
        "cost_pesewas": round(cost, 2),
        "gross_margin_pct": _gross_margin_pct(revenue, cost),
        "behavior_incentivized": (
            "Caps our downside on a heavy user automatically -- margin can no longer silently "
            "go negative past the cap. Mild disincentive to run marginal/exploratory checks "
            "once near the cap, which cuts against the product's own 'check more, catch "
            "issues earlier' pitch -- worth watching for reduced usage near the cap boundary."
        ),
    }


def model_credit_packs(assumptions: dict, cost_per_assessment: float, assessments_per_cycle: float) -> dict:
    pack = assumptions.get("credit_pack", {})
    pack_assessments = pack.get("assessments", 10)
    pack_price_pesewas = pack.get("price_ghs", 40) * 100
    effective_price_per_assessment = pack_price_pesewas / pack_assessments if pack_assessments else 0

    revenue = assessments_per_cycle * effective_price_per_assessment
    cost = assessments_per_cycle * cost_per_assessment
    return {
        "name": f"Credit packs ({pack_assessments} for GHS {pack_price_pesewas/100:.2f})",
        "revenue_pesewas": round(revenue, 2),
        "cost_pesewas": round(cost, 2),
        "gross_margin_pct": _gross_margin_pct(revenue, cost),
        "behavior_incentivized": (
            f"Effective price GHS {effective_price_per_assessment/100:.2f}/assessment, below the "
            "GHS 5.00 per-use price -- rewards buying in bulk upfront (better cash flow for us) "
            "at a real discount to the customer, without the open-ended commitment of a "
            "subscription. No usage cap, so the same unbounded-heavy-user risk as the current "
            "split remains, just at a lower per-unit margin."
        ),
    }


def model_limited_free_tier(cost_per_assessment: float, cached_demo: bool) -> dict:
    """1 assessment per organisation, ever -- either a real scored assessment
    (costs cost_per_assessment) or a cached demo-mode run against a fixed
    sample document (genuinely zero marginal cost, since nothing new is
    computed). Revenue is always 0 -- this is a pure top-of-funnel/
    acquisition scenario, not a revenue line."""
    cost = 0.0 if cached_demo else cost_per_assessment
    return {
        "name": f"Limited free tier (1/org lifetime, {'cached demo' if cached_demo else 'live scored'})",
        "revenue_pesewas": 0.0,
        "cost_pesewas": round(cost, 2),
        "gross_margin_pct": None,  # revenue is 0 by design -- gross margin % is undefined, not "bad"
        "behavior_incentivized": (
            "Zero marginal cost, provably capped by construction (a cached demo has no new "
            "API call at all)." if cached_demo else
            "Real marginal cost per organisation acquired -- bounded (exactly 1x, never "
            "recurring), but not zero. Provable ceiling = cost_per_assessment × org count, "
            "unlike the current 3-per-ACCOUNT model where one org can create unlimited "
            "accounts to keep re-triggering free checks (a real gap in today's design this "
            "scenario would close, worth noting even though this script recommends nothing)."
        ),
    }


def model_concessional_tiers(assumptions: dict, cost_per_assessment: float, assessments_per_cycle: float) -> list[dict]:
    """Laudon Ch.10, C6: differential pricing by organisational capacity.
    Applies each concessional_tiers[].discount_pct to the Professional
    monthly price and reports margin per bucket -- output only, no
    enforcement, no price change."""
    price_ghs = assumptions.get("price_ghs", {})
    monthly_price_pesewas = price_ghs.get("monthly", 50) * 100
    tiers = assumptions.get("concessional_tiers", [])
    results = []
    for tier in tiers:
        org_type = tier.get("org_type", "unknown")
        discount_pct = tier.get("discount_pct", 0)
        discounted_price = monthly_price_pesewas * (1 - discount_pct / 100.0)
        cost = assessments_per_cycle * cost_per_assessment
        results.append({
            "name": f"Concessional tier: {org_type} ({discount_pct}% off Professional)",
            "revenue_pesewas": round(discounted_price, 2),
            "cost_pesewas": round(cost, 2),
            "gross_margin_pct": _gross_margin_pct(discounted_price, cost),
            "behavior_incentivized": (
                f"Effective price GHS {discounted_price/100:.2f}/mo for a self-declared "
                f"'{org_type}' account."
            ),
        })
    return results


def check_cannibalization(concessional_results: list[dict], assumptions: dict, cost_per_assessment: float, assessments_per_cycle: float) -> list[str]:
    """Flags whether the cheapest concessional tier's effective per-
    assessment economics undercut the Agency tier enough to give a real
    Agency-sized account incentive to self-declare into a cheaper org_type
    bucket instead. Output only -- no enforcement, no eligibility
    verification is proposed or built here (that would require documentation
    review, out of scope for a pricing-scenario script)."""
    price_ghs = assumptions.get("price_ghs", {})
    agency_price_pesewas = price_ghs.get("agency", 200) * 100
    agency_effective_per_assessment = (
        agency_price_pesewas / assessments_per_cycle if assessments_per_cycle else None
    )

    warnings = []
    if not concessional_results or agency_effective_per_assessment is None:
        return warnings
    cheapest = min(concessional_results, key=lambda r: r["revenue_pesewas"])
    cheapest_effective_per_assessment = (
        cheapest["revenue_pesewas"] / assessments_per_cycle if assessments_per_cycle else None
    )
    if cheapest_effective_per_assessment is not None and cheapest_effective_per_assessment < agency_effective_per_assessment:
        warnings.append(
            f"{cheapest['name']} is effectively cheaper per assessment "
            f"(GHS {cheapest_effective_per_assessment/100:.2f}) than Agency "
            f"(GHS {agency_effective_per_assessment/100:.2f}) at "
            f"{assessments_per_cycle:.0f} assessments/cycle -- a real Agency-sized account "
            "has a financial incentive to self-declare into the concessional bucket instead. "
            "Any concessional pricing needs a real eligibility check (declared budget/size "
            "verification), not a self-reported dropdown, before this is safe to launch."
        )
    else:
        warnings.append(
            "No cannibalization risk detected at the modeled usage rate -- the cheapest "
            "concessional tier remains more expensive per assessment than Agency."
        )
    return warnings


def _print_scenario(scenario: dict) -> None:
    margin = scenario["gross_margin_pct"]
    margin_str = f"{margin}%" if margin is not None else "n/a (zero revenue by design)"
    print(f"\n  {scenario['name']}")
    print(f"    Revenue: GHS {scenario['revenue_pesewas']/100:.2f}   "
          f"Cost: GHS {scenario['cost_pesewas']/100:.2f}   Gross margin: {margin_str}")
    print(f"    Behavior incentivized: {scenario['behavior_incentivized']}")


def main() -> int:
    assumptions = load_assumptions()
    cost_per_assessment, is_real = get_real_or_synthetic_cost_per_assessment()
    assessments_per_cycle = assumptions.get("expected_assessments_per_cycle", 3)

    print("=" * 78)
    print("ImpactProof pricing scenario model (Laudon Ch.10, C2/C6)")
    print("This is analysis output only -- it changes nothing. See docs/unit_economics.md")
    print("for the measured cost this model is built on, and PRICING DECISIONS are made by")
    print("a person with this output in front of them, never automatically from this script.")
    print("=" * 78)

    if is_real:
        print(f"\nCost per assessment: GHS {cost_per_assessment/100:.2f} (REAL, from api_usage_log)")
    else:
        print(f"\nCost per assessment: GHS {cost_per_assessment/100:.2f} "
              "*** SYNTHETIC EXAMPLE DATA -- no real cost data reachable ***")
    print(f"Modeled usage rate: {assessments_per_cycle:.0f} assessments/cycle "
          "(from knowledge/cltv_assumptions.yaml's expected_assessments_per_cycle)")

    print("\n--- C2: baseline pricing scenarios ---")
    for scenario in (
        model_current_split(assumptions, cost_per_assessment, assessments_per_cycle),
        model_subscription_fair_use(assumptions, cost_per_assessment, assessments_per_cycle),
        model_credit_packs(assumptions, cost_per_assessment, assessments_per_cycle),
        model_limited_free_tier(cost_per_assessment, cached_demo=True),
        model_limited_free_tier(cost_per_assessment, cached_demo=False),
    ):
        _print_scenario(scenario)

    print("\n--- C6: differential pricing by organisational capacity ---")
    concessional_results = model_concessional_tiers(assumptions, cost_per_assessment, assessments_per_cycle)
    for scenario in concessional_results:
        _print_scenario(scenario)

    print("\n--- C6: cannibalization check ---")
    for warning in check_cannibalization(concessional_results, assumptions, cost_per_assessment, assessments_per_cycle):
        print(f"  {warning}")

    print("\n" + "=" * 78)
    print("No price constant or Paystack Plan object was read or modified by this script.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
