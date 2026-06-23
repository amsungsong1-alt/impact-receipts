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
    from_address = _get_secret("RESEND_FROM", "Impact Integrity Check <onboarding@resend.dev>")
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": f"Your Impact Integrity Check verification code: {code}",
                "html": (
                    "<div style='font-family:sans-serif;'>"
                    "<p>Your Impact Integrity Check verification code is:</p>"
                    f"<p style='font-size:28px;font-weight:700;letter-spacing:6px;'>{code}</p>"
                    "<p style='color:#424242;font-size:0.875rem;'>This code expires in 10 minutes. "
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


def send_results_email(
    to_email: str,
    conf_score: float,
    clar_score: float,
    top_fixes: list,
    result_snippet: str,
    verdict: str,
) -> tuple[bool, str]:
    """Send post-check results summary email. Returns (success, error_message)."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email not configured."
    from_address = _get_secret(
        "RESEND_FROM", "Impact Integrity Check <onboarding@resend.dev>"
    )
    conf_pct = round(conf_score / 5 * 100)
    clar_pct = round(clar_score / 5 * 100)
    fixes_html = "".join(
        f"<li style='margin-bottom:6px;'>{f.get('message', '')} "
        f"<em style='color:#616161;'>({f.get('score_impact', '')})</em></li>"
        for f in top_fixes[:3]
    )
    snippet = (result_snippet[:200] + "...") if len(result_snippet) > 200 else result_snippet
    fixes_block = (
        "<p><strong>Top fixes:</strong></p><ul>" + fixes_html + "</ul>"
        if fixes_html else ""
    )
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": f"Your check: Confidence {conf_pct}% · Clarity {clar_pct}% — {verdict}",
                "html": f"""
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>Your Impact Integrity Check results</h2>
  <p style='color:#616161;font-size:0.9rem;margin-top:0;'>{snippet}</p>
  <table style='width:100%;border-collapse:collapse;margin:16px 0;'>
    <tr>
      <td style='padding:14px;background:#EDF7F1;border-radius:6px;text-align:center;'>
        <strong style='font-size:1.6rem;color:#1B5E20;'>{conf_pct}%</strong><br>
        <span style='color:#616161;font-size:0.8rem;'>Confidence</span>
      </td>
      <td style='width:16px;'></td>
      <td style='padding:14px;background:#EDF7F1;border-radius:6px;text-align:center;'>
        <strong style='font-size:1.6rem;color:#1B5E20;'>{clar_pct}%</strong><br>
        <span style='color:#616161;font-size:0.8rem;'>Clarity</span>
      </td>
    </tr>
  </table>
  <p style='margin:0 0 12px;'><strong>Verdict:</strong> {verdict}</p>
  {fixes_block}
  <p style='margin-top:24px;'>
    <a href='https://impact-integrity-diagnostic.streamlit.app/'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Fix gaps &amp; re-score &rarr;
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:28px;border-top:1px solid #eee;padding-top:12px;'>
    Impact Integrity Check &middot; Built in Accra for MEL teams across West Africa<br>
    <a href='https://impact-integrity-diagnostic.streamlit.app/' style='color:#9e9e9e;'>
      impact-integrity-diagnostic.streamlit.app
    </a>
  </p>
</div>""",
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, ""
        return False, f"Email service returned {resp.status_code}"
    except Exception as e:
        return False, str(e)
