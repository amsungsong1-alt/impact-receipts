"""
Paystack payment integration — initialize + verify transactions.
Supports MTN MoMo, Telecel/AirtelTigo Money, and bank cards (Ghana).
All secrets via st.secrets / environment variables.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import requests


def _secret_key() -> str:
    env_val = os.environ.get("PAYSTACK_SECRET_KEY", "")
    try:
        import streamlit as st
        try:
            val = st.secrets["PAYSTACK_SECRET_KEY"]
            if val:
                return val
        except KeyError:
            pass
        except Exception:
            pass
        return st.secrets.get("PAYSTACK_SECRET_KEY") or env_val
    except Exception:
        return env_val


def _base_url() -> str:
    # Priority 1: explicit override in st.secrets or environment
    env_val = os.environ.get("APP_BASE_URL", "")
    try:
        import streamlit as st
        configured = st.secrets.get("APP_BASE_URL") or env_val
        if configured:
            return configured.rstrip("/")

        # Priority 2: detect live URL from request headers (Streamlit 1.30+)
        try:
            host = st.context.headers.get("Host") or st.context.headers.get("host", "")
            proto = "https"  # Streamlit Cloud always serves HTTPS
            if host:
                return f"{proto}://{host}"
        except Exception:
            pass

        # Priority 3: construct from Streamlit server options
        try:
            base_path = (st.get_option("server.baseUrlPath") or "").strip("/")
            port = st.get_option("server.port") or 8501
            if base_path:
                return f"http://localhost:{port}/{base_path}"
        except Exception:
            pass

    except Exception:
        if env_val:
            return env_val.rstrip("/")

    # Final fallback — set APP_BASE_URL in Streamlit secrets to fix payment callbacks
    return "https://impact-integrity-diagnostic.streamlit.app"


_last_payment_error: str = ""


def last_payment_error() -> str:
    return _last_payment_error


def initialize_payment(email: str, amount_kobo: int, plan: str = "per_use") -> str:
    """
    POST to Paystack /transaction/initialize.
    Returns authorization_url (redirect user here) or empty string on failure.
    amount_kobo: amount in Ghana Pesewas (100 pesewas = GHS 1.00).
    Call last_payment_error() after a failure to get the reason.
    """
    global _last_payment_error
    _last_payment_error = ""
    key = _secret_key()
    if not key:
        _last_payment_error = "PAYSTACK_SECRET_KEY not configured."
        return ""
    # Paystack appends "?trxref=...&reference=..." to whatever callback_url we
    # send, even if it already contains a "?" — embedding our own query string
    # here produced a malformed double-"?" URL that Streamlit could not parse
    # correctly on return. Keep the callback_url bare; the email is recovered
    # from Paystack's verify response instead (see verify_payment).
    callback_url = _base_url()
    payload = {
        "email": email,
        "amount": amount_kobo,
        "currency": "GHS",
        "callback_url": callback_url,
        "metadata": {"plan": plan, "custom_fields": [
            {"display_name": "Plan", "variable_name": "plan", "value": plan}
        ]},
    }
    try:
        r = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        if data.get("status"):
            return data["data"].get("authorization_url", "")
        _last_payment_error = data.get("message", "Paystack returned an error.")
        return ""
    except Exception as exc:
        _last_payment_error = str(exc)
        return ""


def verify_payment(reference: str) -> dict:
    """
    GET /transaction/verify/{reference}.
    Returns {"status": "success"|"failed"|"error", "amount": int, "plan": str}.
    """
    key = _secret_key()
    if not key or not reference:
        return {"status": "error", "amount": 0, "plan": ""}
    try:
        r = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        if data.get("status") and data["data"].get("status") == "success":
            meta = data["data"].get("metadata", {})
            plan = meta.get("plan", "per_use")
            email = (data["data"].get("customer") or {}).get("email", "")
            return {"status": "success", "amount": data["data"].get("amount", 0), "plan": plan, "email": email}
        return {"status": "failed", "amount": 0, "plan": "", "email": ""}
    except Exception:
        return {"status": "error", "amount": 0, "plan": "", "email": ""}


def initialize_subscription_payment(email: str, amount_kobo: int, plan_code: str, plan_label: str) -> str:
    """
    Same as initialize_payment(), but ties the transaction to a Paystack Plan
    code (see scripts/setup_paystack_plans.py) instead of leaving it a plain
    one-off charge. Per Paystack's subscription flow, the first successful
    charge against a plan-tied transaction creates a recurring Subscription
    that auto-renews (VERIFY against current Paystack docs before relying on
    this). plan_label keeps flowing through metadata.plan exactly like
    initialize_payment(), so verify_payment()'s existing metadata-reading
    logic needs no changes. Returns authorization_url or "" on failure.
    """
    global _last_payment_error
    _last_payment_error = ""
    key = _secret_key()
    if not key:
        _last_payment_error = "PAYSTACK_SECRET_KEY not configured."
        return ""
    if not plan_code:
        _last_payment_error = "Plan not configured."
        return ""
    payload = {
        "email": email,
        "amount": amount_kobo,
        "currency": "GHS",
        "callback_url": _base_url(),
        "plan": plan_code,
        "metadata": {"plan": plan_label, "custom_fields": [
            {"display_name": "Plan", "variable_name": "plan", "value": plan_label}
        ]},
    }
    try:
        r = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        if data.get("status"):
            return data["data"].get("authorization_url", "")
        _last_payment_error = data.get("message", "Paystack returned an error.")
        return ""
    except Exception as exc:
        _last_payment_error = str(exc)
        return ""


def disable_subscription(subscription_code: str, email_token: str) -> tuple[bool, str]:
    """
    POST /subscription/disable (VERIFY exact field names against current
    Paystack docs before relying on this). Cancels a recurring subscription --
    per Paystack's semantics this does not itself revoke access immediately;
    the account keeps access until its already-paid-for period lapses, so
    callers should not flip is_paid here. Returns (success, message).
    """
    key = _secret_key()
    if not key:
        return False, "PAYSTACK_SECRET_KEY not configured."
    if not subscription_code or not email_token:
        return False, "Missing subscription details."
    try:
        r = requests.post(
            "https://api.paystack.co/subscription/disable",
            json={"code": subscription_code, "token": email_token},
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        if data.get("status"):
            return True, data.get("message", "Subscription cancelled.")
        return False, data.get("message", "Paystack returned an error.")
    except Exception as exc:
        return False, str(exc)


def get_customer(email: str) -> dict:
    """GET /customer/{email} -- reconciliation helper, not on the page-render
    hot path. Returns the raw Paystack customer object, or {} on failure."""
    key = _secret_key()
    if not key or not email:
        return {}
    try:
        r = requests.get(
            f"https://api.paystack.co/customer/{email}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        return data.get("data", {}) if data.get("status") else {}
    except Exception:
        return {}


def list_transactions(email: str, limit: int = 20) -> list[dict]:
    """GET /transaction?customer=... -- reconciliation/debugging helper, not
    a page-render dependency (the billing page reads the local `payments`
    table instead, so it never hits the Paystack API synchronously on every
    load). Returns a list of raw Paystack transaction objects, or [] on
    failure."""
    key = _secret_key()
    if not key or not email:
        return []
    try:
        r = requests.get(
            "https://api.paystack.co/transaction",
            params={"customer": email, "perPage": limit},
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        data = r.json()
        return data.get("data", []) if data.get("status") else []
    except Exception:
        return []


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    HMAC-SHA512 of raw_body using the Paystack secret key, compared
    (constant-time) against signature_header (Paystack's x-paystack-signature
    request header).

    The production webhook receiver is the Deno Edge Function
    (supabase/functions/paystack-webhook) -- an independent implementation of
    this same scheme, since Python and Deno can't share code. This copy
    exists for a future Python-side reconciliation/replay-debug tool. If the
    verification scheme ever changes, both must be updated together.
    """
    key = _secret_key()
    if not key or not signature_header:
        return False
    computed = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header)
