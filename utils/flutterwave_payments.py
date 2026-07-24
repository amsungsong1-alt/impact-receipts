"""
flutterwave_payments.py — Flutterwave Standard Checkout integration for
USD/GBP/EUR. Paystack (utils/paystack.py) remains the sole processor for
GHS, and the GHS-fallback-charge path for NGN/KES/ZAR (see app.py's
_checkout_route_for_currency()) -- Flutterwave never touches GHS, since
that's already covered natively by Paystack.

Flutterwave was chosen over Stripe for this because Stripe requires the
merchant business itself to be legally incorporated in one of its ~46
supported countries, which does not include Ghana -- Flutterwave supports
Ghana-registered businesses directly and can settle USD/GBP/EUR.

Uses plain `requests` calls (like utils/paystack.py) rather than a vendor
SDK -- Flutterwave's v3 REST API is a similarly simple JSON API, and both
share the same "Ghana-region payments API" lineage/shape.

IMPORTANT: Flutterwave's `amount` field is in MAJOR currency units (e.g.
"5.00" for $5.00), NOT minor/subunits like Stripe's cents or Paystack's
pesewas/kobo -- this module's public functions still take
amount_minor_units (matching the other two processors' contract so
app.py can treat all three interchangeably) and divide by 100 internally.

One-off (pay-per-use) checkouts charge the exact daily-FX-converted
amount computed by utils/exchange_rates.py -- no pre-created object
needed. Subscriptions (monthly/annual/agency) require a pre-created
Flutterwave "Payment Plan" (like Paystack's Plan objects -- see
scripts/setup_flutterwave_plans.py), since a Payment Plan's amount is
fixed at creation time and Flutterwave has no inline-recurring-price
equivalent of Stripe's price_data. Subscription prices are therefore
fixed, periodically-reviewed regional prices, not the literal daily rate.

All secrets via st.secrets / environment variables, same dual-source
pattern as utils/paystack.py.
"""
from __future__ import annotations
import hmac
import os
import uuid

import requests

_PLAN_LABELS = {
    "per_use": "ImpactProof — Pay-per-check",
    "monthly": "ImpactProof Professional (monthly)",
    "annual": "ImpactProof Professional (annual)",
    "agency": "ImpactProof Agency (monthly)",
}


def _secret_key() -> str:
    env_val = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
    try:
        import streamlit as st
        try:
            val = st.secrets["FLUTTERWAVE_SECRET_KEY"]
            if val:
                return val
        except KeyError:
            pass
        except Exception:
            pass
        return st.secrets.get("FLUTTERWAVE_SECRET_KEY") or env_val
    except Exception:
        return env_val


def _webhook_secret_hash() -> str:
    env_val = os.environ.get("FLUTTERWAVE_WEBHOOK_SECRET_HASH", "")
    try:
        import streamlit as st
        return st.secrets.get("FLUTTERWAVE_WEBHOOK_SECRET_HASH") or env_val
    except Exception:
        return env_val


def _base_url() -> str:
    env_val = os.environ.get("APP_BASE_URL", "")
    try:
        import streamlit as st
        configured = st.secrets.get("APP_BASE_URL") or env_val
        if configured:
            return configured.rstrip("/")
        try:
            host = st.context.headers.get("Host") or st.context.headers.get("host", "")
            if host:
                return f"https://{host}"
        except Exception:
            pass
    except Exception:
        if env_val:
            return env_val.rstrip("/")
    return "https://impact-integrity-diagnostic.streamlit.app"


_last_payment_error: str = ""


def last_payment_error() -> str:
    return _last_payment_error


