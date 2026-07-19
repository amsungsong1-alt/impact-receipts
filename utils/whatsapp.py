"""
utils/whatsapp.py — WhatsApp Cloud API client for ImpactProof

Provides per-function notification to the founder (+233 50 364 8195) when users
click any WhatsApp CTA in the app, using Meta's WhatsApp Cloud API template messages.

Degrades gracefully when WHATSAPP_TOKEN is not configured — the wa.me link still
opens WhatsApp normally, no user-facing error.

Required secrets (add to .streamlit/secrets.toml):
    WHATSAPP_TOKEN           = "EAAxxxxxxx..."
    WHATSAPP_PHONE_NUMBER_ID = "1234567890"
    WHATSAPP_VERIFY_TOKEN    = "impactproof_wh"

Template names to register with Meta (Category: UTILITY, Language: en_US):
    impactproof_lead_notify  — sent TO founder when user clicks a CTA
    impactproof_user_ack     — auto-reply TO user when they message the number
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import datetime
from typing import Any

WA_NUMBER   = "233503648195"   # founder's WhatsApp Business number (no + prefix)
WA_API_BASE = "https://graph.facebook.com/v20.0"

# ---------------------------------------------------------------------------
# Per-CTA context definitions
# ---------------------------------------------------------------------------

WA_CONTEXTS: dict[str, dict[str, str]] = {
    "weak_result_review": {
        "notify_label": "Weak result review request",
        "user_ack":     (
            "Your result review request is received! "
            "We'll look at your scores and reply here within 24 hours. "
            "Please share your result details if you haven't already."
        ),
        "wa_message_tpl": (
            "Hi, I've just run an ImpactProof check "
            "(Confidence: {conf}/5.0, {verdict}). "
            "I'd like a deeper review before submission. "
            "My email: {email}"
        ),
    },
    "agency_plan": {
        "notify_label": "Agency plan inquiry",
        "user_ack":     (
            "Thanks for your interest in the ImpactProof Agency plan! "
            "We'll be in touch about multi-seat pricing within 24 hours."
        ),
        "wa_message_tpl": (
            "Hi, I'm interested in the ImpactProof Agency plan for my team. "
            "My email: {email}"
        ),
    },
    "landing_review": {
        "notify_label": "Landing page — free review request",
        "user_ack":     (
            "Your free review request is received! "
            "We'll reach out to discuss your submission deadline and evidence quality."
        ),
        "wa_message_tpl": (
            "Hi, I'd like to book a free first review with the ImpactProof founder. "
            "My email: {email}"
        ),
    },
    "payment_support": {
        "notify_label": "Payment support issue",
        "user_ack":     (
            "Payment support acknowledged! "
            "We'll resolve your issue within 4 hours — "
            "please send your transaction reference if you have one."
        ),
        "wa_message_tpl": (
            "Hi, I was charged on ImpactProof but not unlocked. "
            "My email: {email}"
        ),
    },
    "error_support": {
        "notify_label": "App error report",
        "user_ack":     "App error received — we'll investigate and get back to you shortly.",
        "wa_message_tpl": (
            "Hi, I encountered an error on ImpactProof. "
            "My email: {email}"
        ),
    },
    "pricing_questions": {
        "notify_label": "General pricing inquiry",
        "user_ack":     (
            "Thanks for your question! "
            "We'll reply here with pricing details within 24 hours."
        ),
        "wa_message_tpl": (
            "Hi, I have a question about ImpactProof pricing. "
            "My email: {email}"
        ),
    },
}

# Generic auto-reply fallback when context keyword matching fails
_GENERIC_USER_ACK = (
    "Hi! Thanks for reaching out to ImpactProof. "
    "We'll get back to you on WhatsApp within 24 hours. "
    "In the meantime, visit impact-proof.streamlit.app"
)

# Keywords for context detection in inbound messages (used by webhook)
INBOUND_KEYWORDS: dict[str, list[str]] = {
    "weak_result_review":  ["review", "score", "confidence", "clarity", "submission", "check"],
    "agency_plan":         ["agency", "team", "seats", "multiple", "organisation"],
    "payment_support":     ["payment", "charged", "paid", "unlock", "paystack", "momo", "visa"],
    "error_support":       ["error", "bug", "crash", "broken", "issue", "problem"],
    "pricing_questions":   ["price", "pricing", "cost", "plan", "professional", "subscription"],
    "landing_review":      ["book", "free", "first review", "deadline", "submit"],
}


# ---------------------------------------------------------------------------
# Secrets helpers
# ---------------------------------------------------------------------------

def _get_secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(key, "") or os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def wa_enabled() -> bool:
    """True if WhatsApp Cloud API credentials are configured."""
    return bool(_get_secret("WHATSAPP_TOKEN")) and bool(_get_secret("WHATSAPP_PHONE_NUMBER_ID"))


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_wa_url(context_id: str, user_email: str = "",
                  result_data: dict[str, Any] | None = None) -> str:
    """
    Build an enriched wa.me URL for the given context. The pre-filled message
    includes the user's email + any result scores so the founder has context
    before the conversation even starts.
    """
    ctx = WA_CONTEXTS.get(context_id, {})
    tpl = ctx.get("wa_message_tpl", "Hi, I'd like to get in touch with ImpactProof.")

    rd = result_data or {}
    msg = tpl.format(
        email   = user_email or "not provided",
        conf    = rd.get("conf", "?"),
        clar    = rd.get("clar", "?"),
        verdict = rd.get("verdict", ""),
    )
    return f"https://wa.me/{WA_NUMBER}?text={urllib.parse.quote(msg)}"


# ---------------------------------------------------------------------------
# WhatsApp Cloud API — send template message
# ---------------------------------------------------------------------------

def send_wa_template(
    to: str,
    template_name: str,
    params: list[str],
    api_key: str,
    phone_number_id: str,
) -> tuple[bool, str]:
    """
    POST a template message to the WhatsApp Cloud API.

    Args:
        to:               Recipient phone number (digits only, e.g. "233501234567")
        template_name:    Meta-approved template name
        params:           List of parameter strings for template {{1}}, {{2}}, ...
        api_key:          WHATSAPP_TOKEN
        phone_number_id:  WHATSAPP_PHONE_NUMBER_ID

    Returns:
        (success: bool, error_or_message_id: str)
    """
    import json
    try:
        import urllib.request
        url     = f"{WA_API_BASE}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en_US"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(p)[:256]} for p in params
                        ],
                    }
                ] if params else [],
            },
        }
        data    = json.dumps(payload).encode("utf-8")
        req     = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            msg_id = (body.get("messages") or [{}])[0].get("id", "")
            return True, msg_id
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Per-function helpers
# ---------------------------------------------------------------------------

def notify_founder(
    context_id: str,
    user_email: str = "",
    result_data: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Send template `impactproof_lead_notify` to the founder's number.
    Called server-side when any WhatsApp CTA is clicked.

    Parameters mapped to template placeholders:
        {{1}} cta_type       — human-readable label from WA_CONTEXTS
        {{2}} user_email     — user's email address
        {{3}} context_summary — scores / verdict (for result-related CTAs)
        {{4}} timestamp      — ISO timestamp of the click
    """
    if not wa_enabled():
        return False, "WHATSAPP_TOKEN not configured — skipping notification"

    api_key         = _get_secret("WHATSAPP_TOKEN")
    phone_number_id = _get_secret("WHATSAPP_PHONE_NUMBER_ID")

    ctx   = WA_CONTEXTS.get(context_id, {})
    rd    = result_data or {}
    label = ctx.get("notify_label", context_id)

    ctx_summary = ""
    if rd.get("conf") is not None:
        ctx_summary = f"Confidence: {rd['conf']}/5.0, Clarity: {rd.get('clar','?')}/5.0"
        if rd.get("verdict"):
            ctx_summary += f", Verdict: {rd['verdict']}"
    if not ctx_summary:
        ctx_summary = "No result data"

    params = [
        label,
        user_email or "not provided",
        ctx_summary,
        datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    ]

    ok, result = send_wa_template(
        WA_NUMBER, "impactproof_lead_notify", params, api_key, phone_number_id
    )

    # Log to Supabase if available (non-blocking)
    try:
        from utils.db import log_wa_event
        log_wa_event(context_id, user_email, "outbound_notify", WA_NUMBER,
                     f"{label}: {ctx_summary}", ok)
    except Exception:
        pass

    # CRM event -- per-account WhatsApp-click signal for the admin
    # segmentation dashboard (utils/crm.py), parallel to the wa_conversations
    # log above but in the unified crm_events table.
    try:
        from utils.crm import log_event
        log_event(user_email, "whatsapp_click", metadata={"context": context_id, "label": label})
    except Exception:
        pass

    return ok, result


