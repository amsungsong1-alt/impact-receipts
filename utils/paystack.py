"""
Paystack payment integration — initialize + verify transactions.
Supports MTN MoMo, Telecel/AirtelTigo Money, and bank cards (Ghana).
All secrets via st.secrets / environment variables.
"""
from __future__ import annotations
import os
import urllib.parse
import requests


def _secret_key() -> str:
    try:
        import streamlit as st
        return st.secrets.get("PAYSTACK_SECRET_KEY") or os.environ.get("PAYSTACK_SECRET_KEY", "")
    except Exception:
        return os.environ.get("PAYSTACK_SECRET_KEY", "")


def _base_url() -> str:
    try:
        import streamlit as st
        configured = st.secrets.get("APP_BASE_URL") or os.environ.get("APP_BASE_URL", "")
        if configured:
            return configured.rstrip("/")
        return "https://impact-receipts.streamlit.app"
    except Exception:
        return os.environ.get("APP_BASE_URL", "https://impact-receipts.streamlit.app")


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
    callback_url = f"{_base_url()}?user_email={urllib.parse.quote(email, safe='')}"
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
            return {"status": "success", "amount": data["data"].get("amount", 0), "plan": plan}
        return {"status": "failed", "amount": 0, "plan": ""}
    except Exception:
        return {"status": "error", "amount": 0, "plan": ""}
