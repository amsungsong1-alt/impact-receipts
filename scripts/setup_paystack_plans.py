"""
scripts/setup_paystack_plans.py

One-time setup script: creates the three Paystack Plan objects this app's
subscription tiers need (Professional monthly, Professional annual, Agency
monthly) and prints the resulting plan codes.

Run once:
    PAYSTACK_SECRET_KEY=sk_... python scripts/setup_paystack_plans.py

Paste the three printed codes into Streamlit secrets as:
    PAYSTACK_PLAN_PROFESSIONAL_MONTHLY
    PAYSTACK_PLAN_PROFESSIONAL_ANNUAL
    PAYSTACK_PLAN_AGENCY_MONTHLY

Re-running this script creates duplicate Plan objects in Paystack -- it is
not idempotent and is not meant to run on every deploy. Paystack plans are
immutable once created; to change a price, create a new plan and update the
corresponding secret rather than editing an existing plan_code's amount.
"""
from __future__ import annotations
import os
import sys

import requests

# amount is in pesewas (GHS x 100), matching PRICE_MONTHLY_GHS/PRICE_ANNUAL_GHS/
# PRICE_AGENCY_GHS in app.py. interval spelling: VERIFY against current Paystack
# docs before running -- "annually" is used here based on Paystack's documented
# plan intervals (daily/weekly/monthly/quarterly/biannually/annually).
PLANS = [
    # (label, amount_pesewas, interval, secret_name)
    ("Professional (monthly)", 5000, "monthly", "PAYSTACK_PLAN_PROFESSIONAL_MONTHLY"),
    ("Professional (annual)", 50000, "annually", "PAYSTACK_PLAN_PROFESSIONAL_ANNUAL"),
    ("Agency (monthly)", 20000, "monthly", "PAYSTACK_PLAN_AGENCY_MONTHLY"),
]


def main() -> int:
    key = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not key:
        print("Set PAYSTACK_SECRET_KEY in your environment before running this script.")
        return 1

    print("Creating Paystack plans...\n")
    results = {}
    for label, amount, interval, secret_name in PLANS:
        try:
            resp = requests.post(
                "https://api.paystack.co/plan",
                json={
                    "name": f"ImpactProof {label}",
                    "amount": amount,
                    "interval": interval,
                    "currency": "GHS",
                },
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            data = resp.json()
        except Exception as exc:
            print(f"  FAILED  {label}: {exc}")
            continue
        if not data.get("status"):
            print(f"  FAILED  {label}: {data.get('message', 'Paystack returned an error.')}")
            continue
        plan_code = data["data"].get("plan_code", "")
        results[secret_name] = plan_code
        print(f"  OK      {label}: {plan_code}")

    if len(results) != len(PLANS):
        print("\nSome plans failed to create -- see above. Nothing is written automatically;"
              " paste the successful codes in manually and re-run for the rest if needed.")
        return 1

    print("\nPaste these into Streamlit secrets (.streamlit/secrets.toml locally, or"
          " Streamlit Cloud -> App settings -> Secrets in production):\n")
    for secret_name, plan_code in results.items():
        print(f'{secret_name} = "{plan_code}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