def detect_context_from_message(body: str) -> str:
    """Detect the closest WA_CONTEXTS key from an inbound WhatsApp message body."""
    body_lower = body.lower()
    for ctx_id, keywords in INBOUND_KEYWORDS.items():
        if any(kw in body_lower for kw in keywords):
            return ctx_id
    return "pricing_questions"  # generic fallback


def get_user_ack_message(context_id: str, result_data: dict[str, Any] | None = None) -> str:
    """
    Build the context-aware acknowledgement message for the `impactproof_user_ack`
    template. Used by the Supabase Edge Function webhook auto-reply.
    """
    ctx = WA_CONTEXTS.get(context_id, {})
    ack = ctx.get("user_ack", _GENERIC_USER_ACK)
    rd  = result_data or {}
    return ack.format(
        conf    = rd.get("conf", "?"),
        clar    = rd.get("clar", "?"),
        verdict = rd.get("verdict", ""),
    )


def send_user_ack_reply(to: str, context_id: str,
                         result_data: dict[str, Any] | None = None) -> tuple[bool, str]:
    """
    Send the auto-reply template to a user who just messaged the WhatsApp number.
    Called from the Supabase Edge Function (which extracts `to` from the webhook payload).
    Can also be called directly from Python if needed.
    """
    if not wa_enabled():
        return False, "WHATSAPP_TOKEN not configured"

    api_key         = _get_secret("WHATSAPP_TOKEN")
    phone_number_id = _get_secret("WHATSAPP_PHONE_NUMBER_ID")

    ack_msg = get_user_ack_message(context_id, result_data)
    ok, result = send_wa_template(
        to, "impactproof_user_ack", [ack_msg], api_key, phone_number_id
    )

    try:
        from utils.db import log_wa_event
        log_wa_event(context_id, "", "auto_reply", to, ack_msg[:200], ok)
    except Exception:
        pass

    return ok, result
