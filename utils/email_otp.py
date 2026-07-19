"""
One-time-passcode (OTP) email verification via Resend.
Degrades gracefully: if RESEND_API_KEY isn't configured, otp_enabled()
returns False so callers can fall back to unverified email entry.
"""
from __future__ import annotations
import os
import secrets


_APP_NAME = "ImpactProof"


def _get_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(name) or os.environ.get(name, default)
    except Exception:
        return os.environ.get(name, default)


def _from_address() -> str:
    """Build the From: address, always using the current app name regardless of
    what display name the RESEND_FROM secret may contain."""
    raw = _get_secret("RESEND_FROM", "")
    if not raw:
        return f"{_APP_NAME} <onboarding@resend.dev>"
    # If the secret has an old display name (e.g. "Impact Integrity Diagnostic <...>"),
    # extract just the email part and re-wrap with the current app name.
    import re
    m = re.search(r"<([^>]+)>", raw)
    email_part = m.group(1) if m else raw.strip()
    return f"{_APP_NAME} <{email_part}>"


def otp_enabled() -> bool:
    return bool(_get_secret("RESEND_API_KEY"))


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def send_otp_email(to_email: str, code: str) -> tuple[bool, str]:
    """Send a one-time verification code via Resend. Returns (success, error_message)."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email verification is not configured."
    from_address = _from_address()
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": f"Your {_APP_NAME} verification code: {code}",
                "html": (
                    "<div style='font-family:sans-serif;'>"
                    "<p>Your ImpactProof verification code is:</p>"
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
        # 403 with "verify a domain" means the Resend account is in test mode
        # and can only send to the account owner's address.  Signal this with a
        # special prefix so callers can fall back to simple email entry rather
        # than blocking the user entirely.
        if resp.status_code == 403 and "domain" in resp.text.lower():
            return False, "DOMAIN_NOT_VERIFIED:" + resp.text[:200]
        return False, f"Email service returned {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def send_login_email(to_email: str, link_url: str, code: str) -> tuple[bool, str]:
    """Send a magic-link login email that also carries a 6-digit fallback code
    (some corporate email security scanners pre-fetch links and silently burn a
    single-use token before the real user clicks it -- the code lets them in
    anyway). Returns (success, error_message)."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email verification is not configured."
    from_address = _from_address()
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": f"Log in to {_APP_NAME}",
                "html": (
                    "<div style='font-family:sans-serif;'>"
                    "<p>Click below to log in:</p>"
                    f"<p><a href='{link_url}' "
                    "style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;"
                    "text-decoration:none;font-weight:700;display:inline-block;'>Log in →</a></p>"
                    "<p style='color:#616161;font-size:0.875rem;'>This link expires in 20 minutes "
                    "and works once.</p>"
                    "<p>Or enter this code instead:</p>"
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
        if resp.status_code == 403 and "domain" in resp.text.lower():
            return False, "DOMAIN_NOT_VERIFIED:" + resp.text[:200]
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
    from_address = _from_address()
    _app_url = _get_secret("APP_BASE_URL", "https://impact-integrity-diagnostic.streamlit.app").rstrip("/")
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
  <h2 style='color:#1B5E20;margin-bottom:4px;'>Your {_APP_NAME} results</h2>
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
    <a href='{_app_url}/'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Fix gaps &amp; re-score &rarr;
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:28px;border-top:1px solid #eee;padding-top:12px;'>
    {_APP_NAME} &middot; Built in Accra for MEL teams across West Africa<br>
    <a href='{_app_url}/' style='color:#424242;'>
      {_APP_NAME}
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


def _unsubscribe_footer(app_url: str, unsubscribe_token: str) -> str:
    """Shared footer block for marketing (non-transactional) sends only --
    send_otp_email/send_login_email/send_results_email/send_welcome_email are
    transactional and must NOT include this. unsubscribe_token comes from
    users.unsubscribe_token (supabase/migrations/0013); routes to app.py's
    _render_unsubscribe_landing() via the ?unsubscribe= query param."""
    if not unsubscribe_token:
        return ""
    unsub_url = f"{app_url}/?unsubscribe={unsubscribe_token}"
    return (
        f"<p style='color:#9e9e9e;font-size:0.75rem;margin-top:16px;'>"
        f"<a href='{unsub_url}' style='color:#9e9e9e;'>Unsubscribe from these emails</a></p>"
    )


def send_case_study_email(to_email: str, unsubscribe_token: str = "") -> tuple[bool, str]:
    """Day-3 onboarding email — a case study on rework costs, sent by the
    onboarding-drip Edge Function (see supabase/functions/onboarding-drip)
    to accounts 3+ days past signup that haven't received it yet. This
    Python function is the canonical/reviewable template source; the actual
    scheduled send re-implements this same HTML as a TS string literal in
    that Edge Function (Deno can't import this module) — keep both in sync
    by hand if the copy changes here."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email not configured."
    from_address = _from_address()
    _app_url = _get_secret("APP_BASE_URL", "https://impact-integrity-diagnostic.streamlit.app").rstrip("/")
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": "What a rejected donor report actually costs",
                "html": f"""
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>40+ hours of rework, avoidable</h2>
  <p style='font-size:0.9rem;'>
    A real African consultancy had their final donor report rejected 3 times in 2024 —
    because results weren't tied to logframe indicators. That's 40+ hours of rework,
    a missed deadline, and a donor relationship under strain.
  </p>
  <p style='font-size:0.9rem;'>
    The fix was small: catching the gap before submission, not after. That's exactly
    what {_APP_NAME}'s Confidence and Clarity scores are built to do — flag weak
    evidence and missing logframe links before your donor does.
  </p>
  <p style='margin-top:20px;'>
    <a href='{_app_url}/'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Run another check →
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;'>
    {_APP_NAME} &middot; Built in Accra for MEL teams across West Africa
  </p>
  {_unsubscribe_footer(_app_url, unsubscribe_token)}
</div>""",
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, ""
        return False, f"Email service returned {resp.status_code}"
    except Exception as e:
        return False, str(e)


def send_upgrade_offer_email(to_email: str, unsubscribe_token: str = "") -> tuple[bool, str]:
    """Day-7 onboarding email — an upgrade offer, sent by the onboarding-drip
    Edge Function to accounts 7+ days past signup that haven't received it
    yet. Same canonical-template/keep-in-sync-with-the-Edge-Function note as
    send_case_study_email() above."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email not configured."
    from_address = _from_address()
    _app_url = _get_secret("APP_BASE_URL", "https://impact-integrity-diagnostic.streamlit.app").rstrip("/")
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": "Unlimited checks, re-scoring, and a PDF your supervisor can read",
                "html": f"""
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>Ready for unlimited checks?</h2>
  <p style='font-size:0.9rem;'>
    You've had a week with {_APP_NAME}. If your free checks are running low, or you're
    fixing gaps and want to re-score without limits, Professional removes the cap.
  </p>
  <p style='font-size:0.9rem;'>
    <strong>Professional</strong> — GHS 50/month: unlimited checks, re-score after every
    fix, and a downloadable Readiness Card PDF to share with your supervisor or donor.
  </p>
  <p style='font-size:0.85rem;color:#616161;'>
    The ROI is immediate: GHS 50/month vs. GHS 12,000&ndash;17,000 in rework costs from a
    donor-queried report.
  </p>
  <p style='margin-top:20px;'>
    <a href='{_app_url}/?billing=1'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Upgrade to Professional →
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;'>
    {_APP_NAME} &middot; Built in Accra for MEL teams across West Africa
  </p>
  {_unsubscribe_footer(_app_url, unsubscribe_token)}
</div>""",
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, ""
        return False, f"Email service returned {resp.status_code}"
    except Exception as e:
        return False, str(e)


def send_welcome_email(to_email: str) -> tuple[bool, str]:
    """Day-1 onboarding email — sent once when a new user first completes the email gate."""
    api_key = _get_secret("RESEND_API_KEY")
    if not api_key:
        return False, "Email not configured."
    from_address = _from_address()
    _app_url = _get_secret("APP_BASE_URL", "https://impact-integrity-diagnostic.streamlit.app").rstrip("/")
    try:
        import requests
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_address,
                "to": [to_email],
                "subject": f"Your first check is waiting — 4 minutes, free",
                "html": f"""
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>Welcome to {_APP_NAME}</h2>
  <p style='color:#424242;font-size:0.9rem;margin-top:0;'>
    You're now set up. Your first 3 checks are free — no card needed.
  </p>
  <p style='font-size:0.9rem;'>
    The fastest way to get value: paste your result statement into the <strong>Quick Check</strong>
    on the home page. You'll see your provisional Confidence and Clarity scores in under a minute.
  </p>
  <p style='margin-top:20px;'>
    <a href='{_app_url}/'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Run my first check →
    </a>
  </p>
  <hr style='border:none;border-top:1px solid #eee;margin:24px 0;'/>
  <p style='font-size:0.85rem;color:#424242;'>
    <strong>What you get:</strong><br/>
    ✓ Confidence score — how strong is your evidence?<br/>
    ✓ Clarity score — how precisely defined is your result?<br/>
    ✓ Top 3 fixes — what to address before submitting<br/>
    ✓ Readiness Card PDF — shareable with your MEL lead
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;'>
    {_APP_NAME} &middot; Built in Accra for MEL teams across West Africa
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