def create_checkout_session(email: str, amount_minor_units: int, currency: str,
                             plan: str = "per_use", mode: str = "payment",
                             payment_plan_id: str = "") -> str:
    """
    POST to Flutterwave /v3/payments (Standard Checkout).
    mode="payment" for a one-off (pay-per-use) charge of the exact
    daily-FX-converted amount. mode="subscription" requires payment_plan_id
    (a Flutterwave Payment Plan id from scripts/setup_flutterwave_plans.py
    -- see that script and app.py's _flutterwave_plan_id() for how it's
    resolved per currency/tier); the amount charged is then whatever that
    Payment Plan was created with, not amount_minor_units.
    Returns the hosted checkout link (redirect user here), or "" on
    failure -- same contract as utils.paystack.initialize_payment(), so
    app.py can treat all three processors interchangeably.
    Call last_payment_error() after a failure to get the reason.
    """
    global _last_payment_error
    _last_payment_error = ""
    key = _secret_key()
    if not key:
        _last_payment_error = "FLUTTERWAVE_SECRET_KEY not configured."
        return ""
    if currency not in ("USD", "GBP", "EUR"):
        _last_payment_error = f"Flutterwave is not configured for currency {currency}."
        return ""
    if mode == "subscription" and not payment_plan_id:
        _last_payment_error = f"No Flutterwave payment plan configured for '{plan}' in {currency}."
        return ""

    tx_ref = f"ip_{uuid.uuid4().hex}"
    base_url = _base_url()
    payload = {
        "tx_ref": tx_ref,
        "amount": round(amount_minor_units / 100, 2),
        "currency": currency,
        "redirect_url": base_url,
        "customer": {"email": email},
        "customizations": {"title": _PLAN_LABELS.get(plan, "ImpactProof")},
        "meta": {"plan": plan},
    }
    if payment_plan_id:
        payload["payment_plan"] = payment_plan_id
    try:
        r = requests.post(
            "https://api.flutterwave.com/v3/payments",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        if data.get("status") == "success":
            return (data.get("data") or {}).get("link", "")
        _last_payment_error = data.get("message", "Flutterwave returned an error.")
        return ""
    except Exception as exc:
        _last_payment_error = str(exc)
        return ""


def verify_transaction(transaction_id: str) -> dict:
    """
    GET /v3/transactions/{id}/verify -- reconciliation/redirect-return
    read-back, mirrors utils.paystack.verify_payment()'s role. `id` is the
    numeric transaction_id Flutterwave appends to the redirect_url on
    return. Returns {"status": "success"|"failed"|"error", "amount": int,
    "currency": str, "plan": str, "email": str}.
    """
    key = _secret_key()
    if not key or not transaction_id:
        return {"status": "error", "amount": 0, "currency": "", "plan": "", "email": ""}
    try:
        r = requests.get(
            f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        tx = data.get("data") or {}
        if data.get("status") == "success" and tx.get("status") == "successful":
            meta = tx.get("meta") or {}
            customer = tx.get("customer") or {}
            return {
                "status": "success",
                "amount": round((tx.get("amount") or 0) * 100),
                "currency": (tx.get("currency") or "").upper(),
                "plan": meta.get("plan", "per_use"),
                "email": customer.get("email", ""),
            }
        return {"status": "failed", "amount": 0, "currency": "", "plan": "", "email": ""}
    except Exception:
        return {"status": "error", "amount": 0, "currency": "", "plan": "", "email": ""}


def verify_webhook_signature(signature_header: str, secret_hash: str = "") -> bool:
    """
    Flutterwave's webhook scheme is simpler than Paystack/Stripe's: no
    HMAC-over-body on the integrator's side, just a constant-time string
    match between the incoming verif-hash header and the secret hash
    string you configured in the Flutterwave dashboard's webhook settings.
    The production webhook receiver is the Deno Edge Function
    (supabase/functions/flutterwave-webhook) -- an independent
    implementation of this same check; this copy exists for a future
    Python-side reconciliation/replay-debug tool.
    """
    secret = secret_hash or _webhook_secret_hash()
    if not secret or not signature_header:
        return False
    return hmac.compare_digest(secret, signature_header)
