"""
stripe_payments.py — Stripe Checkout integration for USD/GBP/EUR only.
Paystack (utils/paystack.py) remains the sole processor for GHS, and the
GHS-fallback-charge path for NGN/KES/ZAR (see app.py's
_checkout_route_for_currency()) -- Stripe never touches African currencies,
since ImpactProof's Paystack merchant account is Ghana-only.

Uses the official `stripe` SDK (unlike utils/paystack.py's hand-rolled
`requests` calls) -- a deliberate deviation, not an oversight: Stripe's SDK
handles idempotency/retries/Checkout-Session construction more safely than
hand-rolled JSON, and this is the standard way to integrate Stripe.

Uses Checkout Sessions with inline `price_data` rather than pre-created
Price objects, because the FX-derived USD/GBP/EUR amount changes daily
(utils/exchange_rates.py) and Stripe Price objects, like Paystack Plans,
are immutable once created -- inline price_data lets each session charge
the amount computed at request time, for both one-off and recurring
purchases, with no Price-object matrix to maintain.

All secrets via st.secrets / environment variables, same dual-source
pattern as utils/paystack.py.
"""
from __future__ import annotations
import os

_PLAN_LABELS = {
    "per_use": "ImpactProof — Pay-per-check",
    "monthly": "ImpactProof Professional (monthly)",
    "annual": "ImpactProof Professional (annual)",
    "agency": "ImpactProof Agency (monthly)",
}

_RECURRING_INTERVAL = {
    "monthly": "month",
    "annual": "year",
    "agency": "month",
}


def _secret_key() -> str:
    env_val = os.environ.get("STRIPE_SECRET_KEY", "")
    try:
        import streamlit as st
        try:
            val = st.secrets["STRIPE_SECRET_KEY"]
            if val:
                return val
        except KeyError:
            pass
        except Exception:
            pass
        return st.secrets.get("STRIPE_SECRET_KEY") or env_val
    except Exception:
        return env_val


def _webhook_signing_secret() -> str:
    env_val = os.environ.get("STRIPE_WEBHOOK_SIGNING_SECRET", "")
    try:
        import streamlit as st
        return st.secrets.get("STRIPE_WEBHOOK_SIGNING_SECRET") or env_val
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
                             plan: str = "per_use", mode: str = "payment") -> str:
    """
    Creates a Stripe Checkout Session using inline price_data (no
    pre-created Price object needed). mode="payment" for a one-off
    (pay-per-use); mode="subscription" for monthly/annual/agency, in which
    case `plan` must be a key in _RECURRING_INTERVAL.
    Returns the Checkout Session's redirect url, or "" on failure -- same
    contract as utils.paystack.initialize_payment(), so app.py can treat
    both processors interchangeably.
    Call last_payment_error() after a failure to get the reason.
    """
    global _last_payment_error
    _last_payment_error = ""
    key = _secret_key()
    if not key:
        _last_payment_error = "STRIPE_SECRET_KEY not configured."
        return ""
    if currency not in ("USD", "GBP", "EUR"):
        _last_payment_error = f"Stripe does not support currency {currency}."
        return ""
    try:
        import stripe
        stripe.api_key = key

        price_data = {
            "currency": currency.lower(),
            "unit_amount": amount_minor_units,
            "product_data": {"name": _PLAN_LABELS.get(plan, "ImpactProof")},
        }
        if mode == "subscription":
            interval = _RECURRING_INTERVAL.get(plan)
            if not interval:
                _last_payment_error = f"Plan '{plan}' is not a recurring plan."
                return ""
            price_data["recurring"] = {"interval": interval}

        base_url = _base_url()
        session = stripe.checkout.Session.create(
            mode=mode,
            customer_email=email,
            line_items=[{"price_data": price_data, "quantity": 1}],
            success_url=f"{base_url}?stripe_session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=base_url,
            metadata={"plan": plan},
        )
        return session.url or ""
    except Exception as exc:
        _last_payment_error = str(exc)
        return ""


def get_checkout_session(session_id: str) -> dict:
    """
    Reconciliation/redirect-return read-back, mirrors
    utils.paystack.verify_payment()'s role for the redirect-return flow.
    Returns {"status": "success"|"failed"|"error", "amount": int,
    "currency": str, "plan": str, "email": str}.
    """
    key = _secret_key()
    if not key or not session_id:
        return {"status": "error", "amount": 0, "currency": "", "plan": "", "email": ""}
    try:
        import stripe
        stripe.api_key = key
        session = stripe.checkout.Session.retrieve(session_id)
        if session.get("payment_status") == "paid" or session.get("status") == "complete":
            return {
                "status": "success",
                "amount": session.get("amount_total", 0),
                "currency": (session.get("currency") or "").upper(),
                "plan": (session.get("metadata") or {}).get("plan", "per_use"),
                "email": session.get("customer_email", ""),
            }
        return {"status": "failed", "amount": 0, "currency": "", "plan": "", "email": ""}
    except Exception:
        return {"status": "error", "amount": 0, "currency": "", "plan": "", "email": ""}


def verify_webhook_signature(raw_body: bytes, signature_header: str, endpoint_secret: str = "") -> bool:
    """
    Wraps stripe.Webhook.construct_event() (SDK-provided verification,
    unlike Paystack's hand-rolled HMAC). Returns True/False rather than
    raising, to match utils.paystack.verify_webhook_signature()'s
    boolean-return convention. The production webhook receiver is the Deno
    Edge Function (supabase/functions/stripe-webhook) -- an independent
    implementation using Stripe's Deno-compatible SDK; this copy exists for
    a future Python-side reconciliation/replay-debug tool.
    """
    secret = endpoint_secret or _webhook_signing_secret()
    if not secret or not signature_header:
        return False
    try:
        import stripe
        stripe.Webhook.construct_event(raw_body, signature_header, secret)
        return True
    except Exception:
        return False
