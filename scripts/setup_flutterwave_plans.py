"""
scripts/setup_flutterwave_plans.py

One-time setup script: creates the nine Flutterwave Payment Plan objects
this app's subscription tiers need across USD/GBP/EUR (Professional
monthly, Professional annual, Agency monthly x 3 currencies) and prints
the resulting plan ids.

These are FIXED, periodically-reviewed regional prices, not a literal
daily FX conversion of GHS 50/200 -- Flutterwave Payment Plans, like
Paystack Plans, have an amount fixed at creation time, so a subscription
can't be re-priced from utils/exchange_rates.py's daily rate the way a
one-off (pay-per-use) charge can. The starting values below anchor to the
approximate GBP figures already shown in the shipped pricing copy
(~£3.50/mo Professional, ~£13/mo Agency) -- review/adjust before running
if you want different price points.

Run once:
    FLUTTERWAVE_SECRET_KEY=FLWSECK_... python scripts/setup_flutterwave_plans.py

Paste the nine printed ids into Streamlit secrets as:
    FLUTTERWAVE_PLAN_PROFESSIONAL_MONTHLY_USD / _GBP / _EUR
    FLUTTERWAVE_PLAN_PROFESSIONAL_ANNUAL_USD / _GBP / _EUR
    FLUTTERWAVE_PLAN_AGENCY_MONTHLY_USD / _GBP / _EUR

Re-running this script creates duplicate Payment Plan objects in
Flutterwave -- it is not idempotent and is not meant to run on every
deploy. To change a price, create a new plan and update the corresponding
secret rather than editing an existing plan's amount.
"""
from __future__ import annotations
import os
import sys

import requests

# amount is in major currency units (Flutterwave's convention -- see
# utils/flutterwave_payments.py's module docstring), matching how much a
# customer is actually charged per interval. interval spelling: VERIFY
# against current Flutterwave docs before running -- "monthly"/"yearly"
# are used here based on their documented payment-plan intervals.
PLANS = [
    # (label, amount, currency, interval, secret_name)
    ("Professional (monthly)", 4, "USD", "monthly", "FLUTTERWAVE_PLAN_PROFESSIONAL_MONTHLY_USD"),
    ("Professional (monthly)", 3.5, "GBP", "monthly", "FLUTTERWAVE_PLAN_PROFESSIONAL_MONTHLY_GBP"),
    ("Professional (monthly)", 4, "EUR", "monthly", "FLUTTERWAVE_PLAN_PROFESSIONAL_MONTHLY_EUR"),
    ("Professional (annual)", 40, "USD", "yearly", "FLUTTERWAVE_PLAN_PROFESSIONAL_ANNUAL_USD"),
    ("Professional (annual)", 35, "GBP", "yearly", "FLUTTERWAVE_PLAN_PROFESSIONAL_ANNUAL_GBP"),
    ("Professional (annual)", 40, "EUR", "yearly", "FLUTTERWAVE_PLAN_PROFESSIONAL_ANNUAL_EUR"),
    ("Agency (monthly)", 15, "USD", "monthly", "FLUTTERWAVE_PLAN_AGENCY_MONTHLY_USD"),
    ("Agency (monthly)", 13, "GBP", "monthly", "FLUTTERWAVE_PLAN_AGENCY_MONTHLY_GBP"),
    ("Agency (monthly)", 15, "EUR", "monthly", "FLUTTERWAVE_PLAN_AGENCY_MONTHLY_EUR"),
]


def main() -> int:
    key = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
    if not key:
        print("Set FLUTTERWAVE_SECRET_KEY in your environment before running this script.")
        return 1

    print("Creating Flutterwave payment plans...\n")
    results = {}
    for label, amount, currency, interval, secret_name in PLANS:
        try:
            resp = requests.post(
                "https://api.flutterwave.com/v3/payment-plans",
                json={
                    "amount": amount,
                    "name": f"ImpactProof {label} ({currency})",
                    "interval": interval,
                    "currency": currency,
                },
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            data = resp.json()
        except Exception as exc:
            print(f"  FAILED  {label} [{currency}]: {exc}")
            continue
        if data.get("status") != "success":
            print(f"  FAILED  {label} [{currency}]: {data.get('message', 'Flutterwave returned an error.')}")
            continue
        plan_id = str((data.get("data") or {}).get("id", ""))
        results[secret_name] = plan_id
        print(f"  OK      {label} [{currency}]: {plan_id}")

    if len(results) != len(PLANS):
        print("\nSome plans failed to create -- see above. Nothing is written automatically;"
              " paste the successful ids in manually and re-run for the rest if needed.")
        return 1

    print("\nPaste these into Streamlit secrets (.streamlit/secrets.toml locally, or"
          " Streamlit Cloud -> App settings -> Secrets in production):\n")
    for secret_name, plan_id in results.items():
        print(f'{secret_name} = "{plan_id}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
