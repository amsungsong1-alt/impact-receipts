"""
One-time-passcode (OTP) email verification via Resend.
Degrades gracefully: if RESEND_API_KEY isn't configured, otp_enabled()
returns False so callers can fall back to unverified email entry.
"""
from __future__ import annotations
import os
import random


def _get_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(name) or os.environ.get(name, default)
    except Exception:
        return os.environ.get(name, default)


def otp_enabled() -> bool:
    return bool(_get_secret("RESEND_API_KEY"))


def generate_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def send_otp_email(to_email: str, code: str) -> tuple[bool, str]:
    """Send a one-time verification code via Resend. Returns (success, error_message)."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email verification is not configured."
    from_address = _get_secret("RESEND_FROM", "Impact-Receipts <onboarding@resend.dev>")
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": f"Your Impact-Receipts verification code: {code}",
                "html": (
                    "<div style='font-family:sans-serif;'>"
                    "<p>Your Impact-Receipts verification code is:</p>"
                    f"<p style='font-size:28px;font-weight:700;letter-spacing:6px;'>{code}</p>"
                    "<p style='color:#616161;font-size:0.85rem;'>This code expires in 10 minutes. "
                    "If you didn't request this, you can safely ignore this email.</p>"
                    "</div>"
                ),
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, ""
        return False, f"Email service returned {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
