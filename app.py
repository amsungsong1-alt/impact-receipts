"""
app.py — Impact-Receipts: Pre-submission confidence check for MEL teams.

Run with:  streamlit run app.py

Screen flow driven by st.session_state["screen"] (0-3):
  0  Landing & Onboarding
  1  Reported Result Submission
  2  Confidence Snapshot & Next Steps
  3  Portfolio / Framework Dashboard (multi-indicator logframe upload)

Evaluation logic is fully local — see evaluator.py.
No API calls. All data stays on device.
"""

import base64
import json
import os
import pathlib
import re
import threading
import time
import urllib.parse
from datetime import datetime, date

import streamlit as st
import evaluator as _evaluator
from diagnostics import (
    _DIAGNOSTIC_BADGE, _READINESS_BAND, _READINESS_STYLE, _LIMITS_DISCLAIMER,
    _readiness_banner_html, get_diagnostic_state,
    _BRAND_BADGE, _VERDICT_CSS, _DIRECTNESS_TIPS, _VERIFICATION_TIPS,
    _RECENCY_TIPS, _CLARITY_TIPS, _SCORING_GUIDE, _axis_badge_html,
    _overview_score_values, _build_overview_chart_b64,
    DONOR_PROFILES, build_donor_crosswalk_html,
)
from prompts import (
    TOOLTIP_DEFINITION, TOOLTIP_MEASUREMENT, TOOLTIP_INTEGRITY,
    TOOLTIP_SCOPE, TOOLTIP_GOVERNANCE,
    BENEFICIARY_VOICE_TOOLTIP, BENEFICIARY_VOICE_WHATTOFIX,
    METHODOLOGY_STACK,
)
from donor_templates import DONOR_DIAGNOSTICS

# --- Payment / auth / DB utilities ---
try:
    from utils.db import (
        get_user, upsert_user, increment_checks, mark_paid,
        is_still_paid, save_example, get_examples,
    )
    from utils.paystack import initialize_payment, verify_payment, last_payment_error
    from utils.anonymize import anonymize as _anonymize_value
    _UTILS_AVAILABLE = True
except ImportError:
    _UTILS_AVAILABLE = False
    def get_user(e): return None
    def upsert_user(e): return None
    def increment_checks(e): pass
    def mark_paid(e, days=30): pass
    def is_still_paid(u): return False
    def save_example(f, s, v): pass
    def get_examples(f, s, k=5): return []
    def initialize_payment(e, a, p="per_use"): return ""
    def verify_payment(r): return {"status": "error", "amount": 0, "plan": ""}
    def last_payment_error(): return ""
    def _anonymize_value(v): return None
# --- End utils imports ---

# --- OTP email verification ---
try:
    from utils.email_otp import otp_enabled, generate_otp, send_otp_email
except ImportError:
    def otp_enabled(): return False
    def generate_otp(): return "000000"
    def send_otp_email(e, c): return False, "Email verification is not configured."
# --- End OTP email verification ---

# --- UX: INSTANT REPORT CHECK IMPORTS (v3.2) ---
import anthropic as _anthropic
try:
    import fitz as _fitz
    _HAS_FITZ = True
except ImportError:
    _fitz = None
    _HAS_FITZ = False
try:
    import docx as _docx
    _HAS_DOCX = True
except ImportError:
    _docx = None
    _HAS_DOCX = False
try:
    import pdfplumber as _pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _pdfplumber = None
    _HAS_PDFPLUMBER = False
try:
    import pandas as _pd
    _HAS_PANDAS = True
except ImportError:
    _pd = None
    _HAS_PANDAS = False
try:
    import pptx as _pptx
    _HAS_PPTX = True
except ImportError:
    _pptx = None
    _HAS_PPTX = False
# --- END UX: INSTANT REPORT CHECK IMPORTS (v3.2) ---

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# --- Payment / usage constants (edit amounts here) ---
FREE_CHECKS_LIMIT     = 3          # free manual checks per user
PRICE_PER_CHECK_GHS   = 500        # pesewas  (GHS 5.00)
PRICE_MONTHLY_GHS     = 5000       # pesewas  (GHS 50.00/month)
# --- End payment constants ---

# --- Disposable / temporary email domains (blocked at the email gate) ---
# Prevents users from cycling through throwaway addresses to reset the
# free-checks counter. Not exhaustive, but covers the most common services.
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "10minutemail.com", "10minutemail.net", "guerrillamail.com",
    "guerrillamail.net", "guerrillamail.org", "guerrillamail.biz", "sharklasers.com",
    "tempmail.com", "temp-mail.org", "tempmail.net", "tempmail.dev", "throwawaymail.com",
    "yopmail.com", "yopmail.net", "fakeinbox.com", "trashmail.com", "trashmail.net",
    "getnada.com", "mailnesia.com", "maildrop.cc", "mintemail.com", "mohmal.com",
    "dispostable.com", "moakt.com", "emailondeck.com", "mailcatch.com", "spambog.com",
    "33mail.com", "discard.email", "mytemp.email", "tempinbox.com", "burnermail.io",
    "mail-temp.com", "fakemailgenerator.com", "inboxkitten.com", "tempm.com",
}


def _is_disposable_email(email: str) -> bool:
    """Return True if the email's domain is a known disposable/temp-mail provider."""
    domain = email.strip().lower().rsplit("@", 1)[-1]
    return domain in DISPOSABLE_EMAIL_DOMAINS

EVIDENCE_TYPES = [
    "Select evidence type...",
    "Attendance sheets / participant registers",
    "Raw datasets or survey exports",
    "Partner verification letters",
    "Photos with metadata",
    "Tracer survey results",
    "Financial records",
    "Third-party audits",
    "Case study",
    "Outcome harvesting",
    "Beneficiary narrative or testimony",
    "Other",
]

# Evidence types scored on sourcing rigor, triangulation, and bias
# mitigation (Qualitative Evidence Track) instead of measurement precision.
QUALITATIVE_EVIDENCE_TYPES = (
    "Case study",
    "Outcome harvesting",
    "Beneficiary narrative or testimony",
)

# Per-type wording for the five Qualitative Rigor checkboxes (qual_sourcing,
# qual_triangulated, qual_bias feed Measurement/"Sourcing & Triangulation";
# qual_voice, qual_consent feed Definition/"Narrative Definition"). Same
# keys/scoring across types — only the label is tailored so it matches what
# the officer is actually looking at.
QUAL_RIGOR_CHECKLIST = {
    "Case study": (
        "Case/respondent selection method documented "
        "(not just convenience — explain how and why these cases were chosen)",
        "Cross-checked against another source or method (triangulation)",
        "Recall, social-desirability, or selection bias considered and addressed",
        "The case(s) reflect a representative range of beneficiaries, not just one outlier story",
        "Consent to share this account was obtained, and identifying details handled appropriately",
    ),
    "Outcome harvesting": (
        "Outcome description and contribution claim documented "
        "(what changed, and how the program plausibly contributed)",
        "Outcome substantiated with the people/organizations who experienced or observed it (triangulation)",
        "Confirmation bias or post-hoc rationalization considered and addressed",
        "The people/organizations consulted reflect a representative range of those affected",
        "Consent to share this account was obtained, and identifying details handled appropriately",
    ),
    "Beneficiary narrative or testimony": (
        "Selection of who was interviewed/recorded is documented "
        "(not just the most positive or available story)",
        "Account cross-checked against another source or method (triangulation)",
        "Social-desirability or success-story bias considered and addressed",
        "The voices represented reflect a range of beneficiaries, not just one outlier story",
        "Consent to share this account was obtained, and identifying details handled appropriately",
    ),
}

# --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
PII_EVIDENCE_TYPES = [
    "Attendance sheets / participant registers",
    "Photos with metadata",
    "Raw datasets or survey exports",
    "Tracer survey results",
]

# Evidence types that may carry beneficiary stories, photos, or testimony —
# trigger the do-no-harm / safeguarding check, not just the PII/data-law checks.
SAFEGUARDING_EVIDENCE_TYPES = [
    "Photos with metadata",
    "Case study",
    "Outcome harvesting",
    "Beneficiary narrative or testimony",
]

# Governance checklist display maps: value → (icon, description, pts_earned)
CONSENT_CHECKLIST_MAP = {
    "Yes — written consent forms on file":    ("✓", "Written consent on file", 5),
    "Yes — verbal consent documented":         ("✓", "Verbal consent documented", 3),
    "Partial — some beneficiaries consented":  ("⚠", "Partial consent", 1),
    "Not applicable (no personal data)":       ("✓", "Not applicable", 3),
    "No — consent not obtained":               ("✗", "Consent not obtained", 0),
}
ANON_CHECKLIST_MAP = {
    "Yes — fully anonymized":   ("✓", "Fully anonymized", 4),
    "Partially anonymized":     ("⚠", "Partially anonymized", 2),
    "No — not anonymized":      ("✗", "Not anonymized", 0),
    "Not applicable":           ("✓", "Not applicable", 3),
}
LAW_CHECKLIST_MAP = {
    "Yes — compliant (e.g. Ghana Act 843, Nigeria NDPA, Kenya DPA)": ("✓", "Compliant", 3),
    "Unsure — we haven't checked": ("⚠", "Unsure — needs verification", 1),
    "No — we are not compliant":   ("✗", "Not compliant", 0),
    "Not applicable":              ("✓", "Not applicable", 0),
}
SAFEGUARDING_CHECKLIST_MAP = {
    "Yes — reviewed, no concerns identified":         ("✓", "Do-no-harm review completed", 3),
    "Yes — reviewed, identifying details removed":    ("✓", "Reviewed & de-identified", 3),
    "Partial — some content not yet reviewed":        ("⚠", "Partial review", 1),
    "Not applicable (no beneficiary stories/photos)": ("✓", "Not applicable", 3),
    "No — not yet reviewed":                          ("✗", "Do-no-harm review not completed", 0),
}

# Keywords suggesting the result statement/target group may involve minors —
# used only to decide whether to prompt the child-safeguarding question and
# show a warning. Never used to auto-answer the checklist.
CHILD_SAFEGUARDING_KEYWORDS = (
    "child", "children", "minor", "minors", "student", "students", "pupil", "pupils",
    "adolescent", "adolescents", "youth", "girl", "girls", "boy", "boys", "orphan", "orphans",
)

CHILD_SAFEGUARDING_CHECKLIST_MAP = {
    "Yes — child safeguarding policy applied, guardian consent obtained where applicable":
        ("✓", "Child safeguarding policy applied", 3),
    "Partial — some steps taken but not complete":
        ("⚠", "Partial child safeguarding review", 1),
    "Not applicable (no minors involved)":
        ("✓", "Not applicable", 3),
    "No — not yet reviewed":
        ("✗", "Child safeguarding review not completed", 0),
}

SECURE_HANDLING_CHECKLIST_MAP = {
    "Yes — stored securely, access restricted to authorised staff":
        ("✓", "Securely stored, access-restricted", 3),
    "Partial — some identifiable material not yet secured":
        ("⚠", "Partial secure handling", 1),
    "Not applicable (no identifiable testimony/photos)":
        ("✓", "Not applicable", 3),
    "No — not yet secured":
        ("✗", "Secure handling not yet confirmed", 0),
}
# --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---

# --- UX: INSTANT REPORT CHECK (v3.2) ---
INSTANT_CHECK_SYSTEM_PROMPT = r'''You are an expert MEL (Monitoring, Evaluation, and Learning) data extraction engine for the Impact Integrity Diagnostic tool. Your job is to read donor-funded project progress reports and extract structured data to pre-fill a submission verification form.

## YOUR TASK

Extract data from the progress report provided by the user and return a single, valid JSON object — no preamble, no markdown fences, no explanation. Return only the JSON.

## EXTRACTION RULES

### Rule 1 — Always Extract, Never Invent
Extract only what is explicitly stated or can be directly inferred from the document text. Do not fabricate data. If a field is genuinely absent from the document, return "Not found" as the value (string, not null).

### Rule 2 — Infer Intelligently
For fields not explicitly labelled, infer from context. Examples:
- If the report mentions "USAID / Feed the Future", the Primary Donor is "USAID / Feed the Future Ghana".
- If activities span January–March 2026, the Reporting Period Start is "2026/01/01" and End is "2026/03/31".
- If the report says "reviewed by MEL Officer", Internal Review is "Reviewed by MEL Officer".

### Rule 3 — Date Format
All dates must be formatted as YYYY/MM/DD.

### Rule 4 — Geographic Scope
Return as a JSON array of strings, one entry per district/region/location mentioned.

### Rule 5 — Evidence Type Selection
Map the described evidence to the closest standard type from this list:
- "Attendance sheets / participant registers"
- "Raw datasets or survey exports"
- "Partner verification letters"
- "Photos with metadata"
- "Tracer survey results"
- "Financial records"
- "Third-party audits"
- "Other"
If multiple types apply, list the most dominant one.

### Rule 6 — Submission Type Selection
Choose the closest match from this list, based on the document's title, framing, and content:
"Quarterly progress report", "Annual progress report", "Baseline report", "Mid-term review",
"End-line evaluation", "Final/closeout report", "Project proposal", "Financial report",
"MEL plan", "Others (Special/Ad-hoc reports)"

### Rule 7 — Compliance Flags
For the three compliance fields (consent, anonymisation, data protection), if the document does not explicitly address them, return "Not found" — do NOT assume compliance.

### Rule 8 — Logframe Linkage
Extract the PRIMARY indicator that the main result statement reports against. If multiple indicators are listed, select the one with the highest strategic prominence (usually the reach/beneficiary count indicator at Output level).

### Rule 9 — Evidence Narrative
For "evidence_narrative", write a 2–4 sentence synthesis describing HOW the result was achieved and WHAT evidence exists, drawing from the activities and M&E sections. Do not copy-paste — synthesise.

### Rule 10 — Result Statement
The result statement should be the single clearest achievement sentence from the Executive Summary or KPI table. It must contain: (a) a number, (b) a target group, (c) a timeframe, and (d) a % achievement or comparison to target if available.

### Rule 11 — Sector Selection
Choose the closest match from this list based on the document's subject matter:
"WASH", "Health", "Education", "Agriculture / Livelihoods", "Youth Employment",
"Climate Resilience", "Governance", "Other"

### Rule 12 — Primary Donor
If the document names a specific donor/funder (e.g., USAID, FCDO, GIZ, RVO, World Bank, AfDB,
EU/EuropeAid), return that donor's name. If a donor is mentioned but not one of these, return
the donor's name as written. If no donor is mentioned anywhere, return "Not found".

### Rule 13 — Funder Readiness Inputs
Read the ENTIRE document — including annexes, appendices, lessons-learned sections, M&E/MEL
sections, and any image captions or figure/table descriptions — for the following:
- "learning_and_adaptation": A 1–3 sentence synthesis of what the implementing team learned
  and how the program adapted as a result. Only include this if the document explicitly
  describes a lesson learned, adaptation, course-correction, or change in approach.
- "limitations": A 1–2 sentence synthesis of what the reported data does NOT show, cannot
  confirm, or cannot be generalized to (e.g., sample limitations, geographic scope limits,
  self-reported data caveats). Only include this if the document explicitly states a
  limitation or caveat.
- "result_owner_and_decision": If the document names a person, role, or unit responsible for
  this result (e.g., "MEL Lead", "Project Manager") AND/OR describes a decision the result
  will inform (e.g., "will inform the Q3 budget review"), synthesise both into one sentence.
- "attribution_vs_contribution": Return "Yes" if the document explicitly distinguishes its
  own contribution from other actors/factors (e.g., "alongside government and other NGOs"),
  "No" if it claims sole credit without acknowledging other factors, or "Not found" if
  attribution/contribution isn't discussed.
- "disaggregation_status": Return "Yes — fully disaggregated" if beneficiary data is broken
  down by sex, age, disability, AND location; "Partially disaggregated" if only some of these
  dimensions are present; "No" if beneficiary numbers are reported only as totals; or
  "Not found" if no beneficiary data is reported at all.
For any of the above not found in the document, return "Not found".

### Rule 14 — Documents Referenced
Return a JSON array of short strings naming any standard report components that this
document itself contains, references as attached, or refers to as available annexes —
e.g., "Logframe", "Budget", "Financial report", "M&E plan", "Audit report", "Beneficiary
list", "Disaggregated data", "Case studies", "Sustainability plan", "Action plan". Base
this only on what is explicitly present or referenced in the text — do not guess.

### Rule 15 — Beneficiary Voice
Choose the closest match from this list, based on whether and how beneficiaries
contributed to or validated the evidence in this document:
- "No beneficiary voice captured"
- "Direct beneficiary feedback collected (e.g., Lean Data survey, focus groups, NPS)"
- "Beneficiary representatives consulted (community leaders, beneficiary committees)"
- "Anecdotal beneficiary quotes only (uncollected, not systematic)"
- "Not applicable to this result type"
If the document doesn't address this at all, return "Not found".

### Rule 16 — Evidence Strengthening Checks
Read the entire document for verifiable details that strengthen the credibility of the
evidence — e.g., whether attendance sheets are dated/stamped, whether photos contain
GPS metadata or timestamps, whether a sampling method is documented, whether financial
records are reconciled with bank statements, whether an auditor was independent, whether
a partner letter is signed and on letterhead, whether a tracer survey documents its
response rate, etc. Return a JSON array of short plain-language phrases describing each
such detail that is EXPLICITLY confirmed in the document (e.g., "Sheets dated and
stamped", "Photos contain GPS metadata", "Auditor independent from implementer"). Only
include items explicitly evidenced in the text — do not guess or infer ones that aren't
directly supported.

## REQUIRED JSON OUTPUT STRUCTURE

Return exactly this structure. Do not add or remove keys.

{
  "result_basics": {
    "result_statement": "<string>",
    "target_group": "<string>",
    "timeframe": "<string>",
    "geographic_scope": ["<string>"],
    "sector": "<string>",
    "primary_donor": "<string>",
    "submission_type": "<string>",
    "beneficiary_voice": "<string>"
  },
  "logframe_linkage": {
    "indicator_name": "<string>",
    "original_target": "<string>",
    "actual_achievement": "<string>"
  },
  "evidence_verification": {
    "evidence_narrative": "<string>",
    "evidence_type": "<string>",
    "internal_review": "<string>",
    "external_review": "<string>",
    "reporting_period_start": "<YYYY/MM/DD>",
    "reporting_period_end": "<YYYY/MM/DD>",
    "evidence_collection_date": "<YYYY/MM/DD>",
    "consent_documented": "<string>",
    "data_anonymised": "<string>",
    "data_protection_compliant": "<string>"
  },
  "funder_readiness_inputs": {
    "learning_and_adaptation": "<string>",
    "limitations": "<string>",
    "result_owner_and_decision": "<string>",
    "attribution_vs_contribution": "<string>",
    "disaggregation_status": "<string>"
  },
  "documents_referenced": ["<string>"],
  "evidence_strengthening_checks": ["<string>"],
  "extraction_metadata": {
    "implementing_org": "<string>",
    "report_prepared_by": "<string>",
    "confidence_note": "<one sentence describing extraction confidence and any gaps>"
  }
}'''

_UX_TAB_NAMES = ["Result Basics", "Logframe Linkage", "Evidence & Verification", "Review & Submit"]

# IRC field map: extracted key → session_state key
# Excludes selectbox widgets (sector, donor_selected) that render before tab1
_IRC_FIELD_MAP = {
    # Result Basics tab
    "result_statement":   "result_statement",
    "target_group":       "target_group",
    "timeframe":          "timeframe",
    "geographic_scope":   "geographic_scope",
    # Logframe Linkage tab
    "logframe_indicator": "logframe_indicator",
    "logframe_target":    "logframe_target",
    "logframe_achievement": "logframe_achievement",
    # Evidence & Verification tab
    "evidence_description": "evidence_description",
    "verifier":           "verifier",
}

_IRC_PATTERNS = {
    # --- Result Basics ---
    "result_statement": [
        r"(?:key\s+)?result\s+statement\s*[:\-]\s*(.+)",
        r"reported\s+result\s*[:\-]\s*(.+)",
        r"(?:key\s+)?result\s*[:\-]\s*(.+)",
        r"output\s+(?:statement|achieved)\s*[:\-]\s*(.+)",
        r"outcome\s+(?:statement|achieved)\s*[:\-]\s*(.+)",
        r"achievement\s*[:\-]\s*(.+)",
        r"project\s+(?:name|title)\s*[:\-]\s*(.+)",
        r"programme\s+(?:name|title)\s*[:\-]\s*(.+)",
    ],
    "target_group": [
        r"target\s+(?:group|population|beneficiaries|community)\s*[:\-]\s*(.+)",
        r"beneficiar(?:y|ies)\s*[:\-]\s*(.+)",
        r"primary\s+(?:beneficiar(?:y|ies)|target)\s*[:\-]\s*(.+)",
        r"direct\s+beneficiar(?:y|ies)\s*[:\-]\s*(.+)",
    ],
    "timeframe": [
        r"reporting\s+period\s*[:\-]\s*(.+)",
        r"period\s+covered\s*[:\-]\s*(.+)",
        r"implementation\s+period\s*[:\-]\s*(.+)",
        r"timeframe\s*[:\-]\s*(.+)",
        r"report\s+period\s*[:\-]\s*(.+)",
        r"(?:project|programme)\s+(?:duration|period)\s*[:\-]\s*(.+)",
    ],
    "geographic_scope": [
        r"geographic(?:al)?\s+(?:scope|coverage|area)\s*[:\-]\s*(.+)",
        r"country\s*[:\-]\s*(.+)",
        r"(?:project\s+)?location\s*[:\-]\s*(.+)",
        r"region\s*[:\-]\s*(.+)",
        r"(?:target\s+)?(?:district|county|province|state)s?\s*[:\-]\s*(.+)",
    ],
    # --- Logframe Linkage ---
    "logframe_indicator": [
        r"(?:logframe\s+)?indicator\s*(?:name|description)?\s*[:\-]\s*(.+)",
        r"(?:key\s+)?performance\s+indicator\s*[:\-]\s*(.+)",
        r"output\s+indicator\s*[:\-]\s*(.+)",
        r"outcome\s+indicator\s*[:\-]\s*(.+)",
        r"KPI\s*[:\-]\s*(.+)",
        r"M&E\s+indicator\s*[:\-]\s*(.+)",
    ],
    "logframe_target": [
        r"(?:annual|cumulative|indicator)?\s*target\s*[:\-]\s*(.+)",
        r"planned\s+(?:result|output|target)\s*[:\-]\s*(.+)",
        r"(?:project|programme)\s+target\s*[:\-]\s*(.+)",
    ],
    "logframe_achievement": [
        r"(?:actual|cumulative)?\s*achievement\s*[:\-]\s*(.+)",
        r"actual\s+(?:result|output|figure)\s*[:\-]\s*(.+)",
        r"(?:result|output)\s+achieved\s*[:\-]\s*(.+)",
        r"delivered\s*[:\-]\s*(.+)",
        r"number\s+(?:reached|trained|served|treated|supported)\s*[:\-]\s*(.+)",
    ],
    # --- Evidence & Verification ---
    "evidence_description": [
        r"(?:supporting\s+)?evidence\s*(?:description|type|source)?\s*[:\-]\s*(.+)",
        r"data\s+source\s*[:\-]\s*(.+)",
        r"verification\s+(?:source|method|means)\s*[:\-]\s*(.+)",
        r"means\s+of\s+verification\s*[:\-]\s*(.+)",
        r"data\s+collection\s+(?:method|tool|instrument)\s*[:\-]\s*(.+)",
        r"(?:key\s+)?evidence\s+collected\s*[:\-]\s*(.+)",
    ],
    "verifier": [
        r"verified\s+by\s*[:\-]\s*(.+)",
        r"verification\s+by\s*[:\-]\s*(.+)",
        r"implementing\s+(?:organization|organisation|partner|agency)\s*[:\-]\s*(.+)",
        r"submitted\s+by\s*[:\-]\s*(.+)",
        r"prepared\s+by\s*[:\-]\s*(.+)",
        r"(?:MEL|M&E)\s+officer\s*[:\-]\s*(.+)",
    ],
}


def _extract_text_from_file(fname_lower, raw):
    """Extract plain text from a PDF, DOCX, TXT, CSV, PPTX, or XLSX file's raw bytes.

    Returns (text, error_message). On success error_message is "".
    On failure text is "" and error_message describes why.
    """
    import io as _io
    text = ""
    if fname_lower.endswith(".pdf"):
        if not _HAS_PDFPLUMBER:
            return "", "pdfplumber not installed. Run: pip install pdfplumber"
        with _pdfplumber.open(_io.BytesIO(raw)) as _pdf:
            for _pg in _pdf.pages:
                _pt = _pg.extract_text()
                if _pt:
                    text += _pt + "\n"
    elif fname_lower.endswith(".docx"):
        if not _HAS_DOCX:
            return "", "python-docx not installed. Run: pip install python-docx"
        _dobj = _docx.Document(_io.BytesIO(raw))
        text = "\n".join(p.text for p in _dobj.paragraphs)
    elif fname_lower.endswith(".txt") or fname_lower.endswith(".csv"):
        text = raw.decode("utf-8", errors="replace")
    elif fname_lower.endswith(".pptx"):
        if not _HAS_PPTX:
            return "", "python-pptx not installed. Run: pip install python-pptx"
        _prs = _pptx.Presentation(_io.BytesIO(raw))
        text = "\n".join(
            shape.text
            for slide in _prs.slides
            for shape in slide.shapes
            if hasattr(shape, "text") and shape.text.strip()
        )
    elif fname_lower.endswith(".xlsx") or fname_lower.endswith(".xls"):
        if not _HAS_PANDAS:
            return "", "pandas not installed. Run: pip install pandas openpyxl"
        try:
            _sheets = _pd.read_excel(_io.BytesIO(raw), sheet_name=None)
        except Exception as _xl_exc:
            return "", f"Could not read Excel file: {_xl_exc}"
        for _sheet_name, _df in _sheets.items():
            text += f"\n--- Sheet: {_sheet_name} ---\n"
            text += _df.to_string(index=False) + "\n"
    else:
        return "", "Unsupported file type. Upload a PDF, DOCX, TXT, CSV, PPTX, or XLSX."
    return text, ""


def _extract_report_fields(uploaded_file):
    """Rule-based extraction. No AI. Returns (fields, found_list, not_found_list) or (None, error_str, [])."""
    import re as _re
    fname = uploaded_file.name.lower()
    raw = uploaded_file.read()
    text, _err = _extract_text_from_file(fname, raw)
    if _err:
        return None, _err, []
    if not text.strip():
        return None, "Could not extract text. The file may be scanned/image-based.", []
    fields, found, not_found = {}, [], []
    for field, pats in _IRC_PATTERNS.items():
        matched = False
        for pat in pats:
            m = _re.search(pat, text, _re.IGNORECASE)
            if m:
                fields[field] = m.group(1).strip()[:120]
                found.append(field)
                matched = True
                break
        if not matched:
            fields[field] = ""
            not_found.append(field)
    return fields, found, not_found


def _irc_extract_combined(doc_files):
    """Extract and combine text + rule-based fields from one or more uploaded files.

    Returns (full_text, raw_fields, error_message). error_message is "" on success.
    """
    if not doc_files:
        return "", {}, ("No readable text found in this document. Please upload a "
                         "text-based PDF, DOCX, TXT, PPTX, or XLSX — scanned image "
                         "files cannot be extracted.")
    parts = []
    raw_fields = {}
    for f in doc_files:
        f.seek(0)
        text, err = _extract_text_from_file(f.name.lower(), f.read())
        if err:
            return "", {}, f"{f.name}: {err}"
        if not text.strip():
            return "", {}, (f"No readable text found in {f.name}. Please upload a "
                             f"text-based PDF, DOCX, TXT, PPTX, or XLSX — scanned image "
                             f"files cannot be extracted.")
        parts.append(f"--- Document: {f.name} ---\n\n{text}")
        f.seek(0)
        fields, _, _ = _extract_report_fields(f)
        for fk, fv in (fields or {}).items():
            if fv and not raw_fields.get(fk):
                raw_fields[fk] = fv
    return "\n\n".join(parts), raw_fields, ""


def _irc_parse_date(s):
    """Parse YYYY/MM/DD string to date, return None on failure."""
    if not s or s == "Not found":
        return None
    try:
        return date.fromisoformat(s.replace("/", "-"))
    except (ValueError, AttributeError):
        return None


def _irc_match_option(value, options):
    """Fuzzy-match extracted string to a selectbox options list. Returns matched option or None."""
    if not value or value == "Not found":
        return None
    vl = value.lower().strip()
    for opt in options:
        if vl == opt.lower().strip():
            return opt
    for opt in options:
        ol = opt.lower()
        if vl in ol or ol in vl:
            return opt
    vwords = vl.split()
    for opt in options:
        owords = opt.lower().split()
        if vwords and (vwords[0] in owords or (owords and owords[0] in vwords)):
            return opt
    return None
# --- END UX: INSTANT REPORT CHECK (v3.2) ---

EVIDENCE_TYPE_HELP = (
    "Choose the type that best describes your primary evidence document.\n\n"
    "• Attendance sheets / participant registers — Signed records of participants by name, date, and session. "
    "Example: 'Signed attendance sheets from 12 training sessions, names + signatures + dates'\n\n"
    "• Raw datasets or survey exports — Unprocessed data files exported from a survey or data collection tool. "
    "Example: 'KoboToolbox CSV export of 487 farmer surveys; SPSS dataset from baseline survey'\n\n"
    "• Partner verification letters — Formal letters from partner organizations confirming they witnessed or validated the activity. "
    "Example: 'Letter from District Agriculture Officer confirming attendance at all 12 training sessions'\n\n"
    "• Photos with metadata — Photos with embedded GPS, timestamps, and EXIF data proving where and when they were taken. "
    "Example: 'Geotagged photos of borehole installation with date stamps'\n\n"
    "• Tracer survey results — Follow-up surveys conducted weeks/months after the activity to measure actual outcomes. "
    "Example: '3-month tracer survey results showing 65% of trained farmers adopted climate-smart techniques'\n\n"
    "• Financial records — Receipts, payment confirmations, payroll records that prove transactions occurred. "
    "Example: 'Mobile money transfer receipts to 250 farmer cash transfer recipients'\n\n"
    "• Third-party audits — Independent audits or verification reports from external organizations. "
    "Example: 'External audit by SGS Ghana of distribution logistics and beneficiary lists'\n\n"
    "• Case study — An in-depth account of one participant, site, or community, used to illustrate how change happened. "
    "Example: 'Case study of a women's savings group in Tamale showing how loan access changed household decision-making'\n\n"
    "• Outcome harvesting — Outcomes identified after the fact, then worked backwards to assess the program's contribution. "
    "Example: 'Outcome harvesting exercise with district officials identifying 8 policy changes influenced by the program'\n\n"
    "• Beneficiary narrative or testimony — First-person accounts from participants describing the change they experienced. "
    "Example: 'Recorded interviews with 12 farmers describing changes in income and food security after training'\n\n"
    "• Other (specify) — Evidence that doesn't fit any category above. Use sparingly; most evidence fits one of the above."
)

SECTOR_OPTIONS = [
    "(No sector selected)",
    "WASH",
    "Health",
    "Education",
    "Agriculture / Livelihoods",
    "Youth Employment",
    "Climate Resilience",
    "Governance",
    "Other",
]

DONOR_GUIDANCE = {
    "USAID": {
        "key_emphasis": "USAID is governed by ADS 201. Quantitative indicators with verifiable evidence are paramount. Use the 5 USAID DQA standards: Validity, Integrity, Precision, Reliability, Timeliness.",
        "common_rejection": "Results not tied to PIRS (Performance Indicator Reference Sheets) or missing sex/age disaggregation. Always disaggregate by sex, age, and geography.",
        "tip": "USAID requires evidence collected within 12 months for a full Recency score. Evidence older than this should be explicitly flagged and justified.",
    },
    "FCDO": {
        "key_emphasis": "FCDO emphasises Value for Money (VfM) and Theory of Change. Results must connect to outcomes, not just outputs.",
        "common_rejection": "Outputs reported without contribution analysis. Always state how your activities contributed to higher-level outcomes.",
        "tip": "FCDO accepts qualitative evidence if triangulated (Bond Evidence Principles). Triangulation is essential — use at least two independent sources.",
    },
    "GIZ": {
        "key_emphasis": "GIZ uses the Capacity WORKS framework. Results should reflect capacity development at individual, organisational, and system levels.",
        "common_rejection": "Missing reflection on partner capacity. Document partner contributions and capacity gains explicitly in your narrative.",
        "tip": "GIZ values qualitative learning narratives alongside quantitative KPIs. Don't strip out the story — include a lessons-learned section.",
    },
    "RVO": {
        "key_emphasis": "RVO requires logframe-anchored reporting. Every result MUST tie to a Technical Proposal indicator.",
        "common_rejection": "Missing M&E data tied to the original logframe — the #1 RVO rejection cause. Always include a logframe progress table.",
        "tip": "RVO final reports require: narrative + financial + audit + logframe update. Confirm all four are in your submission package before sending.",
    },
    "World Bank": {
        "key_emphasis": "World Bank uses Results Framework Indicators (RFIs) with strict numerical targets. Quantification is non-negotiable.",
        "common_rejection": "Insufficient methodology disclosure. Document data collection methods, sample size, and data source in detail.",
        "tip": "World Bank tier-1 indicators require third-party verification for project budgets above $5M.",
    },
    "AfDB": {
        "key_emphasis": "AfDB Strategy 2024–2033 emphasises 'High 5s' alignment. Connect results to at least one High 5 priority explicitly.",
        "common_rejection": "Results not linked to AfDB strategic pillars or missing country/regional development context.",
        "tip": "AfDB values African-led monitoring and evaluation. Reference AfrEA or African Evidence Network methodology where possible.",
    },
    "EU / EuropeAid": {
        "key_emphasis": "EU follows DG INTPA reporting standards. The Logical Framework Approach (LFA) is the foundation — all results must trace to the logframe.",
        "common_rejection": "Assumptions and risks not updated in the logframe. Always revise the assumptions/risks column when reporting deviations.",
        "tip": "EU expects gender mainstreaming and rights-based analysis to be explicitly visible in results narrative — not just mentioned in passing.",
    },
}

SECTOR_PLACEHOLDERS = {
    "WASH": {
        "result": "e.g., Constructed 25 boreholes serving 12,000 people across 5 districts in Northern Region between January and June 2025",
        "target_group": "e.g., Rural households without access to safe drinking water; women and children primarily responsible for water collection",
        "geographic_scope": "e.g., Tamale, Yendi, Savelugu, Karaga, and Kumbungu districts",
        "evidence_description": "e.g., Borehole functionality reports from 25 sites + water quality test results from district lab + GPS-tagged photos of completed structures",
        "logframe_indicator":   "e.g., Indicator 2.1: Number of households with access to safely managed drinking water",
        "logframe_target":      "e.g., 12,000 households with access by Q4 2025",
        "logframe_achievement": "e.g., 12,000 people reached by June 2025 — 100% of target",
        "verifier":              "e.g., District Water and Sanitation Officer, Water Resource Commission inspector",
    },
    "Health": {
        "result": "e.g., Vaccinated 8,500 children under 5 against measles across 3 health districts in Eastern Region between July and September 2025",
        "target_group": "e.g., Children aged 6 months to 5 years residing in target communities",
        "geographic_scope": "e.g., New Juaben, Suhum, and Akropong health districts",
        "evidence_description": "e.g., Patient records from 3 health facilities + immunization registers signed by district health officer + cold chain monitoring logs",
        "logframe_indicator":   "e.g., Indicator 1.3: % of children under 5 fully immunized in target districts",
        "logframe_target":      "e.g., 85% immunization coverage in 3 districts by Dec 2025",
        "logframe_achievement": "e.g., 8,500 children vaccinated by Sept 2025 — 100% of district target",
        "verifier":              "e.g., District Health Officer, Regional Health Directorate field supervisor",
    },
    "Education": {
        "result": "e.g., Improved literacy scores by 35% among 1,200 primary school students across 15 schools in Central Region between September 2024 and June 2025",
        "target_group": "e.g., Primary school students grades 3-6, ages 8-12, in selected public schools",
        "geographic_scope": "e.g., Cape Coast, Mfantsiman, and Ekumfi districts (15 schools)",
        "evidence_description": "e.g., Pre/post standardized test results + enrollment registers + teacher observation logs + sample of student work",
        "logframe_indicator":   "e.g., Indicator 3.2: % of students achieving minimum reading proficiency",
        "logframe_target":      "e.g., 60% of students at grade-level literacy by June 2025",
        "logframe_achievement": "e.g., 1,200 students with improved literacy scores by June 2025 — 100% of target",
        "verifier":              "e.g., Ghana Education Service district inspector, headteacher certification",
    },
    "Agriculture / Livelihoods": {
        "result": "e.g., Trained 487 smallholder farmers in climate-smart agriculture across 3 districts in Northern Ghana between January and June 2025",
        "target_group": "e.g., Smallholder farmers (18–60 years), majority women, with land holdings under 2 hectares",
        "geographic_scope": "e.g., Tamale, Yendi, Savelugu districts (Northern Region)",
        "evidence_description": "e.g., Signed attendance sheets from 12 training sessions across 3 districts, verified by District Agriculture Officer + farmer cooperative records",
        "logframe_indicator":   "e.g., Indicator 2.4: Number of smallholder farmers trained in climate-smart practices",
        "logframe_target":      "e.g., 400 farmers trained by Q4 2025",
        "logframe_achievement": "e.g., 487 farmers trained by June 2025 — 97% of target",
        "verifier":              "e.g., District Agriculture Officer, partner org M&E lead, external evaluator",
    },
    "Youth Employment": {
        "result": "e.g., Provided vocational training to 250 unemployed youth in IT and entrepreneurship across Accra and Kumasi from January to March 2026",
        "target_group": "e.g., Unemployed youth aged 18-35, with secondary school qualifications, residing in urban areas",
        "geographic_scope": "e.g., Accra (Greater Accra Region) and Kumasi (Ashanti Region)",
        "evidence_description": "e.g., Signed attendance sheets for all 10 training modules + digital certificates issued to 245 graduates + 3-month tracer survey results + employment contracts",
        "logframe_indicator":   "e.g., Indicator 1.2: Number of unemployed youth completing vocational training",
        "logframe_target":      "e.g., 250 youth trained by Q4 2025",
        "logframe_achievement": "e.g., 250 youth completed training by March 2026 — 100% of target",
        "verifier":              "e.g., COTVET assessor, employer sign-off, training provider certification",
    },
    "Climate Resilience": {
        "result": "e.g., Established 50 community-managed weather stations across 10 coastal communities in Volta Region between March and December 2025",
        "target_group": "e.g., Coastal fishing and farming communities vulnerable to climate-related disasters",
        "geographic_scope": "e.g., Keta, Anloga, Ada East, and Ada West districts (Volta Region)",
        "evidence_description": "e.g., Installation logs + GPS coordinates of all stations + community management committee meeting minutes + monthly data collection reports",
        "logframe_indicator":   "e.g., Indicator 4.1: Number of community-managed early-warning systems established",
        "logframe_target":      "e.g., 50 weather stations operational by Dec 2025",
        "logframe_achievement": "e.g., 50 weather stations operational by Dec 2025 — 100% of target",
        "verifier":              "e.g., Environmental Protection Agency inspector, community committee chair",
    },
    "Governance": {
        "result": "e.g., Trained 180 district-level officials on participatory budgeting processes across 6 districts between April and August 2025",
        "target_group": "e.g., Elected district assembly members, district planning officers, and civil society representatives",
        "geographic_scope": "e.g., 6 selected districts in Ashanti, Eastern, and Western regions",
        "evidence_description": "e.g., Training attendance records + pre/post knowledge assessments + signed certificates of completion + post-training participatory budget reports from 4 districts",
        "logframe_indicator":   "e.g., Indicator 3.3: Number of officials trained in participatory budgeting",
        "logframe_target":      "e.g., 150 district officials trained by Aug 2025",
        "logframe_achievement": "e.g., 180 officials trained by Aug 2025 — 100% of target",
        "verifier":              "e.g., District Coordinating Director, civil society observer, auditor-general representative",
    },
    "Other": {
        "result": "e.g., [Action verb] [number] [target population] in [location] between [start date] and [end date]",
        "target_group": "e.g., Women 18–35, rural community health workers in 3 districts",
        "geographic_scope": "e.g., Ashanti Region — Kumasi, Obuasi, and Bekwai districts",
        "evidence_description": "e.g., Type of records + who collected them + how they were verified + any third-party validation",
        "logframe_indicator":   "e.g., Indicator [X.X]: [Indicator name from approved Technical Proposal or logframe]",
        "logframe_target":      "e.g., [Number + unit + deadline from logframe]",
        "logframe_achievement": "e.g., [Actual delivered number] by [date] — [%] of original target",
        "verifier":              "e.g., [Implementing partner M&E lead], [government line ministry], [external evaluator]",
    },
}

def _render_readiness_banner(diag_state: str):
    band = _READINESS_BAND.get(diag_state, "Needs Work")
    style = _READINESS_STYLE[band]
    _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"
    st.markdown(
        f"<div class='readiness-banner' style='background:{style['bg']};{_pca}'>"
        f"{style['icon']} {band} &mdash; {style['caption']}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(_LIMITS_DISCLAIMER)


INTERNAL_REVIEW_OPTIONS = [
    "Choose an option...",
    "Reviewed by MEL Officer",
    "Collected only (no review)",
    "Not reviewed",
    "Other",
]

EXTERNAL_REVIEW_OPTIONS = [
    "Choose an option...",
    "Verified by independent third party",
    "External partner review",
    "No external review",
    "Other",
]

TRACEABILITY_OPTIONS = [
    "Choose an option...",
    "Yes — an auditor could retrieve the original records",
    "Partially — some records would take effort to locate",
    "No / not sure",
]

PROVENANCE_YES_NO_NA_OPTIONS = [
    "Choose an option...",
    "Yes",
    "No",
    "Not applicable",
]

# ---------------------------------------------------------------------------
# Portfolio / Framework Dashboard — CSV/Excel column schema
# ---------------------------------------------------------------------------

# (column_name, required, example value for the downloadable template)
_PORTFOLIO_COLUMNS = [
    ("indicator_name",       True,  "Indicator 2.1: Households with access to safe water"),
    ("result_statement",     True,  "Installed 12 community boreholes serving 3,400 people across 4 districts in Northern Region between Jan-Jun 2025."),
    ("target_group",         True,  "Rural households"),
    ("timeframe",            True,  "January–June 2025"),
    ("geographic_scope",     True,  "4 districts, Northern Region"),
    ("evidence_type",        True,  "Attendance sheets / participant registers"),
    ("evidence_description", True,  "Borehole completion certificates and community handover registers, signed by District Water Officer."),
    ("evidence_date",        False, "June 2025"),
    ("internal_review",      False, "Reviewed by MEL Officer"),
    ("external_review",      False, "No external review"),
    ("verifier",             False, "District Water Officer"),
    ("logframe_indicator",   False, "Indicator 2.1: Number of households with access to safely managed drinking water"),
    ("logframe_target",      False, "3,000 households"),
    ("logframe_achievement", False, "3,400 households"),
    ("learning_notes",       False, ""),
    ("limitations_notes",    False, ""),
    ("qual_sourcing_documented", False, "FALSE"),
    ("qual_triangulated",        False, "FALSE"),
    ("qual_bias_considered",     False, "FALSE"),
    ("qual_beneficiary_voice_represented", False, "FALSE"),
    ("qual_consent_ethics_addressed",      False, "FALSE"),
]

# Accepted values for internal_review / external_review (unrecognized values
# default to 0, same as evaluate_submission()'s own fallback).
_PORTFOLIO_REVIEW_HINT = (
    "internal_review accepts: 'Reviewed by MEL Officer', 'Collected only (no review)', "
    "'Not reviewed'. external_review accepts: 'Verified by independent third party', "
    "'External partner review', 'No external review'. Leave blank to default to "
    "'Not reviewed' / 'No external review'."
)

SUBMISSION_CHECKLIST = {
    "Project proposal": [
        ("cl_proposal",       "Narrative / technical proposal"),
        ("cl_budget",         "Budget / financial plan"),
        ("cl_logframe",       "Logframe / results framework"),
        ("cl_annexes",        "Annexes (supporting docs)"),
        ("cl_implementation", "Implementation plan"),
        ("cl_org_docs",       "Organisational documents"),
    ],
    "Baseline report": [
        ("cl_methodology",    "Baseline methodology & tools"),
        ("cl_findings",       "Baseline findings report"),
        ("cl_disaggregated",  "Disaggregated / beneficiary data"),
        ("cl_logframe",       "Updated indicators / logframe"),
        ("cl_annexes",        "Annexes with tools or datasets"),
    ],
    "Quarterly progress report": [
        ("cl_narrative",      "Narrative / technical report"),
        ("cl_logframe",       "Updated logframe with achievements"),
        ("cl_disaggregated",  "Beneficiary / disaggregated data"),
        ("cl_annexes",        "Annexes / evidence"),
        ("cl_variance",       "Budget variance report (if requested)"),
    ],
    "Annual progress report": [
        ("cl_narrative",      "Narrative / technical report"),
        ("cl_financial",      "Financial report"),
        ("cl_logframe",       "Updated logframe with achievements"),
        ("cl_disaggregated",  "Beneficiary / disaggregated data"),
        ("cl_annexes",        "Annexes / evidence"),
        ("cl_sustainability", "Sustainability / next-step plan"),
    ],
    "Mid-term review": [
        ("cl_findings",       "Review / field verification report"),
        ("cl_logframe",       "Progress against logframe"),
        ("cl_annexes",        "Annexes / evidence"),
        ("cl_action_plan",    "Action plan (if required)"),
    ],
    "End-line evaluation": [
        ("cl_evaluation",     "Evaluation report"),
        ("cl_methodology",    "Methodology documentation"),
        ("cl_findings",       "Findings with disaggregated outcomes"),
        ("cl_annexes",        "Annexes / evidence"),
        ("cl_learning",       "Learning / dissemination summary"),
    ],
    "Final/closeout report": [
        ("cl_narrative",      "Final narrative report"),
        ("cl_financial",      "Final financial report"),
        ("cl_audit",          "Audit report (if required)"),
        ("cl_logframe",       "Updated logframe / achievements"),
        ("cl_disaggregated",  "Beneficiary / disaggregated data"),
        ("cl_sustainability", "Sustainability / exit plan"),
        ("cl_annexes",        "Annexes"),
    ],
    "Financial report": [
        ("cl_expense_summary","Expense summary"),
        ("cl_variance",       "Budget vs actual / variance explanation"),
        ("cl_schedules",      "Supporting financial schedules"),
        ("cl_bank_recon",     "Bank / ledger reconciliation"),
    ],
    "MEL plan": [
        ("cl_indicators",     "Indicators & targets"),
        ("cl_data_sources",   "Data sources & collection methods"),
        ("cl_reporting_cal",  "Reporting calendar"),
        ("cl_roles",          "Roles & responsibilities"),
        ("cl_data_quality",   "Data quality procedures"),
        ("cl_methodology",    "Data collection tools / methodology"),
    ],
    "Others (Special/Ad-hoc reports)": [
        ("cl_narrative",      "Narrative / technical report"),
        ("cl_annexes",        "Donor-specific annexes"),
        ("cl_case_studies",   "Case studies / special studies"),
        ("cl_safeguarding",   "Safeguarding / compliance reports"),
    ],
}

# "Strengthen this evidence" checklist items, keyed by evidence type (v3.6 IRC auto-fill)
EVIDENCE_STRENGTHEN_CHECKLIST = {
    "Attendance sheets / participant registers": [
        ("signatures_verified", "Signatures verified against ID list"),
        ("date_stamped",        "Sheets dated and stamped"),
        ("cross_ref",           "Cross-referenced with another source (e.g., facilitator notes)"),
    ],
    "Raw datasets or survey exports": [
        ("sample_doc",   "Sampling method documented"),
        ("clean_data",   "Dataset cleaned and de-duplicated"),
        ("version_ctrl", "Original raw export retained for audit"),
    ],
    "Partner verification letters": [
        ("letterhead",       "Letter on official partner letterhead"),
        ("authority_signed", "Signed by authorized partner representative"),
        ("recent_letter",    "Letter dated within 6 months of reporting period"),
    ],
    "Photos with metadata": [
        ("gps_meta",       "Photos contain GPS metadata"),
        ("timestamp_photo","Timestamps visible/verifiable"),
        ("consent_photo",  "Beneficiary consent obtained for photos"),
    ],
    "Tracer survey results": [
        ("followup_tracer", "Follow-up conducted at appropriate interval (3+ months)"),
        ("response_rate",   "Response rate documented (target: 60%+)"),
        ("bias_ack",        "Sampling bias / non-response acknowledged"),
    ],
    "Financial records": [
        ("receipts_dated", "Receipts/transactions dated"),
        ("reconciled_ev",  "Reconciled with bank/MoMo statements"),
        ("audit_trail_ev", "Audit trail intact (request → approval → payment)"),
    ],
    "Third-party audits": [
        ("independent_ev",     "Auditor independent from implementer"),
        ("signed_audit",       "Audit report signed and dated"),
        ("recommendations_ev", "Audit recommendations addressed/disclosed"),
    ],
}

# ---------------------------------------------------------------------------
# CSS — injected once at app load
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=JetBrains+Mono:wght@400&display=swap');

:root {
  --brand-green: #1B5E20;
  --gold:        #8A6500;
  --body-text:   #212121;
  --muted:       #616161;
  --bg-card:     #F5F5F5;
  --border:      rgba(27,90,32,0.15);
}

/* Dark mode card text — keep with !important */
.is-col, .is-col li, .is-col ul, .is-col h4 {
    color: #1B5E20 !important;
}
.isnot-col, .isnot-col li, .isnot-col ul, .isnot-col h4 {
    color: #C62828 !important;
}
.what-we-check {
    background: #F1F8E9 !important;
}
.what-we-check, .what-we-check li, .what-we-check ul,
.what-we-check h4, .what-we-check strong {
    color: #1B5E20 !important;
}

html, body, [class*="css"] {
  font-family: 'Inter', sans-serif;
  color: var(--body-text);
}

h1, h2, h3, h4 {
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  color: var(--brand-green);
}

/* Primary button -> Impact Green */
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
  background-color: #1B5E20 !important;
  border-color: #1B5E20 !important;
  color: white !important;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  border-radius: 8px;
}

/* Secondary button -> Trust Gold outline */
.stButton > button[kind="secondary"],
.stFormSubmitButton > button[kind="secondary"] {
  border-color: #8A6500 !important;
  color: #8A6500 !important;
  font-family: 'Inter', sans-serif;
  background: transparent !important;
}

/* Card container */
.result-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 20px;
}

/* Axis score badge */
.axis-badge {
  padding: 10px 14px;
  border-radius: 8px;
  text-align: center;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  font-size: 0.85rem;
  margin-bottom: 6px;
}

/* Verdict banner */
.verdict-banner {
  background: #1B5E20;
  color: white;
  border-radius: 10px;
  padding: 14px 20px;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  text-align: center;
  margin: 16px 0;
  font-size: 1rem;
}
.verdict-banner.misleading { background: #E65100; }
.verdict-banner.weak-conf  { background: #F57F17; }
.verdict-banner.high-risk  { background: #B71C1C; }

/* Progress steps row */
.progress-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 24px;
  font-family: 'Inter', sans-serif;
  font-size: 0.85rem;
  color: var(--body-text);
}
.progress-steps .step {
  background: #1B5E20;
  color: white;
  border-radius: 50%;
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}
.progress-steps .connector {
  flex: 1;
  height: 2px;
  background: #CCCCCC;
  max-width: 40px;
}
.progress-steps .step-label { font-weight: 500; }

/* Hero section */
.hero-block {
  padding: 12px 0 20px 0;
  border-bottom: 1px solid #8A6500;
  margin-bottom: 20px;
}
.hero-block h1 {
  font-size: 1.85rem;
  line-height: 1.25;
  margin-bottom: 8px;
}
.hero-tagline {
  font-style: italic;
  color: #8A6500;
  font-size: 1rem;
  margin: 4px 0 14px 0;
}
.hero-sub {
  font-size: 1rem;
  color: #374151;
  line-height: 1.6;
  margin-bottom: 6px;
}
.brand-promise {
  color: #616161;
  font-size: 0.92rem;
  line-height: 1.6;
  margin-top: 6px;
  margin-bottom: 0;
}

/* IS / IS NOT table */
.is-not-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 20px 0;
  align-items: stretch;
}
.is-col, .isnot-col { padding: 16px 20px; border-radius: 10px; }
.is-col   { background: #EDF7F1; border: 1px solid #A7D9BC; }
.isnot-col { background: #FEF3F2; border: 1px solid #FCA5A5; }
.is-col h4   { color: var(--brand-green); margin: 0 0 10px 0; }
.isnot-col h4 { color: #991B1B; margin: 0 0 10px 0; }
.is-col li, .isnot-col li { margin-bottom: 6px; font-size: 0.9rem; }

/* CTA call button */
.cta-call-btn a {
  display: inline-block;
  background: #8A6500;
  color: white !important;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  padding: 10px 20px;
  border-radius: 8px;
  text-decoration: none;
  font-size: 0.95rem;
}

/* Trust Gold tagline footer */
.trust-tagline {
  font-style: italic;
  color: #8A6500;
  font-size: 0.82rem;
  text-align: center;
  padding: 12px 0 4px 0;
  border-top: 1px solid rgba(138,101,0,0.2);
  margin-top: 24px;
}

/* GTM conversion hook card */
.gtm-card {
  border: 1px solid #8A6500;
  border-radius: 10px;
  padding: 20px 24px;
  margin: 24px 0;
  background: #FFFEF7;
}
.gtm-card p { color: #212121; font-size: 0.95rem; margin: 0 0 4px 0; }
.gtm-card .gtm-sub { color: #616161; font-size: 0.85rem; margin-bottom: 14px; }

/* GTM buttons */
.gtm-btn-gold a {
  display: inline-block;
  border: 2px solid #8A6500;
  color: #8A6500 !important;
  padding: 8px 18px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 700;
  font-size: 0.9rem;
  font-family: 'Inter', sans-serif;
  margin-right: 10px;
}

/* Gold info box */
.gold-info-box {
  background: #FFFEF7;
  border-left: 4px solid #8A6500;
  padding: 10px 16px;
  border-radius: 6px;
  font-size: 0.9rem;
  color: #212121;
  margin: 12px 0;
}
.gold-info-box a { color: #1B5E20; }

/* Score metric font */
[data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace; }

/* Diagnostic state badge */
.diagnostic-badge {
  padding: 10px 16px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 1rem;
  margin-bottom: 12px;
  display: inline-block;
  letter-spacing: 0.02em;
}

/* Top-line "is this good enough to submit?" banner */
.readiness-banner {
  padding: 14px 20px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 1.1rem;
  margin-bottom: 12px;
  color: #FFFFFF;
  text-align: center;
}

/* Mobile-first improvements */
@media (max-width: 768px) {
  .stButton button {
    min-height: 48px !important;
    font-size: 16px !important;
    padding: 12px 16px !important;
  }
  .stTextInput input, .stTextArea textarea,
  .stSelectbox div[role="combobox"] {
    min-height: 44px !important;
    font-size: 16px !important;
  }
  .main .block-container {
    padding-left: 1rem !important;
    padding-right: 1rem !important;
  }
  .stTabs [data-baseweb="tab-list"] {
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
  }
  .stCheckbox label {
    min-height: 36px !important;
    display: flex !important;
    align-items: center !important;
  }
}
/* Active tab: bold + underline */
.stTabs [data-baseweb="tab"][aria-selected="true"] button {
    font-weight: 700;
    text-decoration: underline;
}
/* Form labels: consistent weight */
.stTextInput label, .stTextArea label, .stSelectbox label,
.stDateInput label, .stFileUploader label, .stNumberInput label {
    font-size: 0.875rem !important;
    font-weight: 600 !important;
}
</style>
"""

# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _init_session_state():
    defaults = {
        "screen":              0,
        "error_message":       None,
        "evaluations":         None,
        "submissions_snapshot": None,
        "active_slots":        1,
        "has_seen_tutorial":   False,
        "tutorial_step":       0,
        "sector":              SECTOR_OPTIONS[0],
        "confirm_reset":       False,
        "gov_dpp_uploaded":    False,
        "lite_mode":           False,
        # --- UX (v3.2) ---
        "current_tab":         0,
        "remembered_donor":    "",
        "remembered_sector":   "",
        # --- END UX (v3.2) ---
        # --- v3.3 additions ---
        "donor_other":         "",
        "donor_framework":     "Generic",
        # --- auth / payment ---
        "user_email":          "",
        "is_paid":             False,
        "consent_examples":    False,
        "_pay_once_url":       "",
        "_pay_monthly_url":    "",
        # --- end auth ---
        "report_level":        "(Not specified)",
        "report_prepared_by":  "",
        "report_status":       _REPORT_STATUS_OPTIONS[0],
        "report_notes":        "",
        "_tab1_auto_advanced": False,
        "_tab2_auto_advanced": False,
        # --- END v3.3 ---
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


_BASE_FORM_KEYS = [
    "result_statement", "target_group", "timeframe", "geographic_scope",
    "evidence_description", "evidence_type", "evidence_type_other",
    "internal_review", "internal_review_other",
    "external_review", "external_review_other",
    "verifier", "sector", "sector_other", "beneficiary_voice",
    "logframe_indicator", "logframe_target", "logframe_achievement",
    # evidence sub-prompt checkboxes (informational, v3.3)
    "signatures_verified", "date_stamped", "cross_ref",
    "sample_doc", "clean_data", "version_ctrl",
    "letterhead", "authority_signed", "recent_letter",
    "gps_meta", "timestamp_photo", "consent_photo",
    "followup_tracer", "response_rate", "bias_ack",
    "receipts_dated", "reconciled_ev", "audit_trail_ev",
    "independent_ev", "signed_audit", "recommendations_ev",
    # governance & compliance (v3.2)
    "gov_consent_status", "gov_anonymization_status", "gov_compliance_law_status",
    "gov_safeguarding_status", "gov_child_safeguarding_status", "gov_secure_handling_status",
    # v3.3
    "donor_other", "report_level",
    # v3.3 checklist keys
    "cl_proposal", "cl_implementation", "cl_org_docs", "cl_methodology",
    "cl_findings", "cl_disaggregated", "cl_variance", "cl_action_plan",
    "cl_evaluation", "cl_learning", "cl_expense_summary", "cl_schedules",
    "cl_bank_recon", "cl_indicators", "cl_data_sources", "cl_reporting_cal",
    "cl_roles", "cl_data_quality", "cl_case_studies", "cl_safeguarding",
    "cl_beneficiary",
    # v3.4 advisory checklist (optional, score-neutral)
    "attribution_contribution", "disaggregation_status",
    # v3.5 learning / limitations / decision-ownership notes
    "learning_notes", "limitations_notes", "additional_context",
    # v3.6 review-handoff layer (per-submission, no auth)
    "review_status", "reviewer_name", "reviewer_role", "reviewer_date",
    "reviewer_decision", "reviewer_notes",
]

# v3.6 — Review-handoff layer: per-submission status and reviewer decision.
# No user accounts / authentication — reviewer identity is free text within
# the current session, consistent with the rest of the app's single-session model.
_SUBMISSION_STATUS_OPTIONS = ["Draft", "In review", "Approved", "Returned"]
_REVIEW_DECISION_OPTIONS = ["", "Approve", "Return for revision"]
_SUBMISSION_STATUS_COLORS = {
    "Draft":      ("#F5F5F5", "#616161"),
    "In review":  ("#FFF9C4", "#F57F17"),
    "Approved":   ("#C8E6C9", "#1B5E20"),
    "Returned":   ("#FFE0B2", "#E65100"),
}

_BV_OPTIONS = [
    "Choose an option...",
    "No beneficiary voice captured",
    "Direct beneficiary feedback collected (e.g., Lean Data survey, focus groups, NPS)",
    "Beneficiary representatives consulted (community leaders, beneficiary committees)",
    "Anecdotal beneficiary quotes only (uncollected, not systematic)",
    "Not applicable to this result type",
]


def _slot_suffix(slot: int) -> str:
    return "" if slot == 1 else f"_{slot}"


def _reset_all_slots():
    active = st.session_state.get("active_slots", 1)
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        for k in _BASE_FORM_KEYS:
            st.session_state.pop(f"{k}{s}", None)
        for k in ["evidence_date", "uploaded_files", "draft_uploaded_filenames"]:
            st.session_state.pop(f"{k}{s}", None)
    for k in ["active_slots", "evaluations", "submissions_snapshot",
              "evaluation", "submission_snapshot", "error_message", "active_slots_run",
              "_tab1_auto_advanced", "_tab2_auto_advanced"]:
        st.session_state.pop(k, None)


def _go_to_screen(screen: int, reset: bool = False):
    if reset:
        _reset_all_slots()
        if screen == 1:
            _load_draft()
    st.session_state["screen"] = screen
    st.rerun()


# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------

def _render_tagline_footer():
    st.markdown(
        '<div class="trust-tagline">Stress-test a result before you submit it.</div>',
        unsafe_allow_html=True,
    )


def _format_date(d) -> str:
    """Convert date/datetime to 'Month YYYY' string for evaluator."""
    if d is None:
        return ""
    if hasattr(d, "strftime"):
        return d.strftime("%B %Y")
    return str(d)


def _ss_str(key: str, default: str = "") -> str:
    """Read a session_state value as a string, tolerating non-string values
    (e.g. a number or list accidentally written by IRC extraction)."""
    val = st.session_state.get(key, default)
    if isinstance(val, str):
        return val
    return default if val is None else str(val)


_DRAFT_PATH = os.path.join("inputs", "draft.json")


def _save_draft():
    active = st.session_state.get("active_slots", 1)
    draft = {"active_slots": active}
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        for k in _BASE_FORM_KEYS:
            draft[f"{k}{s}"] = st.session_state.get(f"{k}{s}", "")
        ed = st.session_state.get(f"evidence_date{s}")
        draft[f"evidence_date{s}"] = ed.isoformat() if hasattr(ed, "isoformat") else ""
        raw_files = st.session_state.get(f"uploaded_files_widget{s}") or []
        draft[f"uploaded_filenames{s}"] = [f.name for f in raw_files if hasattr(f, "name")]
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        for dk in ("reporting_start", "reporting_end"):
            d = st.session_state.get(f"{dk}{s}")
            draft[f"{dk}{s}"] = d.isoformat() if hasattr(d, "isoformat") else ""
    # --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
    for _gs in range(1, active + 1):
        _s = _slot_suffix(_gs)
        for _gk in ["gov_consent_status", "gov_anonymization_status", "gov_compliance_law_status"]:
            draft[f"{_gk}{_s}"] = st.session_state.get(f"{_gk}{_s}", "")
    draft["gov_dpp_uploaded"] = st.session_state.get("gov_dpp_uploaded", False)
    # --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
    for gk in ("submission_type", "cl_narrative", "cl_financial", "cl_audit",
               "cl_logframe", "cl_annexes", "cl_beneficiary", "cl_sustainability",
               "cl_budget", "donor_selected", "donor_other"):
        draft[gk] = st.session_state.get(gk, "")
    os.makedirs("inputs", exist_ok=True)
    with open(_DRAFT_PATH, "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)
    st.session_state["_last_saved_time"] = datetime.now().strftime("%H:%M")


def _load_draft():
    if not os.path.exists(_DRAFT_PATH):
        return
    try:
        with open(_DRAFT_PATH, encoding="utf-8") as f:
            draft = json.load(f)
    except Exception:
        return
    active = int(draft.get("active_slots", 1))
    st.session_state["active_slots"] = active
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        for k in _BASE_FORM_KEYS:
            key = f"{k}{s}"
            if key in draft:
                st.session_state[key] = draft[key]
        raw_date = draft.get(f"evidence_date{s}", "")
        if raw_date:
            try:
                st.session_state[f"evidence_date{s}"] = date.fromisoformat(raw_date)
            except (ValueError, TypeError):
                pass
        st.session_state[f"draft_uploaded_filenames{s}"] = draft.get(f"uploaded_filenames{s}", [])
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        for dk in ("reporting_start", "reporting_end"):
            raw = draft.get(f"{dk}{s}", "")
            if raw:
                try:
                    st.session_state[f"{dk}{s}"] = date.fromisoformat(raw)
                except (ValueError, TypeError):
                    pass
    for gk in ("submission_type", "cl_narrative", "cl_financial", "cl_audit",
               "cl_logframe", "cl_annexes", "cl_beneficiary", "cl_sustainability",
               "cl_budget", "donor_selected", "donor_other"):
        if gk in draft:
            st.session_state[gk] = draft[gk]


def _clear_draft():
    if os.path.exists(_DRAFT_PATH):
        os.remove(_DRAFT_PATH)


# ---------------------------------------------------------------------------
# Tutorial renderer
# ---------------------------------------------------------------------------

_TUTORIAL_COPY = {
    1: {
        "title": "📝 Each field below contributes to your score.",
        "body": (
            "Watch the **Live Score Preview** panel (Review & Submit tab) update as you type.\n"
            "We'll show you exactly which inputs boost which scores."
        ),
    },
    2: {
        "title": "🎯 Your result is now scored on two axes:",
        "body": (
            "• **Confidence:** How much we should trust the evidence\n"
            "• **Clarity:** How clearly the result is defined\n\n"
            "Both must be **Strong (≥4.0)** to reach this tool's top band.\n\n"
            "The **What to Fix** section tells you exactly how to improve."
        ),
    },
    3: {
        "title": "📄 Download your report and submit it to your donor.",
        "body": (
            "Use the **Download HTML Report** or **Download PDF Report** buttons below "
            "to get a shareable copy of your results.\n\n"
            "Used your free checks? Upgrade options (pay-per-check or monthly) appear "
            "wherever you've reached the free-check limit."
        ),
    },
}

_TUTORIAL_LAST_STEP = max(_TUTORIAL_COPY)


def _render_tutorial(step: int):
    if st.session_state.get("has_seen_tutorial") or st.session_state.get("tutorial_step", 0) > step:
        return
    copy = _TUTORIAL_COPY.get(step)
    if not copy:
        return
    st.caption(f"💡 **{copy['title']}** — {copy['body']}")
    if st.button("Got it →", key=f"tutorial_got_{step}"):
        if step == _TUTORIAL_LAST_STEP:
            st.session_state["has_seen_tutorial"] = True
        st.session_state["tutorial_step"] = step + 1
        st.rerun()


# ---------------------------------------------------------------------------
# Live score preview
# ---------------------------------------------------------------------------

# --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
def _minors_possibly_involved(slot: int) -> bool:
    """True if the result statement or target group mentions minors — used only
    to decide whether to prompt the child-safeguarding question, never to
    auto-answer it."""
    s = _slot_suffix(slot)
    text = " ".join([
        st.session_state.get(f"result_statement{s}", "") or "",
        st.session_state.get(f"target_group{s}", "") or "",
    ]).lower()
    return any(kw in text for kw in CHILD_SAFEGUARDING_KEYWORDS)


def _compute_governance_score(slot: int):
    """Returns (governance_score 0-24, pii_selected bool, gaps list,
    safeguarding_triggered bool, minors_possibly_involved bool)."""
    s = _slot_suffix(slot)
    ev_type = st.session_state.get(f"evidence_type{s}", "")
    pii_selected = ev_type in PII_EVIDENCE_TYPES
    safeguarding_triggered = ev_type in SAFEGUARDING_EVIDENCE_TYPES
    minors_involved = _minors_possibly_involved(slot)

    consent    = st.session_state.get(f"gov_consent_status{s}", "")
    anon       = st.session_state.get(f"gov_anonymization_status{s}", "")
    law        = st.session_state.get(f"gov_compliance_law_status{s}", "")
    safeguard  = st.session_state.get(f"gov_safeguarding_status{s}", "")
    child_safe = st.session_state.get(f"gov_child_safeguarding_status{s}", "")
    secure     = st.session_state.get(f"gov_secure_handling_status{s}", "")
    dpp        = st.session_state.get("gov_dpp_uploaded", False)

    score = 0
    gaps  = []

    if consent in ("Choose an option...", "Select consent status..."):
        pass  # 0 pts, no gap — user has not answered yet
    elif consent == "Yes — written consent forms on file":
        score += 5
    elif consent == "Yes — verbal consent documented":
        score += 3
    elif consent.startswith("Partial"):
        score += 1
    elif consent.startswith("Not applicable"):
        score += 3
    else:
        gaps.append("Consent not obtained")

    if anon in ("Choose an option...", "Select anonymization status..."):
        pass  # 0 pts, no gap
    elif anon == "Yes — fully anonymized":
        score += 4
    elif anon == "Partially anonymized":
        score += 2
    elif anon == "Not applicable":
        score += 3
    else:
        gaps.append("Evidence not anonymized")

    if law in ("Choose an option...", "Select compliance status..."):
        pass  # 0 pts, no gap
    elif law.startswith("Yes"):
        score += 3
    elif law.startswith("Unsure"):
        score += 1
    elif law.startswith("No"):
        gaps.append("Data law compliance not confirmed")

    if safeguard in ("Choose an option...", "Select safeguarding status..."):
        pass  # 0 pts, no gap
    elif safeguard.startswith("Yes"):
        score += 3
    elif safeguard.startswith("Partial"):
        score += 1
    elif safeguard.startswith("Not applicable"):
        score += 3
    elif safeguard.startswith("No"):
        gaps.append("Do-no-harm review not completed (Core Humanitarian Standard, Commitment 4)")

    if child_safe in ("Choose an option...", "Select child safeguarding status..."):
        pass  # 0 pts, no gap
    elif child_safe.startswith("Yes"):
        score += 3
    elif child_safe.startswith("Partial"):
        score += 1
    elif child_safe.startswith("Not applicable"):
        score += 3
    elif child_safe.startswith("No"):
        gaps.append("Child safeguarding review not completed (Core Humanitarian Standard, Commitment 4 — Keeping Children Safe)")

    if secure in ("Choose an option...", "Select secure handling status..."):
        pass  # 0 pts, no gap
    elif secure.startswith("Yes"):
        score += 3
    elif secure.startswith("Partial"):
        score += 1
    elif secure.startswith("Not applicable"):
        score += 3
    elif secure.startswith("No"):
        gaps.append("Secure handling of identifiable testimony not confirmed (Bond Evidence Principles 2024 — Transparency/Data Protection)")

    if dpp:
        score += 5

    return min(24, score), pii_selected, gaps, safeguarding_triggered, minors_involved
# --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---


def _render_paywall(irc_context: bool = False):
    """Show upgrade/payment options. irc_context=True suppresses the free-checks header."""
    email = st.session_state.get("user_email", "")
    if not irc_context:
        st.error(f"🔒 You've used all {FREE_CHECKS_LIMIT} free checks.")
        st.markdown(
            "Upgrade to run more checks and unlock the Instant Report Check "
            "(AI-powered auto-fill from uploaded documents)."
        )
    _c1, _c2 = st.columns(2)
    with _c1:
        st.markdown(f"**Pay-per-use:** GHS {PRICE_PER_CHECK_GHS/100:.0f}")
        if st.session_state.get("_pay_once_url"):
            st.link_button("Complete Payment →", st.session_state["_pay_once_url"],
                           use_container_width=True, type="primary")
        elif st.button("Pay for 1 Check", key="pay_once", use_container_width=True):
            with st.spinner("Preparing payment link…"):
                _url = initialize_payment(email, PRICE_PER_CHECK_GHS, "per_use")
            if _url:
                st.session_state["_pay_once_url"] = _url
                st.rerun()
            else:
                _detail = last_payment_error()
                st.error(f"Payment service unavailable. Try again shortly.{' (' + _detail + ')' if _detail else ''}")
    with _c2:
        st.markdown(f"**Monthly unlimited:** GHS {PRICE_MONTHLY_GHS/100:.0f}/month")
        if st.session_state.get("_pay_monthly_url"):
            st.link_button("Complete Payment →", st.session_state["_pay_monthly_url"],
                           use_container_width=True, type="primary")
        elif st.button("Subscribe Monthly", key="pay_monthly", use_container_width=True):
            with st.spinner("Preparing payment link…"):
                _url = initialize_payment(email, PRICE_MONTHLY_GHS, "monthly")
            if _url:
                st.session_state["_pay_monthly_url"] = _url
                st.rerun()
            else:
                _detail = last_payment_error()
                st.error(f"Payment service unavailable. Try again shortly.{' (' + _detail + ')' if _detail else ''}")


def _subscore_chart(items):
    """Build an interactive horizontal bar chart of sub-scores with hover tooltips.

    items: list of (label, score, max_val, detail) tuples.
    """
    import pandas as pd
    import altair as alt

    rows = []
    for label, score, max_val, detail in items:
        pct = round(min(score / max_val, 1.0) * 100, 1) if max_val else 0.0
        status = "Strong" if pct >= 75 else ("Acceptable" if pct >= 50 else "Below target")
        rows.append({
            "Component": label, "Score": score, "Max": max_val,
            "% of target": pct, "Status": status,
            "Detail": (detail or "").split("\n\n")[0],
        })
    df = pd.DataFrame(rows)

    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("% of target:Q", scale=alt.Scale(domain=[0, 100]), title="% of target"),
            y=alt.Y("Component:N", sort=None, title=None),
            color=alt.Color(
                "Status:N",
                scale=alt.Scale(
                    domain=["Strong", "Acceptable", "Below target"],
                    range=["#1B5E20", "#8A6500", "#C62828"],
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("Component:N", title="Component"),
                alt.Tooltip("Score:Q", title="Score", format=".2f"),
                alt.Tooltip("Max:Q", title="Max", format=".2f"),
                alt.Tooltip("% of target:Q", title="% of target"),
                alt.Tooltip("Status:N", title="Status"),
                alt.Tooltip("Detail:N", title="Why"),
            ],
        )
        .properties(width="container", height=alt.Step(28))
    )


def _render_subscore_chart(items, key: str):
    """Render an interactive horizontal bar chart of sub-scores with hover tooltips.

    In low-bandwidth mode, render plain progress bars instead of an Altair chart.
    """
    if st.session_state.get("lite_mode", False):
        for label, score, max_val, _detail in items:
            pct = min(score / max_val, 1.0) if max_val else 0.0
            st.progress(pct, text=f"{label}: {score}/{max_val}")
        return
    st.altair_chart(_subscore_chart(items), use_container_width=True, key=key)


_EVIDENCE_LADDER_TIER_DESCRIPTIONS = {
    "Basic": "Attendance, registration, logs, photos",
    "Moderate": "Follow-up surveys, testimonials",
    "Stronger": "Business/regulatory records, mentor verification, "
                "baseline/endline, external evaluation, comparison groups",
}


def _evidence_ladder_chart(ladder):
    """Build an interactive 'climb the ladder' chart: one rung per evidence tier,
    with the rung you're currently standing on highlighted and hover detail on
    what was matched."""
    import pandas as pd
    import altair as alt

    counts   = ladder.get("tier_counts", {})
    matches  = ladder.get("tier_matches", {})
    dominant = ladder.get("dominant_tier")

    rows = []
    for rung, tier in enumerate(_evaluator.EVIDENCE_LADDER_TIERS, start=1):
        rows.append({
            "Tier": tier,
            "Rung": f"Rung {rung} — {tier}",
            "Sources detected": counts.get(tier, 0),
            "You are here": "👈 Your evidence currently sits here" if tier == dominant else "",
            "Matched keywords": ", ".join(matches.get(tier, [])) or "None detected yet",
            "What counts": _EVIDENCE_LADDER_TIER_DESCRIPTIONS[tier],
        })
    df = pd.DataFrame(rows)

    if dominant:
        opacity_enc = alt.condition(
            alt.FieldEqualPredicate(field="Tier", equal=dominant),
            alt.value(1.0), alt.value(0.35),
        )
    else:
        opacity_enc = alt.value(0.85)

    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("Sources detected:Q", title="Sources detected"),
            y=alt.Y("Rung:N", sort=["Rung 3 — Stronger", "Rung 2 — Moderate", "Rung 1 — Basic"], title=None),
            color=alt.Color(
                "Tier:N",
                scale=alt.Scale(
                    domain=["Basic", "Moderate", "Stronger"],
                    range=["#C62828", "#8A6500", "#1B5E20"],
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            opacity=opacity_enc,
            tooltip=[
                alt.Tooltip("Tier:N", title="Tier"),
                alt.Tooltip("What counts:N", title="What counts"),
                alt.Tooltip("Sources detected:Q", title="Sources detected"),
                alt.Tooltip("Matched keywords:N", title="Matched keywords"),
                alt.Tooltip("You are here:N", title=" "),
            ],
        )
    )

    labels = (
        alt.Chart(df)
        .mark_text(align="left", dx=6, fontWeight="bold", color="#1B5E20")
        .encode(
            x=alt.X("Sources detected:Q"),
            y=alt.Y("Rung:N", sort=["Rung 3 — Stronger", "Rung 2 — Moderate", "Rung 1 — Basic"]),
            text="You are here:N",
        )
    )

    return (bars + labels).properties(width="container", height=alt.Step(40))


def _render_evidence_ladder_chart(ladder, key: str):
    """Render the Evidence Ladder chart.

    In low-bandwidth mode, render a plain markdown list instead of an Altair chart.
    """
    if st.session_state.get("lite_mode", False):
        dominant = ladder.get("dominant_tier")
        counts   = ladder.get("tier_counts", {})
        for tier in _evaluator.EVIDENCE_LADDER_TIERS:
            marker = "👉 " if tier == dominant else "◦ "
            st.markdown(f"{marker}**{tier}** — {counts.get(tier, 0)} source(s) detected")
        return
    st.altair_chart(_evidence_ladder_chart(ladder), use_container_width=True, key=key)


def _render_live_score_preview(slot: int = 1):
    sub = _build_submission_from_session(slot)
    try:
        ev = _evaluator.evaluate_submission(sub)
    except Exception:
        st.caption("Fill in the form fields above to see your live score.")
        return

    conf_score     = ev.get("confidence_score", 0)       # post-multiplier (gate assessment)
    raw_conf       = ev.get("raw_confidence_score", conf_score)  # pre-multiplier (matches sub-scores)
    multiplier     = ev.get("content_quality_multiplier", 1.0)
    content_issues = ev.get("content_issues", [])
    clar_score     = ev.get("clarity_score", 0)
    clar_label  = ev.get("clarity_label", "—")
    conf_comp   = ev.get("confidence_components", {})
    clar_comp   = ev.get("clarity_components", {})

    # --- v3.4: cache "what to fix" so destination tabs can show highlighted notes ---
    s = _slot_suffix(slot)
    st.session_state[f"_fixes_computed{s}"] = ev.get("fixes", [])

    # Labels derived from the raw confidence so they match the displayed number
    raw_conf_label, _ = _evaluator.interpret_score(raw_conf) if hasattr(_evaluator, "interpret_score") else (ev.get("confidence_label", "—"), "")

    # Headline: is this good enough to submit?
    _live_diag_state, _ = get_diagnostic_state(raw_conf, clar_score, content_issues, sub.get("beneficiary_voice", ""))
    if _live_diag_state != "INVALID INPUT":
        _render_readiness_banner(_live_diag_state)

    c1, c2 = st.columns(2)
    with c1:
        # Show raw score — always equals sum of sub-scores below
        st.metric("Confidence", f"{raw_conf}/5.0", delta=raw_conf_label, delta_color="off")
    with c2:
        st.metric("Clarity", f"{clar_score}/5.0", delta=clar_label, delta_color="off")

    # Penalty warning: effective score used for gate assessment
    if multiplier < 1.0:
        _penalty_lines = [f"- {ci}" for ci in (content_issues or [])]
        _penalty_body = "\n".join(_penalty_lines) if _penalty_lines else "Review your result statement and evidence description."
        st.warning(
            f"**Content quality penalty (×{multiplier}) applied** — effective score: **{conf_score}/5.0**\n\n"
            f"Issues detected:\n{_penalty_body}\n\n"
            "Fix these to remove the penalty."
        )
        # --- UX: ACTIONABLE SCORE PREVIEW (v3.2) ---
        if st.button("→ Fix: Go to Result Basics", key="fix_content_quality", type="primary"):
            st.session_state["current_tab"] = 0
            st.rerun()
        # --- END UX: ACTIONABLE SCORE PREVIEW (v3.2) ---

    bd1, bd2 = st.columns(2)

    with bd1:
        st.markdown("**Confidence**")
        dl = conf_comp.get("direct_level", 0)
        vl = conf_comp.get("verify_level", 0)
        rl = conf_comp.get("recency_level", 0)
        ds = conf_comp.get("direct_score", 0)
        vs = conf_comp.get("verify_score", 0)
        rs = conf_comp.get("recency_score", 0)
        _render_subscore_chart([
            ("Directness", ds, 2.0, _DIRECTNESS_TIPS.get(dl, "How directly traceable the evidence is to the result. Target: 1.5+/2.0.")),
            ("Verification", vs, 2.0, _VERIFICATION_TIPS.get(vl, "How rigorously the evidence has been reviewed. Target: 1.5+/2.0.")),
            ("Recency", rs, 1.0, _RECENCY_TIPS.get(rl, "How recent the evidence is relative to the reporting period. Target: 0.7+/1.0.")),
        ], key=f"live_conf_chart{s}")

    with bd2:
        st.markdown("**Clarity**")
        def_s  = clar_comp.get("definition_score", 0)
        meas_s = clar_comp.get("measurement_score", 0)
        integ  = clar_comp.get("integrity_score", 0)
        scope  = clar_comp.get("scope_score", 0)
        gov    = clar_comp.get("governance_score", 0)
        is_qual    = clar_comp.get("is_qualitative", False)
        def_label  = "Narrative Definition" if is_qual else "Definition"
        def_tip    = _CLARITY_TIPS["definition_qualitative"] if is_qual else _CLARITY_TIPS["definition"]
        meas_label = "Sourcing & Triangulation" if is_qual else "Measurement"
        meas_tip   = _CLARITY_TIPS["measurement_qualitative"] if is_qual else _CLARITY_TIPS["measurement"]
        _render_subscore_chart([
            (def_label, def_s, 1.25, def_tip),
            (meas_label, meas_s, 1.25, meas_tip),
            ("Integrity", integ, 1.0, _CLARITY_TIPS["integrity"]),
            ("Scope", scope, 0.75, _CLARITY_TIPS["scope"]),
            ("Governance", gov, 0.75, _CLARITY_TIPS["governance"]),
        ], key=f"live_clar_chart{s}")

    # Gate assessment uses penalized conf_score
    state, state_sub = get_diagnostic_state(conf_score, clar_score)
    st.caption(f"Status: **{state}** — {state_sub}")

    # --- UX: ACTIONABLE SCORE PREVIEW (v3.2) ---
    if state in ("MISLEADING", "FUNDAMENTALLY WEAK"):
        if st.button("→ Fix: Sharpen Result Statement", key="fix_misleading", type="primary"):
            st.session_state["current_tab"] = 0
            st.rerun()
    if state in ("UNDEREVIDENCED", "FUNDAMENTALLY WEAK"):
        if st.button("→ Fix: Strengthen Evidence", key="fix_underevidenced", type="primary"):
            st.session_state["current_tab"] = 2
            st.rerun()
    if state == "NEEDS REFINEMENT":
        if st.button("→ Fix: Review Specific Gaps", key="fix_refinement", type="primary"):
            st.session_state["current_tab"] = 1
            st.rerun()
    # --- END UX: ACTIONABLE SCORE PREVIEW (v3.2) ---

    # --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
    gov_score, pii_selected, gov_gaps, safeguarding_triggered, minors_involved = _compute_governance_score(slot)
    conf_100 = round(raw_conf * 20, 1)
    gov_adjustment = round(gov_score * 0.3, 1)
    if gov_score == 0 and (pii_selected or safeguarding_triggered or minors_involved):
        gov_adjustment -= 8
    adjusted_conf = min(100.0, conf_100 + gov_adjustment)

    st.session_state["_gov_score_computed"] = gov_score
    st.session_state["_gov_gaps_computed"]  = gov_gaps
    st.session_state["_gov_pii_computed"]   = pii_selected
    st.session_state["_conf_adj_computed"]  = adjusted_conf

    # Read governance field values for display (scoring unchanged — uses _compute_governance_score above)
    _disp_consent    = st.session_state.get(f"gov_consent_status{s}", "")
    _disp_anon       = st.session_state.get(f"gov_anonymization_status{s}", "")
    _disp_law        = st.session_state.get(f"gov_compliance_law_status{s}", "")
    _disp_safeguard  = st.session_state.get(f"gov_safeguarding_status{s}", "")
    _disp_child_safe = st.session_state.get(f"gov_child_safeguarding_status{s}", "")
    _disp_secure     = st.session_state.get(f"gov_secure_handling_status{s}", "")
    _disp_dpp        = st.session_state.get("gov_dpp_uploaded", False)
    _answered = sum([
        _disp_consent    not in ("", "Choose an option...", "Select consent status..."),
        _disp_anon       not in ("", "Choose an option...", "Select anonymization status..."),
        _disp_law        not in ("", "Choose an option...", "Select compliance status..."),
        _disp_safeguard  not in ("", "Choose an option...", "Select safeguarding status..."),
        _disp_child_safe not in ("", "Choose an option...", "Select child safeguarding status..."),
        _disp_secure     not in ("", "Choose an option...", "Select secure handling status..."),
    ])

    st.markdown("---")
    st.markdown("#### 🛡️ Governance & Compliance")
    _gc1, _gc2 = st.columns([1, 2])
    with _gc1:
        st.metric("Governance Score", f"{gov_score} / 24")
    with _gc2:
        st.metric("Governance-Adjusted Confidence", f"{adjusted_conf:.0f} / 100")

    # Single bold status line — no alarming styling
    if gov_score >= 20:
        st.markdown("**Strong governance — major requirements addressed.**")
    elif gov_score >= 11:
        st.markdown("**Partial compliance — some requirements still recommended before submission.**")
    elif _answered == 0:
        st.markdown("**Data governance checklist not yet completed — 0 of 6 questions answered.**")
    else:
        st.markdown(f"**Governance requirements partially met ({gov_score}/24) — review items below.**")

    # Remediation action — placed right next to the status line so the fix is one click away
    if gov_score < 20:
        if st.button("→ Fix: Governance Issues", key="fix_gov_btn", type="primary"):
            st.session_state["current_tab"] = 2
            st.rerun()

    # Per-item checklist
    with st.expander("Governance checklist detail", expanded=(gov_score < 11)):
        for _lbl, _val, _max, _cmap in [
            ("Beneficiary consent",                  _disp_consent,    5, CONSENT_CHECKLIST_MAP),
            ("Data anonymization",                   _disp_anon,       4, ANON_CHECKLIST_MAP),
            ("Data law compliance",                  _disp_law,        3, LAW_CHECKLIST_MAP),
            ("Do-no-harm & safeguarding",            _disp_safeguard,  3, SAFEGUARDING_CHECKLIST_MAP),
            ("Child safeguarding",                   _disp_child_safe, 3, CHILD_SAFEGUARDING_CHECKLIST_MAP),
            ("Secure handling of identifiable testimony", _disp_secure, 3, SECURE_HANDLING_CHECKLIST_MAP),
        ]:
            _icon, _desc, _earned = _cmap.get(_val, ("✗", "Not answered", 0))
            st.markdown(f"{_icon} **{_lbl}** — {_desc} ({_earned}/{_max} pts)")
        if _disp_dpp:
            st.markdown("✓ **Data protection policy** — uploaded (+5 bonus)")
        else:
            st.caption("◦ Data protection policy not uploaded (optional +5 bonus)")
    # --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---


# ---------------------------------------------------------------------------
# JSON inputs export / import
# ---------------------------------------------------------------------------

def _build_inputs_json(timestamp: str) -> str:
    active = st.session_state.get("active_slots_run", st.session_state.get("active_slots", 1))
    slots_data = []
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        slot_dict = {}
        for k in _BASE_FORM_KEYS:
            slot_dict[k] = st.session_state.get(f"{k}{s}", "")
        ed = st.session_state.get(f"evidence_date{s}")
        slot_dict["evidence_date"] = ed.isoformat() if hasattr(ed, "isoformat") else ""
        rs = st.session_state.get(f"reporting_start{s}")
        slot_dict["reporting_start"] = rs.isoformat() if hasattr(rs, "isoformat") else ""
        re_ = st.session_state.get(f"reporting_end{s}")
        slot_dict["reporting_end"] = re_.isoformat() if hasattr(re_, "isoformat") else ""
        raw_files = st.session_state.get(f"uploaded_files_widget{s}") or []
        slot_dict["uploaded_filenames"] = [f.name for f in raw_files if hasattr(f, "name")]
        # --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
        for _gk in ["gov_consent_status", "gov_anonymization_status", "gov_compliance_law_status",
                     "gov_safeguarding_status", "gov_child_safeguarding_status", "gov_secure_handling_status"]:
            slot_dict[_gk] = st.session_state.get(f"{_gk}{s}", "")
        slot_dict["gov_dpp_uploaded"] = st.session_state.get("gov_dpp_uploaded", False)
        # --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
        slots_data.append(slot_dict)

    payload = {
        "timestamp": timestamp,
        "session_id": f"ir-{timestamp}",
        "active_slots": active,
        "slots": slots_data,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _normalize_draft_json(data: dict) -> dict:
    """Convert a flat '_save_draft()' export (the '📥 Download Draft (JSON)' format,
    e.g. {"active_slots": 1, "result_statement": "...", "logframe_indicator": "...", ...})
    into the {"slots": [...]} format produced by _build_inputs_json() / 'Save Inputs (JSON)'
    and expected by _load_from_inputs_json."""
    if "slots" in data:
        return data

    active = int(data.get("active_slots", 1))
    slots_data = []
    for slot in range(1, active + 1):
        s = _slot_suffix(slot)
        slot_dict = {}
        for k in _BASE_FORM_KEYS:
            if f"{k}{s}" in data:
                slot_dict[k] = data[f"{k}{s}"]
        for dk in ("evidence_date", "reporting_start", "reporting_end"):
            if f"{dk}{s}" in data:
                slot_dict[dk] = data[f"{dk}{s}"]
        if f"uploaded_filenames{s}" in data:
            slot_dict["uploaded_filenames"] = data[f"uploaded_filenames{s}"]
        for gk in ("gov_consent_status", "gov_anonymization_status", "gov_compliance_law_status",
                    "gov_safeguarding_status", "gov_child_safeguarding_status", "gov_secure_handling_status"):
            if f"{gk}{s}" in data:
                slot_dict[gk] = data[f"{gk}{s}"]
        slot_dict["gov_dpp_uploaded"] = data.get("gov_dpp_uploaded", False)
        slots_data.append(slot_dict)

    return {
        "timestamp": data.get("timestamp", ""),
        "active_slots": active,
        "slots": slots_data,
    }


def _load_from_inputs_json(data: dict):
    data = _normalize_draft_json(data)
    if "slots" not in data:
        st.error("Invalid file format — missing 'slots' key. Please upload a file exported by Impact-Receipts.")
        return

    active = int(data.get("active_slots", 1))
    st.session_state["active_slots"] = active

    for slot_idx, slot_dict in enumerate(data["slots"]):
        slot = slot_idx + 1
        s = _slot_suffix(slot)
        for k in _BASE_FORM_KEYS:
            if k in slot_dict:
                try:
                    st.session_state[f"{k}{s}"] = slot_dict[k]
                except Exception:
                    # key already backs a widget instantiated earlier in this run
                    # (e.g. the global "sector" selector) — skip, non-critical
                    pass
        raw_date = slot_dict.get("evidence_date", "")
        if raw_date:
            try:
                st.session_state[f"evidence_date{s}"] = date.fromisoformat(raw_date)
            except (ValueError, TypeError):
                pass
        for _dk2, _sk2 in [("reporting_start", f"reporting_start{s}"),
                            ("reporting_end",   f"reporting_end{s}")]:
            _rd2 = slot_dict.get(_dk2, "")
            if _rd2:
                try:
                    st.session_state[_sk2] = date.fromisoformat(_rd2)
                except (ValueError, TypeError):
                    pass
        # restore governance fields not in _BASE_FORM_KEYS loop
        _gov_dpp = slot_dict.get("gov_dpp_uploaded")
        if _gov_dpp is not None:
            st.session_state["gov_dpp_uploaded"] = bool(_gov_dpp)
        st.session_state[f"draft_uploaded_filenames{s}"] = slot_dict.get("uploaded_filenames", [])

    ts = data.get("timestamp", "unknown")
    # --- UX: SMART DEFAULTS (v3.2) ---
    _prefill_count = sum(
        1 for _sd in data.get("slots", [{}])
        for _k, _v in _sd.items() if _v and _k in _BASE_FORM_KEYS
    )
    st.success(f"✅ Draft loaded — {_prefill_count} fields pre-filled. Review and update as needed.")
    # --- END UX: SMART DEFAULTS (v3.2) ---
    # bump version so _irc_widget-backed fields re-seed from the freshly loaded values
    st.session_state["_irc_fill_version"] = st.session_state.get("_irc_fill_version", 0) + 1
    st.session_state["_tab2_auto_advanced"] = True
    st.session_state["screen"] = 1
    st.session_state["current_tab"] = 0
    st.rerun()


def _build_submission_from_session(slot: int = 1) -> dict:
    """Assemble evaluator-compatible submission dict from session_state for a given slot."""
    s = _slot_suffix(slot)

    ev_type = st.session_state.get(f"evidence_type{s}", "")
    if ev_type == "Other":
        ev_type = st.session_state.get(f"evidence_type_other{s}", "") or "Other"

    int_rev = st.session_state.get(f"internal_review{s}", "Not reviewed")
    if int_rev == "Other":
        int_rev = st.session_state.get(f"internal_review_other{s}", "") or "Other"

    ext_rev = st.session_state.get(f"external_review{s}", "No external review")
    if ext_rev == "Other":
        ext_rev = st.session_state.get(f"external_review_other{s}", "") or "Other"

    donor = st.session_state.get("donor_selected", "(No donor specified)")
    if donor == "Other":
        donor = st.session_state.get("donor_other", "") or "Other"

    sector = st.session_state.get("sector", SECTOR_OPTIONS[0])
    if sector == "Other":
        sector = st.session_state.get("sector_other", "") or "Other"

    submission_type = st.session_state.get("submission_type", "Select submission type...")

    return {
        "result_statement":   st.session_state.get(f"result_statement{s}", ""),
        "target_group":       st.session_state.get(f"target_group{s}", ""),
        "timeframe":          st.session_state.get(f"timeframe{s}", ""),
        "geographic_scope":   st.session_state.get(f"geographic_scope{s}", ""),
        "additional_context": st.session_state.get(f"additional_context{s}", ""),
        "learning_notes":     st.session_state.get(f"learning_notes{s}", ""),
        "limitations_notes":  st.session_state.get(f"limitations_notes{s}", ""),
        "internal_review":    int_rev,
        "external_review":    ext_rev,
        "attached_filenames": st.session_state.get(f"uploaded_files{s}", []),
        "beneficiary_voice":    st.session_state.get(f"beneficiary_voice{s}", ""),
        "logframe_indicator":   st.session_state.get(f"logframe_indicator{s}", ""),
        "logframe_target":      st.session_state.get(f"logframe_target{s}", ""),
        "logframe_achievement": st.session_state.get(f"logframe_achievement{s}", ""),
        "reporting_start":      _format_date(st.session_state.get(f"reporting_start{s}")),
        "reporting_end":        _format_date(st.session_state.get(f"reporting_end{s}")),
        "provenance_checklist": {
            "sampling_documented":     st.session_state.get(f"provenance_sampling{s}", "Choose an option..."),
            "double_counting_checked": st.session_state.get(f"provenance_dedup{s}", "Choose an option..."),
            "collection_tool_named":   st.session_state.get(f"provenance_tool{s}", "Choose an option..."),
            "collector_independent":   st.session_state.get(f"provenance_independence{s}", "Choose an option..."),
            "recall_period_ok":        st.session_state.get(f"provenance_recall{s}", "Choose an option..."),
            "auditor_traceable":       st.session_state.get(f"provenance_traceability{s}", "Choose an option..."),
        },
        "qualitative_evidence": st.session_state.get(f"qualitative_evidence{s}", False),
        "qualitative_rigor_checklist": {
            "sourcing_documented":          st.session_state.get(f"qual_sourcing{s}", False),
            "triangulated":                 st.session_state.get(f"qual_triangulated{s}", False),
            "bias_considered":              st.session_state.get(f"qual_bias{s}", False),
            "beneficiary_voice_represented": st.session_state.get(f"qual_voice{s}", False),
            "consent_ethics_addressed":      st.session_state.get(f"qual_consent{s}", False),
        },
        "attribution_contribution": st.session_state.get(f"attribution_contribution{s}", "Not specified"),
        "disaggregation_status":     st.session_state.get(f"disaggregation_status{s}", "Not specified"),
        "review_status":     st.session_state.get(f"review_status{s}", _SUBMISSION_STATUS_OPTIONS[0]),
        "reviewer_name":     st.session_state.get(f"reviewer_name{s}", ""),
        "reviewer_role":     st.session_state.get(f"reviewer_role{s}", ""),
        "reviewer_date":     st.session_state.get(f"reviewer_date{s}", ""),
        "reviewer_decision": st.session_state.get(f"reviewer_decision{s}", ""),
        "reviewer_notes":    st.session_state.get(f"reviewer_notes{s}", ""),
        "donor":                     donor,
        "sector":                    sector,
        "project_name":              st.session_state.get("project_name", ""),
        "submission_type":           submission_type,
        "evidence": [{
            "type":        ev_type,
            "description": st.session_state.get(f"evidence_description{s}", ""),
            "recency":     _format_date(st.session_state.get(f"evidence_date{s}")),
            "verified_by": st.session_state.get(f"verifier{s}", ""),
        }],
    }


def _render_slot_fields(slot: int):
    """Render all form fields for one result slot."""
    s = _slot_suffix(slot)

    for key, default in [
        (f"evidence_type{s}", EVIDENCE_TYPES[0]),
        (f"internal_review{s}", "Choose an option..."),
        (f"external_review{s}", "Choose an option..."),
        # --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
        (f"gov_consent_status{s}", "Select consent status..."),
        (f"gov_anonymization_status{s}", "Select anonymization status..."),
        (f"gov_compliance_law_status{s}", "Select compliance status..."),
        (f"gov_safeguarding_status{s}", "Select safeguarding status..."),
        (f"gov_child_safeguarding_status{s}", "Select child safeguarding status..."),
        (f"gov_secure_handling_status{s}", "Select secure handling status..."),
        # --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
        # --- REVIEW-HANDOFF LAYER (v3.6) ---
        (f"review_status{s}", _SUBMISSION_STATUS_OPTIONS[0]),
        (f"reviewer_decision{s}", _REVIEW_DECISION_OPTIONS[0]),
        # --- END REVIEW-HANDOFF LAYER (v3.6) ---
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    _sector = st.session_state.get("sector", SECTOR_OPTIONS[0])
    _ph_key = "Other" if _sector in ("Other", "(No sector selected)") else _sector
    _ph = SECTOR_PLACEHOLDERS.get(_ph_key, SECTOR_PLACEHOLDERS["Other"])

    st.text_area(
        "Result statement",
        key=f"result_statement{s}",
        placeholder=_ph["result"],
        height=100,
        help="What did your project achieve? Include the action verb, number, target group, location, and timeframe.",
    )
    _rs = st.session_state.get(f"result_statement{s}", "")
    if _rs and len(_rs.strip()) < 20:
        st.warning("Result statement is very short. Include: action verb + number + population + timeframe.")
    elif _rs and not any(c.isdigit() for c in _rs):
        st.caption("Tip: Add a number (e.g., '500 farmers trained') — quantified claims score higher.")

    st.markdown("#### Logframe Linkage")
    st.caption(
        "**Why this matters:** A real African consultancy had their final donor report "
        "rejected 3 times in 2024 because results weren't tied to logframe indicators. "
        "40+ hours of rework. We don't want that to happen to you."
    )
    _irc_widget(
        st.text_input,
        "Logframe indicator this result reports against",
        f"logframe_indicator{s}", default="",
        placeholder=_ph.get("logframe_indicator", "e.g., Indicator 1.2: Number of [target group] achieving [outcome]"),
        help=(
            "Copy the exact indicator name and code from your approved Technical Proposal or logframe. "
            "If you cannot quote it, your donor cannot match your result to your commitment."
        ),
    )
    _irc_widget(
        st.text_input,
        "Original target for this indicator (from logframe)",
        f"logframe_target{s}", default="",
        placeholder=_ph.get("logframe_target", "e.g., 250 youth trained by Q4 2025"),
        help=(
            "The target as approved in the original Technical Proposal. Donors compare achievements "
            "against approved targets — not revised internal targets."
        ),
    )
    _irc_widget(
        st.text_input,
        "Actual achievement (must match your result statement)",
        f"logframe_achievement{s}", default="",
        placeholder=_ph.get("logframe_achievement", "e.g., [Actual number] by [date] — [%] of original target"),
        help=(
            "The actual delivered number, ideally with % achievement vs original target. "
            "Must reconcile with your result statement above."
        ),
    )

    st.text_input(
        "Target group", key=f"target_group{s}",
        placeholder=_ph["target_group"],
        help="Who specifically? Age, gender, role, geography. Avoid 'beneficiaries' alone.",
    )

    st.text_input(
        "Timeframe", key=f"timeframe{s}",
        placeholder="e.g., January - June 2025",
        help="Specific dates or quarters. 'January–June 2025' is stronger than 'In 2025'.",
    )

    st.text_input(
        "Geographic scope", key=f"geographic_scope{s}",
        placeholder=_ph["geographic_scope"],
        help="Districts, regions, or specific sites. 'Volta Region' beats 'rural areas'.",
    )

    st.text_area(
        "Describe your supporting evidence", key=f"evidence_description{s}",
        placeholder=_ph["evidence_description"],
        height=120,
        help="Describe the actual document or data: who collected it, how, and what's in it.",
    )
    _ed = st.session_state.get(f"evidence_description{s}", "")
    if _ed and len(_ed.strip()) < 30:
        st.warning("Evidence description is brief. Specify: who collected it, how, and what it contains.")

    st.selectbox(
        "Evidence type", key=f"evidence_type{s}",
        options=EVIDENCE_TYPES,
        help=EVIDENCE_TYPE_HELP,
    )
    ev_type = st.session_state.get(f"evidence_type{s}", EVIDENCE_TYPES[0])
    ev_desc = st.session_state.get(f"evidence_description{s}", "")
    _dl = _evaluator.get_directness_level(ev_type, ev_desc)
    _ds = round((_dl / 5) * 2.0, 1)
    st.caption(f"Directness score from this evidence type: **{_ds}/2.0**")

    if ev_type == "Other":
        st.text_input("Specify evidence type", key=f"evidence_type_other{s}")

    int_rev = st.session_state.get(f"internal_review{s}", INTERNAL_REVIEW_OPTIONS[0])
    st.selectbox(
        "Internal review", key=f"internal_review{s}",
        options=INTERNAL_REVIEW_OPTIONS,
        help="Did anyone in your organization review or cross-check this data?",
    )
    int_rev = st.session_state.get(f"internal_review{s}", INTERNAL_REVIEW_OPTIONS[0])
    _int_vl = _evaluator.get_verification_level(int_rev, "No external review", "")
    _int_vs = round((_int_vl / 5) * 2.0, 1)
    if _int_vs > 0:
        st.caption(f"Internal review adds **{_int_vs}/2.0** to Verification score")
    else:
        st.caption("⚠ No internal review: Verification score starts at 0. Adding a reviewer will improve this.")

    if int_rev == "Other":
        st.text_input("Specify internal reviewer", key=f"internal_review_other{s}")

    ext_rev = st.session_state.get(f"external_review{s}", EXTERNAL_REVIEW_OPTIONS[0])
    st.selectbox(
        "External review", key=f"external_review{s}",
        options=EXTERNAL_REVIEW_OPTIONS,
        help="Did an outside party verify the data? Government, partner, auditor, or evaluator.",
    )
    ext_rev = st.session_state.get(f"external_review{s}", EXTERNAL_REVIEW_OPTIONS[0])
    verifier_text = st.session_state.get(f"verifier{s}", "")
    _full_vl = _evaluator.get_verification_level(int_rev, ext_rev, verifier_text)
    _full_vs = round((_full_vl / 5) * 2.0, 1)
    _added   = round(_full_vs - _int_vs, 1)
    if _added > 0:
        st.caption(f"External review adds **+{_added}** more → total Verification: **{_full_vs}/2.0**")
    elif ext_rev == "No external review":
        st.caption("⚠ No external review: adding independent verification can raise this score significantly.")
    else:
        st.caption(f"Total Verification: **{_full_vs}/2.0**")

    if ext_rev == "Other":
        st.text_input("Specify external reviewer", key=f"external_review_other{s}")

    # --- UX: CONDITIONAL FIELDS (v3.2) ---
    if st.session_state.get(f"internal_review{s}") != "Not reviewed":
        _irc_widget(
            st.text_input, "Who verified this?", f"verifier{s}", default="",
            placeholder=_ph.get("verifier", "e.g., District Agriculture Officer, partner org M&E lead, external evaluator"),
            help="The person or organization that confirmed the data is accurate.",
        )
    # --- END UX: CONDITIONAL FIELDS (v3.2) ---

    st.markdown("#### Reporting Period")
    st.caption("The period this submission covers. Evidence dates outside this range will be flagged.")
    _rp_col_s, _rp_col_e = st.columns(2)
    with _rp_col_s:
        st.date_input(
            "Reporting period start",
            value=st.session_state.get(f"reporting_start{s}"),
            key=f"reporting_start{s}",
            help="When does the period this report covers begin?",
        )
    with _rp_col_e:
        st.date_input(
            "Reporting period end",
            value=st.session_state.get(f"reporting_end{s}"),
            key=f"reporting_end{s}",
            help="When does the period this report covers end?",
        )

    st.date_input(
        "When was this evidence collected?",
        value=st.session_state.get(f"evidence_date{s}"),
        key=f"evidence_date{s}",
        help="When was the data collected? Use the most recent date if multiple sources.",
    )
    _ed = st.session_state.get(f"evidence_date{s}")
    if _ed and hasattr(_evaluator, "get_recency_diagnostic"):
        _rec_diag = _evaluator.get_recency_diagnostic(_ed)
        if "0.4/1.0" in _rec_diag or "0.2/1.0" in _rec_diag:
            st.warning(_rec_diag)
        elif "0.6/1.0" in _rec_diag:
            st.info(_rec_diag)
        else:
            st.success(_rec_diag)
    _rp_s = st.session_state.get(f"reporting_start{s}")
    _rp_e = st.session_state.get(f"reporting_end{s}")
    if _ed and _rp_s and _rp_e and hasattr(_evaluator, "validate_reporting_period"):
        _, _rp_msg, _rp_sev = _evaluator.validate_reporting_period(_ed, _rp_s, _rp_e)
        if _rp_sev == "ERROR":
            st.error(_rp_msg)
        elif _rp_sev == "WARNING":
            st.warning(_rp_msg)
        elif _rp_msg:
            st.success(_rp_msg)

    st.markdown("#### Beneficiary Voice")
    st.caption(
        "Did the beneficiaries contribute to or validate this evidence? "
        "Anchored in Bond Evidence Principles 2024 + 60 Decibels Lean Data."
    )
    st.selectbox(
        "How were beneficiary voices captured?",
        key=f"beneficiary_voice{s}",
        options=_BV_OPTIONS,
        help=(
            "Bond Evidence Principle 1 (2024 refresh): Voice & Inclusion. "
            "The strongest evidence includes beneficiary perspectives, not just provider reports."
        ),
    )

    prev_files = st.session_state.get(f"draft_uploaded_filenames{s}", [])
    if prev_files:
        st.caption(f"Previously attached: {', '.join(prev_files)} — please re-attach below.")
    st.file_uploader(
        "Attach supporting documents (optional)", key=f"uploaded_files_widget{s}",
        accept_multiple_files=True,
        type=["pdf", "docx", "xlsx", "csv", "jpg", "jpeg", "png", "txt"],
        help="Attach raw evidence files — datasets, signed sheets, photos with metadata, partner letters.",
    )


# ---------------------------------------------------------------------------
# Screen 1 — Tab helper functions (v3.3)
# ---------------------------------------------------------------------------

def _tab_slot_setup(slot: int):
    s = _slot_suffix(slot)
    for key, default in [
        (f"evidence_type{s}", EVIDENCE_TYPES[0]),
        (f"internal_review{s}", "Not reviewed"),
        (f"external_review{s}", "No external review"),
        # --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
        (f"gov_consent_status{s}", "Select consent status..."),
        (f"gov_anonymization_status{s}", "Select anonymization status..."),
        (f"gov_compliance_law_status{s}", "Select compliance status..."),
        (f"gov_safeguarding_status{s}", "Select safeguarding status..."),
        (f"gov_child_safeguarding_status{s}", "Select child safeguarding status..."),
        (f"gov_secure_handling_status{s}", "Select secure handling status..."),
        # --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
        # --- REVIEW-HANDOFF LAYER (v3.6) ---
        (f"review_status{s}", _SUBMISSION_STATUS_OPTIONS[0]),
        (f"reviewer_decision{s}", _REVIEW_DECISION_OPTIONS[0]),
        # --- END REVIEW-HANDOFF LAYER (v3.6) ---
    ]:
        if key not in st.session_state:
            st.session_state[key] = default
    _sector = st.session_state.get("sector", SECTOR_OPTIONS[0])
    _ph_key = "Other" if _sector in ("Other", "(No sector selected)") else _sector
    _ph = SECTOR_PLACEHOLDERS.get(_ph_key, SECTOR_PLACEHOLDERS["Other"])
    return s, _ph


def _irc_widget(widget_fn, label, base_key, default=None, **kwargs):
    """Render a widget whose canonical value lives in the plain (non-widget)
    session_state key `base_key`, so the rest of the app (sidebar summary,
    scoring, _build_submission_from_session) keeps reading and writing
    `base_key` exactly as before — including Instant Report Check pre-fills
    and the "Today" date-shortcut buttons.

    The widget itself is bound to a version-suffixed key (`base_key__w{N}`).
    Streamlit resets a session_state entry to its last frontend value at the
    start of every run once that key has ever backed a widget, which would
    silently discard out-of-band writes to `base_key` if `base_key` were used
    directly as the widget key. Keeping the widget key separate avoids that,
    and bumping `N` (via `_irc_fill_version`) mints a fresh, never-instantiated
    widget key whenever IRC re-fills the form, so the new value is picked up.
    """
    ver = st.session_state.get("_irc_fill_version", 0)
    wkey = f"{base_key}__w{ver}"
    shadow_key = f"_irc_shadow_{wkey}"
    base_val = st.session_state.get(base_key, default)
    if wkey not in st.session_state or st.session_state.get(shadow_key, object()) != base_val:
        st.session_state[wkey] = base_val
    widget_fn(label, key=wkey, **kwargs)
    st.session_state[base_key] = st.session_state[wkey]
    st.session_state[shadow_key] = st.session_state[wkey]


# --- v3.3 field-validation marker sets ---
_DEMO_MARKERS = {"farmer", "women", "woman", "youth", "child", "children", "household",
    "teacher", "worker", "patient", "student", "beneficiar", "community",
    "resident", "family", "families", "men", "girl", "boy", "aged", "adult"}
_DATE_MARKERS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
    "oct", "nov", "dec", "q1", "q2", "q3", "q4", "quarter", "2023", "2024",
    "2025", "2026", "2027", "month", "year", "period", "week"}
_LOC_MARKERS  = {"district", "region", "province", "state", "county", "city", "town",
    "village", "community", "ward", "national", "local", "ghana", "nigeria",
    "kenya", "uganda", "ethiopia", "senegal", "africa", "northern", "southern",
    "eastern", "western", "central", "zone", "area", "site"}

# --- v3.4: maps "what to fix" messages to the tab/field where they should be addressed ---
_FIX_FIELD_MAP = [
    ("missing unit, timeframe, or target group", 0, "Result statement, Target group, Timeframe"),
    ("sites and groups included and excluded",   0, "Geographic scope / Target group"),
    ("Name an owner for this result",            1, "Logframe indicator & linkage"),
    ("primary record",                           2, "Evidence type & description"),
    ("internal reviewer or an external partner", 2, "Internal review / External review / Verifier"),
    ("evidence date is within 6 months",         2, "Evidence date"),
    ("collection method and sampling approach",  2, "Evidence description"),
    ("Close data gaps with original source records", 2, "Evidence description"),
]


def _render_fix_notes(slot: int, tab_idx: int):
    """Show highlighted notes for gaps relevant to this tab, computed on Review & Submit."""
    s = _slot_suffix(slot)
    fixes = st.session_state.get(f"_fixes_computed{s}", [])
    notes = []
    for fix in fixes:
        msg = fix.get("message", "")
        for kw, t, field in _FIX_FIELD_MAP:
            if t == tab_idx and kw in msg:
                notes.append((field, fix["message"], fix.get("score_impact", "")))
                break
    if tab_idx == 2:
        for gap in st.session_state.get("_gov_gaps_computed", []):
            notes.append(("Compliance & Data Governance", gap, "raises Governance score"))
    if notes:
        lines = "\n".join(
            f"- **{field}** — {msg} _({impact})_" for field, msg, impact in notes
        )
        st.info(f"**📌 To improve your score, address:**\n\n{lines}")


def _render_tab1_slot(slot: int):
    s, _ph = _tab_slot_setup(slot)
    _render_fix_notes(slot, 0)
    _irc_widget(
        st.text_area, "Result statement", f"result_statement{s}", default="",
        placeholder=_ph["result"],
        height=100,
        help="What did your project achieve? Include the action verb, number, target group, location, and timeframe.",
    )
    _rs = st.session_state.get(f"result_statement{s}", "")
    if _rs and len(_rs.strip()) < 20:
        st.warning("Result statement is very short. Include: action verb + number + population + timeframe.")
    elif _rs and not any(c.isdigit() for c in _rs):
        st.caption("Tip: Add a number (e.g., '500 farmers trained') — quantified claims score higher.")
    if _rs:
        _def_count = sum([
            bool(re.search(r'\d', _rs)),
            bool(st.session_state.get(f"timeframe{s}", "")),
            bool(st.session_state.get(f"target_group{s}", "")),
        ])
        _def_score = round((_def_count / 3) * 1.25, 2)
        st.caption(f"Definition score contribution: **{_def_score}/1.25** (number, timeframe, target group)")
    _irc_widget(
        st.text_input, "Target group", f"target_group{s}", default="",
        placeholder=_ph["target_group"],
        help="Who specifically? Age, gender, role, geography. Avoid 'beneficiaries' alone.",
    )
    _irc_widget(
        st.text_input, "Timeframe", f"timeframe{s}", default="",
        placeholder="e.g., January - June 2025",
        help="Specific dates or quarters. 'January–June 2025' is stronger than 'In 2025'.",
    )
    _irc_widget(
        st.text_input, "Geographic scope", f"geographic_scope{s}", default="",
        placeholder=_ph["geographic_scope"],
        help="Districts, regions, or specific sites. 'Volta Region' beats 'rural areas'.",
    )
    _tg = _ss_str(f"target_group{s}").strip()
    _rs_filled = bool(_ss_str(f"result_statement{s}").strip())
    _tg_hint = _ph.get("target_group", "")
    if _rs_filled and not _tg:
        st.caption(f"💡 Hint: {_tg_hint}")
    elif len(_tg) > 5 and not any(m in _tg.lower() for m in _DEMO_MARKERS):
        st.warning("Target group should describe who was reached — include population type, age, or role.")

    _tf = _ss_str(f"timeframe{s}").strip()
    if _rs_filled and not _tf:
        st.caption("💡 Hint: e.g., January – June 2025 or Q1 2026")
    elif len(_tf) > 3 and not any(m in _tf.lower() for m in _DATE_MARKERS):
        st.warning("Timeframe should include a date range or period, e.g. January–June 2025.")

    _gs = _ss_str(f"geographic_scope{s}").strip()
    _gs_hint = _ph.get("geographic_scope", "")
    if _rs_filled and not _gs:
        st.caption(f"💡 Hint: {_gs_hint}")
    elif len(_gs) > 5 and not any(m in _gs.lower() for m in _LOC_MARKERS):
        _gs_example = re.sub(r"^e\.g\.,\s*", "", _gs_hint)
        st.warning(
            "Geographic scope should name specific districts, regions, or locations "
            f"(e.g., {_gs_example})."
        )

    st.caption("Specificity in these fields adds to your Clarity score. Generic terms cap it.")


def _render_tab2_slot(slot: int):
    s, _ph = _tab_slot_setup(slot)
    _render_fix_notes(slot, 1)
    st.markdown("#### Logframe Linkage")
    st.caption(
        "**Why this matters:** A real African consultancy had their final donor report "
        "rejected 3 times in 2024 because results weren't tied to logframe indicators. "
        "40+ hours of rework. We don't want that to happen to you."
    )
    _irc_widget(
        st.text_input,
        "Logframe indicator this result reports against",
        f"logframe_indicator{s}", default="",
        placeholder=_ph.get("logframe_indicator", "e.g., Indicator 1.2: Number of [target group] achieving [outcome]"),
        help=(
            "Copy the exact indicator name and code from your approved Technical Proposal or logframe. "
            "If you cannot quote it, your donor cannot match your result to your commitment."
        ),
    )
    _irc_widget(
        st.text_input,
        "Original target for this indicator (from logframe)",
        f"logframe_target{s}", default="",
        placeholder=_ph.get("logframe_target", "e.g., 250 youth trained by Q4 2025"),
        help=(
            "The target as approved in the original Technical Proposal. Donors compare achievements "
            "against approved targets — not revised internal targets."
        ),
    )
    _irc_widget(
        st.text_input,
        "Actual achievement (must match your result statement)",
        f"logframe_achievement{s}", default="",
        placeholder=_ph.get("logframe_achievement", "e.g., [Actual number] by [date] — [%] of original target"),
        help=(
            "The actual delivered number, ideally with % achievement vs original target. "
            "Must reconcile with your result statement above."
        ),
    )


def _render_tab3_slot(slot: int):
    s, _ph = _tab_slot_setup(slot)
    _render_fix_notes(slot, 2)
    with st.expander("📋 Evidence Details", expanded=True):
        _irc_widget(
            st.text_area, "Describe your supporting evidence", f"evidence_description{s}", default="",
            placeholder=_ph["evidence_description"],
            height=120,
            help="Describe the actual document or data: who collected it, how, and what's in it.",
        )
        _ed_val = st.session_state.get(f"evidence_description{s}", "")
        if _ed_val and len(_ed_val.strip()) < 30:
            st.warning("Evidence description is brief. Specify: who collected it, how, and what it contains.")
        if _ed_val:
            _meas_count = sum([
                any(kw in _ed_val.lower() for kw in ["survey", "interview", "kobo", "questionnaire", "instrument"]),
                any(kw in _ed_val.lower() for kw in ["sample", "random", "purposive", "stratified", "n="]),
                bool(_ed_val.strip()),
            ])
            _meas_score = round((_meas_count / 3) * 1.25, 2)
            st.caption(f"Measurement score contribution: **{_meas_score}/1.25** (method, sampling, description present)")

        _irc_widget(
            st.selectbox, "Evidence type", f"evidence_type{s}", default=EVIDENCE_TYPES[0],
            options=EVIDENCE_TYPES,
            help=EVIDENCE_TYPE_HELP,
        )
        ev_type = st.session_state.get(f"evidence_type{s}", EVIDENCE_TYPES[0])
        ev_desc = st.session_state.get(f"evidence_description{s}", "")
        _dl = _evaluator.get_directness_level(ev_type, ev_desc)
        _ds = round((_dl / 5) * 2.0, 1)
        st.caption(f"Directness score from this evidence type: **{_ds}/2.0**")

        _irc_widget(
            st.checkbox,
            "This result is evidenced qualitatively (case study, outcome harvesting, Most "
            "Significant Change, beneficiary voice) — score Definition and Measurement on "
            "qualitative dimensions instead of numeric precision",
            f"qualitative_evidence{s}", default=False,
        )
        is_qualitative_evidence = (
            ev_type in QUALITATIVE_EVIDENCE_TYPES
            or st.session_state.get(f"qualitative_evidence{s}", False)
        )

        _sub_lbl = "📝 Strengthen this evidence (optional — helps defend in donor reviews)"
        if ev_type == "Attendance sheets / participant registers":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Signatures verified against ID list", key=f"signatures_verified{s}")
                st.checkbox("Sheets dated and stamped", key=f"date_stamped{s}")
                st.checkbox("Cross-referenced with another source (e.g., facilitator notes)", key=f"cross_ref{s}")
        elif ev_type == "Raw datasets or survey exports":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Sampling method documented", key=f"sample_doc{s}")
                st.checkbox("Dataset cleaned and de-duplicated", key=f"clean_data{s}")
                st.checkbox("Original raw export retained for audit", key=f"version_ctrl{s}")
        elif ev_type == "Partner verification letters":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Letter on official partner letterhead", key=f"letterhead{s}")
                st.checkbox("Signed by authorized partner representative", key=f"authority_signed{s}")
                st.checkbox("Letter dated within 6 months of reporting period", key=f"recent_letter{s}")
        elif ev_type == "Photos with metadata":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Photos contain GPS metadata", key=f"gps_meta{s}")
                st.checkbox("Timestamps visible/verifiable", key=f"timestamp_photo{s}")
                st.checkbox("Beneficiary consent obtained for photos", key=f"consent_photo{s}")
        elif ev_type == "Tracer survey results":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Follow-up conducted at appropriate interval (3+ months)", key=f"followup_tracer{s}")
                st.checkbox("Response rate documented (target: 60%+)", key=f"response_rate{s}")
                st.checkbox("Sampling bias / non-response acknowledged", key=f"bias_ack{s}")
        elif ev_type == "Financial records":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Receipts/transactions dated", key=f"receipts_dated{s}")
                st.checkbox("Reconciled with bank/MoMo statements", key=f"reconciled_ev{s}")
                st.checkbox("Audit trail intact (request → approval → payment)", key=f"audit_trail_ev{s}")
        elif ev_type == "Third-party audits":
            with st.expander(_sub_lbl, expanded=st.session_state.get("_irc_used", False)):
                st.checkbox("Auditor independent from implementer", key=f"independent_ev{s}")
                st.checkbox("Audit report signed and dated", key=f"signed_audit{s}")
                st.checkbox("Audit recommendations addressed/disclosed", key=f"recommendations_ev{s}")
        elif is_qualitative_evidence:
            with st.expander(
                "📝 Qualitative Rigor — replaces Measurement and Definition with "
                "narrative-evidence dimensions",
                expanded=True,
            ):
                st.caption(
                    "These checks replace the Measurement and Definition sub-scores "
                    "for qualitative evidence."
                )
                (
                    _sourcing_lbl, _triangulated_lbl, _bias_lbl,
                    _voice_lbl, _consent_lbl,
                ) = QUAL_RIGOR_CHECKLIST.get(
                    ev_type, QUAL_RIGOR_CHECKLIST["Case study"]
                )
                _irc_widget(
                    st.checkbox, _sourcing_lbl,
                    f"qual_sourcing{s}", default=False,
                )
                _irc_widget(
                    st.checkbox, _triangulated_lbl,
                    f"qual_triangulated{s}", default=False,
                )
                _irc_widget(
                    st.checkbox, _bias_lbl,
                    f"qual_bias{s}", default=False,
                )
                _irc_widget(
                    st.checkbox, _voice_lbl,
                    f"qual_voice{s}", default=False,
                )
                _irc_widget(
                    st.checkbox, _consent_lbl,
                    f"qual_consent{s}", default=False,
                )
                _qual_meas_count = sum([
                    st.session_state.get(f"qual_sourcing{s}", False),
                    st.session_state.get(f"qual_triangulated{s}", False),
                    st.session_state.get(f"qual_bias{s}", False),
                ])
                _qual_meas_score = round((_qual_meas_count / 3) * 1.25, 2)
                st.caption(f"Sourcing & Triangulation contribution: **{_qual_meas_score}/1.25**")
                _qual_def_count = sum([
                    bool(st.session_state.get(f"timeframe{s}")),
                    st.session_state.get(f"qual_voice{s}", False),
                    st.session_state.get(f"qual_consent{s}", False),
                ])
                _qual_def_score = round((_qual_def_count / 3) * 1.25, 2)
                st.caption(f"Narrative Definition contribution: **{_qual_def_score}/1.25**")

        if ev_type == "Other":
            st.text_input("Specify evidence type", key=f"evidence_type_other{s}")

    with st.expander("✅ Verification & Reporting Period", expanded=True):
        int_rev = st.session_state.get(f"internal_review{s}", INTERNAL_REVIEW_OPTIONS[0])
        _irc_widget(
            st.selectbox, "Internal review", f"internal_review{s}", default=INTERNAL_REVIEW_OPTIONS[0],
            options=INTERNAL_REVIEW_OPTIONS,
            help="Did anyone in your organization review or cross-check this data?",
        )
        int_rev = st.session_state.get(f"internal_review{s}", INTERNAL_REVIEW_OPTIONS[0])
        _int_vl = _evaluator.get_verification_level(int_rev, "No external review", "")
        _int_vs = round((_int_vl / 5) * 2.0, 1)
        if _int_vs > 0:
            st.caption(f"Internal review adds **{_int_vs}/2.0** to Verification score")
        else:
            st.caption("⚠ No internal review: Verification score starts at 0. Adding a reviewer will improve this.")
        if int_rev == "Other":
            st.text_input("Specify internal reviewer", key=f"internal_review_other{s}")

        ext_rev = st.session_state.get(f"external_review{s}", EXTERNAL_REVIEW_OPTIONS[0])
        _irc_widget(
            st.selectbox, "External review", f"external_review{s}", default=EXTERNAL_REVIEW_OPTIONS[0],
            options=EXTERNAL_REVIEW_OPTIONS,
            help="Did an outside party verify the data? Government, partner, auditor, or evaluator.",
        )
        ext_rev = st.session_state.get(f"external_review{s}", EXTERNAL_REVIEW_OPTIONS[0])
        verifier_text = st.session_state.get(f"verifier{s}", "")
        _full_vl = _evaluator.get_verification_level(int_rev, ext_rev, verifier_text)
        _full_vs = round((_full_vl / 5) * 2.0, 1)
        _added   = round(_full_vs - _int_vs, 1)
        if _added > 0:
            st.caption(f"External review adds **+{_added}** more → total Verification: **{_full_vs}/2.0**")
        elif ext_rev == "No external review":
            st.caption("⚠ No external review: adding independent verification can raise this score significantly.")
        else:
            st.caption(f"Total Verification: **{_full_vs}/2.0**")
        if ext_rev == "Other":
            st.text_input("Specify external reviewer", key=f"external_review_other{s}")

        _irc_widget(
            st.text_input, "Who verified this?", f"verifier{s}", default="",
            placeholder=_ph.get("verifier", "e.g., District Agriculture Officer, partner org M&E lead, external evaluator"),
            help="The person or organization that confirmed the data is accurate.",
        )

        st.markdown("#### Data Collection & Provenance")
        st.caption(
            "These answer whether the data was collected soundly — they adjust your "
            "Verification score (USAID DQA Reliability/Precision). Answer 'Not applicable' "
            "where it honestly doesn't apply — that's neutral. Leaving an item unanswered "
            "is treated the same as 'No' and lowers the score."
        )
        _irc_widget(
            st.selectbox, "Sampling or selection method documented (who was included, and how)",
            f"provenance_sampling{s}", default=PROVENANCE_YES_NO_NA_OPTIONS[0],
            options=PROVENANCE_YES_NO_NA_OPTIONS,
        )
        _irc_widget(
            st.selectbox, "Checked for double-counting (no beneficiary or result counted twice "
            "across activities or periods)", f"provenance_dedup{s}", default=PROVENANCE_YES_NO_NA_OPTIONS[0],
            options=PROVENANCE_YES_NO_NA_OPTIONS,
        )
        _irc_widget(
            st.selectbox, "Data-collection tool/method identified (e.g. KoboToolbox, paper form, "
            "admin records)", f"provenance_tool{s}", default=PROVENANCE_YES_NO_NA_OPTIONS[0],
            options=PROVENANCE_YES_NO_NA_OPTIONS,
        )
        _irc_widget(
            st.selectbox, "Data collected by someone independent of those reporting the result "
            "(enumerator-bias risk)", f"provenance_independence{s}", default=PROVENANCE_YES_NO_NA_OPTIONS[0],
            options=PROVENANCE_YES_NO_NA_OPTIONS,
        )
        _irc_widget(
            st.selectbox, "Recall-period risk assessed (data collected close to the event, or "
            "recall bias mitigated)", f"provenance_recall{s}", default=PROVENANCE_YES_NO_NA_OPTIONS[0],
            options=PROVENANCE_YES_NO_NA_OPTIONS,
        )
        _irc_widget(
            st.selectbox, "Could an external auditor retrieve the original records referenced "
            "above?", f"provenance_traceability{s}", default=TRACEABILITY_OPTIONS[0],
            options=TRACEABILITY_OPTIONS,
            help="E.g. raw survey exports, signed registers, payment records.",
        )
        _prov_checklist = {
            "sampling_documented":     st.session_state.get(f"provenance_sampling{s}", PROVENANCE_YES_NO_NA_OPTIONS[0]),
            "double_counting_checked": st.session_state.get(f"provenance_dedup{s}", PROVENANCE_YES_NO_NA_OPTIONS[0]),
            "collection_tool_named":   st.session_state.get(f"provenance_tool{s}", PROVENANCE_YES_NO_NA_OPTIONS[0]),
            "collector_independent":   st.session_state.get(f"provenance_independence{s}", PROVENANCE_YES_NO_NA_OPTIONS[0]),
            "recall_period_ok":        st.session_state.get(f"provenance_recall{s}", PROVENANCE_YES_NO_NA_OPTIONS[0]),
            "auditor_traceable":       st.session_state.get(f"provenance_traceability{s}", TRACEABILITY_OPTIONS[0]),
        }
        _prov_adj = _evaluator.get_provenance_adjustment(_prov_checklist)
        if _prov_adj > 0:
            st.caption(f"Provenance answers add **+{_prov_adj}** to Verification score (capped at 2.0/2.0 total)")
        elif _prov_adj < 0:
            st.caption(f"⚠ Unanswered provenance items currently subtract **{_prov_adj}** from your Verification score.")
        else:
            st.caption("Completing this checklist can add up to **+0.6** to your Verification score.")

        st.markdown("#### Reporting Period")
        st.caption("The period this submission covers. Evidence dates outside this range will be flagged.")
        _rp_c1, _rp_t1 = st.columns([5, 1])
        with _rp_c1:
            _irc_widget(
                st.date_input, "Reporting period start", f"reporting_start{s}", default=date.today(),
                help="When does the period this report covers begin?")
        with _rp_t1:
            st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
            if st.button("Today", key=f"today_rp_start{s}"):
                st.session_state[f"reporting_start{s}"] = date.today()
                st.rerun()
        _rp_s_val = st.session_state.get(f"reporting_start{s}")
        if _rp_s_val and _rp_s_val > date.today():
            st.caption("⚠ This date is in the future.")

        _rp_c2, _rp_t2 = st.columns([5, 1])
        with _rp_c2:
            _irc_widget(
                st.date_input, "Reporting period end", f"reporting_end{s}", default=date.today(),
                help="When does the period this report covers end?")
        with _rp_t2:
            st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
            if st.button("Today", key=f"today_rp_end{s}"):
                st.session_state[f"reporting_end{s}"] = date.today()
                st.rerun()
        _rp_e_val = st.session_state.get(f"reporting_end{s}")
        if _rp_e_val and _rp_e_val > date.today():
            st.caption("⚠ This date is in the future.")

        _ev_c, _ev_t = st.columns([5, 1])
        with _ev_c:
            _irc_widget(
                st.date_input, "When was this evidence collected?", f"evidence_date{s}", default=date.today(),
                help="When was the data collected? Use the most recent date if multiple sources.",
            )
        with _ev_t:
            st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
            if st.button("Today", key=f"today_ev_date{s}"):
                st.session_state[f"evidence_date{s}"] = date.today()
                st.rerun()
        _ed = st.session_state.get(f"evidence_date{s}")
        if _ed and _ed > date.today():
            st.caption("⚠ This date is in the future.")
        if _ed and hasattr(_evaluator, "get_recency_diagnostic"):
            _rec_diag = _evaluator.get_recency_diagnostic(_ed)
            if "0.4/1.0" in _rec_diag or "0.2/1.0" in _rec_diag:
                st.warning(_rec_diag)
            elif "0.6/1.0" in _rec_diag:
                st.info(_rec_diag)
            else:
                st.success(_rec_diag)
        _rp_s = st.session_state.get(f"reporting_start{s}")
        _rp_e = st.session_state.get(f"reporting_end{s}")
        if _ed and _rp_s and _rp_e and hasattr(_evaluator, "validate_reporting_period"):
            _, _rp_msg, _rp_sev = _evaluator.validate_reporting_period(_ed, _rp_s, _rp_e)
            if _rp_sev == "ERROR":
                st.error(_rp_msg)
            elif _rp_sev == "WARNING":
                st.warning(_rp_msg)
            elif _rp_msg:
                st.success(_rp_msg)

    st.markdown("#### Beneficiary Voice")
    st.caption(
        "Did the beneficiaries contribute to or validate this evidence? "
        "Anchored in Bond Evidence Principles 2024 + 60 Decibels Lean Data."
    )
    st.selectbox(
        "How were beneficiary voices captured?",
        key=f"beneficiary_voice{s}",
        options=_BV_OPTIONS,
        help=(
            "Bond Evidence Principle 1 (2024 refresh): Voice & Inclusion. "
            "The strongest evidence includes beneficiary perspectives, not just provider reports."
        ),
    )
    _bv_val = st.session_state.get(f"beneficiary_voice{s}", "")
    _bv_score = (_evaluator.compute_beneficiary_voice_bonus(_bv_val)
                 if hasattr(_evaluator, "compute_beneficiary_voice_bonus") else 0.0)
    # --- UX: CONDITIONAL FIELDS (v3.2) ---
    if _bv_val and _bv_val not in ("No beneficiary voice captured", "Choose an option..."):
        st.caption(f"Beneficiary Voice bonus: **+{_bv_score}/0.5** (Bond Evidence Principles 2024)")
    # --- END UX: CONDITIONAL FIELDS (v3.2) ---

    # --- GOVERNANCE & COMPLIANCE LAYER (v3.2) ---
    _ev_type_now = st.session_state.get(f"evidence_type{s}", "")
    _pii_triggered = _ev_type_now in PII_EVIDENCE_TYPES
    _safeguarding_triggered = _ev_type_now in SAFEGUARDING_EVIDENCE_TYPES
    _minors_triggered = _minors_possibly_involved(slot)
    st.markdown("---")
    with st.expander("🛡️ Compliance & Data Governance", expanded=_pii_triggered or _safeguarding_triggered or _minors_triggered or st.session_state.get("_irc_used", False)):
        st.subheader("🛡️ Compliance & Ethics Check")
        st.caption("*Ensure your evidence is not just credible — but legally safe and safe for the people in it.*")
        if _pii_triggered:
            st.warning(
                "⚠️ **PII Alert:** One or more of your selected evidence types may "
                "contain Personally Identifiable Information (PII). Please answer the "
                "compliance checks below before proceeding."
            )
        if _safeguarding_triggered:
            st.warning(
                "⚠️ **Safeguarding Alert:** This evidence type may include beneficiary "
                "stories, photos, or testimony. Please confirm consent, a do-no-harm "
                "review, and secure handling below before proceeding."
            )
        if _minors_triggered:
            st.error(
                "🔴 **Child Safeguarding Alert:** This result statement or target group "
                "may involve minors. Please complete the child safeguarding check below "
                "(Core Humanitarian Standard, Commitment 4 — Keeping Children Safe)."
            )
        with st.expander(
            "📋 Data Governance Checklist (expand to complete)",
            expanded=_pii_triggered or _safeguarding_triggered or _minors_triggered,
        ):
            st.selectbox(
                "Do you have documented consent from beneficiaries for their data "
                "to be shared with the donor?",
                options=[
                    "Select consent status...",
                    "Yes — written consent forms on file",
                    "Yes — verbal consent documented",
                    "Partial — some beneficiaries consented",
                    "No — consent not obtained",
                    "Not applicable (no personal data)",
                ],
                key=f"gov_consent_status{s}",
            )
            st.selectbox(
                "Has this evidence been anonymized or de-identified where required?",
                options=[
                    "Select anonymization status...",
                    "Yes — fully anonymized",
                    "Partially anonymized",
                    "No — not anonymized",
                    "Not applicable",
                ],
                key=f"gov_anonymization_status{s}",
            )
            st.selectbox(
                "Does your evidence collection method comply with the data protection "
                "law in your project's country?",
                options=[
                    "Select compliance status...",
                    "Yes — compliant (e.g. Ghana Act 843, Nigeria NDPA, Kenya DPA)",
                    "Unsure — we haven't checked",
                    "No — we are not compliant",
                    "Not applicable",
                ],
                key=f"gov_compliance_law_status{s}",
            )
            st.selectbox(
                "If this evidence includes beneficiary stories, photos, or testimony, "
                "has it been reviewed for do-no-harm risks (identification, stigma, "
                "retraumatization, or safety) before sharing with the donor?",
                options=[
                    "Select safeguarding status...",
                    "Yes — reviewed, no concerns identified",
                    "Yes — reviewed, identifying details removed",
                    "Partial — some content not yet reviewed",
                    "No — not yet reviewed",
                    "Not applicable (no beneficiary stories/photos)",
                ],
                key=f"gov_safeguarding_status{s}",
            )
            st.selectbox(
                "If minors may be involved in this evidence, has a child safeguarding "
                "review been completed (organisational child safeguarding policy applied, "
                "and guardian consent obtained where applicable)?",
                options=[
                    "Select child safeguarding status...",
                    "Yes — child safeguarding policy applied, guardian consent obtained where applicable",
                    "Partial — some steps taken but not complete",
                    "No — not yet reviewed",
                    "Not applicable (no minors involved)",
                ],
                key=f"gov_child_safeguarding_status{s}",
            )
            st.selectbox(
                "If this evidence includes identifiable testimony, photos, or stories, "
                "is it stored securely with access limited to authorised staff "
                "(e.g. password-protected files, restricted folders)?",
                options=[
                    "Select secure handling status...",
                    "Yes — stored securely, access restricted to authorised staff",
                    "Partial — some identifiable material not yet secured",
                    "No — not yet secured",
                    "Not applicable (no identifiable testimony/photos)",
                ],
                key=f"gov_secure_handling_status{s}",
            )
        st.markdown(
            "#### 📁 Upload Organisational Data Protection Policy "
            "(optional — earns Governance Bonus)"
        )
        _dpp_file = st.file_uploader(
            "Upload your data protection policy (PDF or DOCX)",
            type=["pdf", "docx"],
            key=f"gov_dpp_upload{s}",
        )
        if _dpp_file is not None:
            st.session_state["gov_dpp_uploaded"] = True
            st.caption(
                "✅ Policy uploaded. **+5 Governance Bonus** applied to your "
                "Confidence Score for this session."
            )
        else:
            st.caption(
                "Uploading your policy grants a +5 Governance Bonus to your "
                "Confidence Score for this session."
            )
    # --- END GOVERNANCE & COMPLIANCE LAYER (v3.2) ---

    # --- ADVISORY CHECKLIST (v3.4, score-neutral) ---
    with st.expander("📊 Reporting Quality Checklist (optional, advisory only)", expanded=st.session_state.get("_irc_used", False)):
        st.caption("These do not affect your Confidence or Clarity scores — they appear as advisory flags in your report.")
        st.selectbox(
            "Does your report distinguish attribution from contribution?",
            options=["Not specified", "Yes", "No", "Not sure"],
            key=f"attribution_contribution{s}",
            help=(
                "Attribution claims your program caused the change on its own. "
                "Contribution acknowledges your program was one of several "
                "contributing factors alongside others."
            ),
        )
        st.selectbox(
            "Is beneficiary data disaggregated (women, youth, PWD, rural)?",
            options=["Not specified", "Yes — fully disaggregated", "Partially disaggregated", "No"],
            key=f"disaggregation_status{s}",
            help="Many funders now expect results broken down by sex, age, disability, and location.",
        )
        st.divider()
        st.text_area(
            "What did you learn from this result, and how did your program adapt? (optional)",
            key=f"learning_notes{s}",
            placeholder=(
                "e.g., We learned that follow-up calls increased survey response rates, "
                "so we adjusted our M&E plan to include monthly check-ins."
            ),
            help=(
                "Funders increasingly look for evidence of learning and adaptation. "
                "This appears as a Funder Readiness flag in your report — it does not "
                "affect your Confidence or Clarity scores."
            ),
        )
        st.text_area(
            "What can this data NOT confirm or be generalized to? (optional)",
            key=f"limitations_notes{s}",
            placeholder=(
                "e.g., This sample covers only urban participants and cannot be "
                "generalized to rural areas."
            ),
            help=(
                "Disclosing limitations builds credibility. This appears as a Funder "
                "Readiness flag in your report — it does not affect your Confidence or "
                "Clarity scores."
            ),
        )
        st.text_area(
            "Who owns this result, and what decision will it inform? (optional — improves Clarity)",
            key=f"additional_context{s}",
            placeholder=(
                "e.g., The MEL Lead owns this result. It will inform the Q3 budget "
                "reallocation decision for the livelihoods component."
            ),
            help=(
                "Naming an owner and the decision this result informs strengthens your "
                "Governance sub-score (part of Clarity)."
            ),
        )
    # --- END ADVISORY CHECKLIST (v3.4/v3.5) ---

    prev_files = st.session_state.get(f"draft_uploaded_filenames{s}", [])
    if prev_files:
        st.caption(f"Previously attached: {', '.join(prev_files)} — please re-attach below.")
    st.file_uploader(
        "Attach supporting documents (optional)", key=f"uploaded_files_widget{s}",
        accept_multiple_files=True,
        type=["pdf", "docx", "xlsx", "csv", "jpg", "jpeg", "png", "txt"],
        help="Attach raw evidence files — datasets, signed sheets, photos with metadata, partner letters.",
    )


# ---------------------------------------------------------------------------
# Screen 0 — Landing & Onboarding
# ---------------------------------------------------------------------------

# Pre-filled Ghana health NGO example — used by the "Try with a sample result" button.
# Values must be valid entries from the relevant option lists (EVIDENCE_TYPES,
# INTERNAL_REVIEW_OPTIONS, EXTERNAL_REVIEW_OPTIONS, _BV_OPTIONS, SECTOR_OPTIONS).
_DEMO_SUBMISSION = {
    # _BASE_FORM_KEYS text fields (slot 1, no suffix)
    "result_statement":    (
        "450 women of reproductive age in Ashanti Region received skilled antenatal care across "
        "3 health facilities, resulting in a 34% reduction in preventable maternal complications "
        "between January and December 2024 compared to the 2022 baseline."
    ),
    "target_group":        "Women of reproductive age (15–49) in peri-urban Kumasi",
    "timeframe":           "January – December 2024",
    "geographic_scope":    "Ashanti Region, Ghana (3 health facilities)",
    "evidence_description":(
        "Monthly DHIS2 data extracted from 3 facility registers by the district health "
        "information officer and verified against paper attendance registers by the project "
        "MEL officer."
    ),
    "logframe_indicator":  "% reduction in preventable maternal complications among ANC attendees",
    "logframe_target":     "30% reduction by December 2024",
    "logframe_achievement":"34% reduction (450 women served across 3 facilities)",
    "verifier":            "District Health Information Officer (independent of programme delivery)",
}
# Selectbox fields set separately (must match their option lists exactly)
_DEMO_SELECT_FIELDS = {
    "evidence_type":    "Raw datasets or survey exports",
    "internal_review":  "Reviewed by MEL Officer",
    "external_review":  "External partner review",
    "beneficiary_voice":"Anecdotal beneficiary quotes only (uncollected, not systematic)",
    "sector":           "Health",
    "donor_selected":   "USAID",
    "donor_framework":  "USAID",
}


def _complete_email_login(email: str) -> None:
    st.session_state["user_email"] = email
    upsert_user(email)
    _u = get_user(email)
    if _u and is_still_paid(_u):
        st.session_state["is_paid"] = True
    _pending_ref = st.session_state.pop("pending_paystack_ref", None)
    if _pending_ref:
        _pr = verify_payment(_pending_ref)
        if _pr.get("status") == "success":
            _pr_days = 30 if _pr.get("plan") == "monthly" else 1
            mark_paid(email, days=_pr_days)
            st.session_state["is_paid"] = True
    for _k in ("_otp_email", "_otp_code", "_otp_sent_at", "_otp_attempts"):
        st.session_state.pop(_k, None)
    st.rerun()


def _render_email_gate_inline(form_key_suffix: str = "") -> None:
    """Inline email-collection widget (OTP or simple). Stops rendering after display."""
    if otp_enabled() and st.session_state.get("_otp_email"):
        _otp_email = st.session_state["_otp_email"]
        if time.time() - st.session_state.get("_otp_sent_at", 0) > 600:
            st.warning("Your verification code expired. Please request a new one.")
            for _k in ("_otp_email", "_otp_code", "_otp_sent_at", "_otp_attempts"):
                st.session_state.pop(_k, None)
            st.rerun()
        st.caption(f"We sent a 6-digit code to **{_otp_email}**. Enter it below (expires in 10 minutes).")
        with st.form(f"otp_verify_form{form_key_suffix}"):
            _otp_input = st.text_input("Verification code", max_chars=6, placeholder="123456")
            _verify_clicked = st.form_submit_button("Verify →", use_container_width=True)
        if _verify_clicked:
            if _otp_input.strip() == st.session_state.get("_otp_code"):
                _complete_email_login(_otp_email)
            else:
                st.session_state["_otp_attempts"] = st.session_state.get("_otp_attempts", 0) + 1
                if st.session_state["_otp_attempts"] >= 5:
                    st.error("Too many incorrect attempts. Please request a new code.")
                    for _k in ("_otp_email", "_otp_code", "_otp_sent_at", "_otp_attempts"):
                        st.session_state.pop(_k, None)
                    st.rerun()
                else:
                    st.error("Incorrect code. Please try again.")
        _otp_c1, _otp_c2 = st.columns(2)
        with _otp_c1:
            if st.button("Resend code", use_container_width=True, key=f"resend_otp{form_key_suffix}"):
                _new_code = generate_otp()
                with st.spinner("Sending verification code…"):
                    _ok, _err = send_otp_email(_otp_email, _new_code)
                if _ok:
                    st.session_state["_otp_code"] = _new_code
                    st.session_state["_otp_sent_at"] = time.time()
                    st.session_state["_otp_attempts"] = 0
                    st.success("A new code has been sent.")
                else:
                    st.error(f"Could not send code: {_err}")
        with _otp_c2:
            if st.button("Use a different email", use_container_width=True, key=f"diff_email{form_key_suffix}"):
                for _k in ("_otp_email", "_otp_code", "_otp_sent_at", "_otp_attempts"):
                    st.session_state.pop(_k, None)
                st.rerun()
    else:
        st.caption(
            "No password needed. We'll email you a 6-digit code to confirm it's yours."
            if otp_enabled() else
            "No password needed. We use your email to save your paid access."
        )
        with st.form(f"email_gate_form{form_key_suffix}"):
            _gate_email = st.text_input("Email address", placeholder="you@organisation.org")
            _submit_label = "Send verification code" if otp_enabled() else "Continue →"
            if st.form_submit_button(_submit_label, use_container_width=True):
                if "@" not in _gate_email or "." not in _gate_email.split("@")[-1]:
                    st.warning("Please enter a valid email address.")
                elif _is_disposable_email(_gate_email):
                    st.warning("Please use a permanent work or personal email — temporary addresses aren't accepted.")
                else:
                    _e = _gate_email.strip().lower()
                    if otp_enabled():
                        _code = generate_otp()
                        with st.spinner("Sending verification code…"):
                            _ok, _err = send_otp_email(_e, _code)
                        if _ok:
                            st.session_state["_otp_email"] = _e
                            st.session_state["_otp_code"] = _code
                            st.session_state["_otp_sent_at"] = time.time()
                            st.session_state["_otp_attempts"] = 0
                            st.rerun()
                        else:
                            st.error(f"Could not send verification email: {_err}")
                    else:
                        _complete_email_login(_e)
    st.stop()


# ============================================================
# MATCH DAY — Patch 1: Scoreboard + Commentary ticker
# ============================================================

def inject_matchday_css():
    """Call ONCE per run, after st.set_page_config()."""
    st.markdown("""
    <style>
    .md-ticker { background:#2C2C2A; color:#fff; border-radius:8px; padding:10px 14px;
        font-size:14px; display:flex; align-items:center; gap:10px; margin:0 0 14px 0; }
    .md-ticker .mic { background:#A32D2D; color:#fff; font-size:9px; font-weight:600;
        padding:2px 6px; border-radius:4px; letter-spacing:.5px; flex-shrink:0; }
    .md-ticker .txt { line-height:1.4; }
    .md-sb { background:#fff; border:1px solid #d3d1c7; border-radius:12px;
        overflow:hidden; margin:0 0 16px 0; }
    .md-sb-head { background:#2C2C2A; color:#fff; padding:8px 16px; font-size:11px;
        letter-spacing:1px; text-transform:uppercase; display:flex;
        justify-content:space-between; align-items:center; }
    .md-sb-live { font-size:10px; }
    .md-sb-body { display:grid; grid-template-columns:1fr 1px 1fr; }
    .md-stat { padding:18px 16px; text-align:center; }
    .md-stat .name { font-size:12px; color:#888780; margin-bottom:4px; }
    .md-stat .val { font-size:34px; font-weight:600; line-height:1; }
    .md-stat .sub { font-size:11px; color:#888780; margin-top:6px; }
    .md-div { background:#d3d1c7; }
    .md-green { color:#1D9E75; } .md-amber { color:#BA7517; } .md-red { color:#A32D2D; }
    .md-var { background:#1a1a18; color:#fff; border-radius:12px;
        padding:24px 20px; margin:16px 0; display:flex; align-items:center; gap:18px; }
    .md-var-badge { background:#A32D2D; color:#fff; font-size:11px; font-weight:700;
        padding:6px 10px; border-radius:6px; letter-spacing:1.5px; flex-shrink:0; }
    .md-var-text strong { font-size:1rem; }
    .md-var-text span { font-size:0.85rem; color:#aaa8a0; }
    .md-pitch { background:#1a1a18; border-radius:0; padding:10px 16px;
        margin:0; position:fixed; top:3.75rem; left:0; right:0; z-index:9999; }
    .md-pitch-stages { display:flex; align-items:flex-start; justify-content:space-between;
        position:relative; }
    .md-pitch-stages::before { content:""; position:absolute; top:16px; left:10%; right:10%;
        height:2px; background:#333; z-index:0; }
    .md-pstage { display:flex; flex-direction:column; align-items:center; gap:6px;
        flex:1; position:relative; z-index:1; cursor:help; }
    .md-pstage .dot { width:32px; height:32px; border-radius:50%; background:#333;
        color:#666; font-size:12px; font-weight:700; display:flex;
        align-items:center; justify-content:center; }
    .md-pstage .lbl { font-size:10px; color:#555; text-align:center; letter-spacing:.3px; }
    .md-pstage.done .dot { background:#1D9E75; color:#fff; }
    .md-pstage.done .lbl { color:#1D9E75; }
    .md-pstage.active .dot { background:#FAC775; color:#1a1a18; }
    .md-pstage.active .lbl { color:#FAC775; font-weight:600; }
    .md-pstage:hover .lbl { text-decoration: underline dotted; }
    .md-fulltime { background:#2C2C2A; color:#fff; border-radius:12px;
        padding:20px 20px 16px; margin:12px 0; text-align:center; }
    .md-fulltime .whistle { font-size:10px; letter-spacing:1.5px; text-transform:uppercase;
        color:#888780; margin-bottom:8px; }
    .md-fulltime h3 { margin:0 0 8px; font-size:1.3rem; color:#FAC775; }
    .md-fulltime p { margin:0; font-size:0.85rem; color:#aaa8a0; line-height:1.5; }
    .md-card { background:#f9f8f5; border:1px solid #e0ded8; border-radius:10px;
        padding:14px 16px; margin:8px 0; }
    </style>
    """, unsafe_allow_html=True)


MATCHDAY_COMMENTARY = {
    "enter":    "Kickoff. Your indicators are taking the field — let's line them up.",
    "logframe": "Good movement — let's see which indicators find a home in the logframe.",
    "evidence": "The goal is being checked. VAR is reviewing the evidence before anything counts.",
    "review":   "Decision time. Submit as-is, or strengthen a flagged claim before you shoot.",
    "report":   "Full time. Here's your result and the official match report.",
}


def render_commentary(stage_key: str):
    """Renders the one-line match commentary for the given stage."""
    line = MATCHDAY_COMMENTARY.get(stage_key, "")
    if not line:
        return
    st.markdown(
        f'<div class="md-ticker"><span class="mic">LIVE</span>'
        f'<span class="txt">{line}</span></div>',
        unsafe_allow_html=True,
    )


def _score_class(value, verified):
    if value is None or not verified:
        return "md-amber"
    if value >= 70:
        return "md-green"
    if value >= 50:
        return "md-amber"
    return "md-red"


def render_scoreboard(confidence=None, clarity=None, verified=False):
    """Two-stat match scoreboard for Confidence and Clarity (0-100 scale)."""
    conf_txt = "—" if confidence is None else str(int(round(confidence)))
    clar_txt = "—" if clarity is None else str(int(round(clarity)))
    conf_cls = _score_class(confidence, verified)
    clar_cls = _score_class(clarity, verified)
    status = "● final" if verified else "● provisional"
    status_color = "#9FE1CB" if verified else "#FAC775"
    st.markdown(f"""
    <div class="md-sb">
      <div class="md-sb-head"><span>Match stats</span>
        <span class="md-sb-live" style="color:{status_color}">{status}</span></div>
      <div class="md-sb-body">
        <div class="md-stat"><div class="name">Confidence</div>
          <div class="val {conf_cls}">{conf_txt}</div>
          <div class="sub">is the evidence trustworthy?</div></div>
        <div class="md-div"></div>
        <div class="md-stat"><div class="name">Clarity</div>
          <div class="val {clar_cls}">{clar_txt}</div>
          <div class="sub">is the claim well-stated?</div></div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_var_review():
    """Dark VAR panel shown while the confidence check is running."""
    st.markdown(
        '<div class="md-var">'
        '<div class="md-var-badge">VAR</div>'
        '<div class="md-var-text">'
        '<strong>VAR Review in progress</strong><br>'
        '<span>Checking video evidence — the official decision is coming.</span>'
        '</div></div>',
        unsafe_allow_html=True,
    )


MATCHDAY_STAGES = [
    ("enter",    "Line-up"),
    ("logframe", "Build-up"),
    ("evidence", "VAR"),
    ("review",   "The shot"),
    ("report",   "Full time"),
]

MATCHDAY_TIPS = {
    "enter":    "Step 1 — Define your result: who benefited, what changed, where and when",
    "logframe": "Step 2 — Link your result to your logframe indicator and target",
    "evidence": "VAR · Verification Assistant Referee — evidence check before your score counts",
    "review":   "Step 4 — Add donor context and submit for your Confidence &amp; Clarity scores",
    "report":   "Full time — your Confidence &amp; Clarity scores and verdict are in",
}


def render_pitch_strip(current_stage: str):
    keys = [k for k, _ in MATCHDAY_STAGES]
    try:
        cur = keys.index(current_stage)
    except ValueError:
        cur = -1
    cells = ""
    for idx, (k, lbl) in enumerate(MATCHDAY_STAGES):
        cls = "done" if idx < cur else ("active" if idx == cur else "")
        mark = "✓" if idx < cur else str(idx + 1)
        tip = MATCHDAY_TIPS.get(k, "")
        cells += (f'<div class="md-pstage {cls}" title="{tip}"><div class="dot">{mark}</div>'
                  f'<div class="lbl">{lbl}</div></div>')
    st.markdown(
        f'<div class="md-pitch"><div class="md-pitch-stages">{cells}</div></div>'
        f'<div style="height:64px"></div>',
        unsafe_allow_html=True,
    )


def _esc(s: str) -> str:
    import html
    return html.escape(str(s))


def render_fulltime(confidence, clarity, summary):
    """Final-result card. Render directly above your st.download_button().

    confidence / clarity : final 0-100 scores (verified).
    summary : a short honest sentence about the result.
    """
    conf_txt = "—" if confidence is None else str(int(round(confidence)))
    clar_txt = "—" if clarity is None else str(int(round(clarity)))
    st.markdown(f"""
    <div class="md-fulltime">
      <div class="whistle">Full-time whistle</div>
      <h3>Confidence {conf_txt} · Clarity {clar_txt}</h3>
      <p>{_esc(summary)}</p>
    </div>
    """, unsafe_allow_html=True)


def render_season_teaser():
    """One-line hook seeding the Phase 2 'Integrity League'. Copy only."""
    st.markdown(
        '<div class="md-card" style="text-align:center;">'
        '<h4 style="margin:0 0 4px 0;">Season record</h4>'
        '<p style="font-size:12px;color:#888780;margin:0;">This match is logged to your '
        'integrity record. Your rating rises only on verified evidence — never on volume. '
        '(Coming soon.)</p></div>',
        unsafe_allow_html=True,
    )


def render_screen_0():
    _logo_path = pathlib.Path(__file__).parent / "logo.png.png"
    try:
        _logo_b64 = base64.b64encode(_logo_path.read_bytes()).decode()
        _logo_tag = (
            f'<div style="display:flex; align-items:center; gap:14px; margin-bottom:12px;">'
            f'<img src="data:image/png;base64,{_logo_b64}" alt="Impact-Receipts" style="height:56px;">'
            f'<span style="font-size:0.9rem; font-weight:600; line-height:1.2;">'
            f'<span style="color:#1B5E20;">Impact Integrity Diagnostic</span><br>'
            f'<span style="color:#8A6500; font-weight:400;">Pre-submission result checker for NGOs</span>'
            f'</span>'
            f'</div>'
        )
    except FileNotFoundError:
        _logo_tag = (
            '<div style="display:flex; align-items:center; gap:14px; margin-bottom:12px;">'
            '<span style="font-size:0.9rem; font-weight:600; line-height:1.2;">'
            '<span style="color:#1B5E20;">Impact Integrity Diagnostic</span><br>'
            '<span style="color:#8A6500; font-weight:400;">Pre-submission result checker for NGOs</span>'
            '</span>'
            '</div>'
        )
    st.markdown(
        f"""
        <div class="hero-block">
          {_logo_tag}
          <h1>Know which reported results are strong, weak, or need fixing — before your donor sees them.</h1>
          <p class="hero-tagline">See if your evidence is strong and your result statement is clear enough — before your donor asks.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("On a slow connection? Open the sidebar («, top-left) and turn on ⚡ Low-bandwidth mode.")

    if st.button("Score My Result Statement →", type="primary", use_container_width=True, key="cta_top"):
        if not st.session_state.get("has_seen_tutorial"):
            st.session_state["tutorial_step"] = 1
        _go_to_screen(1, reset=True)

    if st.button("📊 Portfolio Dashboard — score my whole logframe", use_container_width=True, key="cta_portfolio"):
        _go_to_screen(3)

    st.caption("No data to hand? Try a pre-filled Ghana health example:")
    if st.button("🚀 Try with a sample result →", key="cta_demo",
                 help="Loads a realistic ANC result from Ashanti Region — runs in seconds"):
        for _k, _v in _DEMO_SUBMISSION.items():
            st.session_state[_k] = _v
        for _k, _v in _DEMO_SELECT_FIELDS.items():
            st.session_state[_k] = _v
        if not st.session_state.get("has_seen_tutorial"):
            st.session_state["tutorial_step"] = 1
        _go_to_screen(1)


    st.markdown(
        """
        <div>
          <p class="hero-sub">
            The Impact Integrity Diagnostic is built for Monitoring, Evaluation &amp; Learning Officers and Reporting Leads at NGOs
            and donor-funded projects in Africa &mdash; those compiling final reports for USAID,
            FCDO, GIZ, RVO, World Bank, AfDB, EU/EuropeAid, and others.
          </p>
          <p class="brand-promise">I help you submit with confidence &mdash; not by judging your work,
          but by showing you exactly where it&rsquo;s strong and where it needs strengthening.</p>
          <ol class="how-it-works" style="margin:10px 0 0 0; padding-left:20px; color:#374151; font-size:0.95rem;">
            <li>Add your result statement</li>
            <li>Describe your supporting evidence</li>
            <li>Get a confidence label + specific fixes &mdash; in 10 minutes</li>
          </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="border-left:4px solid #8A6500; border-radius:8px; padding:14px 20px; margin:16px 0; background:transparent;">
          <p style="margin:0; font-size:0.95rem; color:#212121;">
            <strong>Funders now ask:</strong> What changed? How do you know? How strong is the evidence?
            What did you learn? &mdash; <em>This check tells you before they do.</em>
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="what-we-check" style="border-radius:8px;padding:16px 20px;
                    margin:16px 0;border-left:4px solid #1B5E20;">
          <h4 style="margin:0 0 10px 0;">&#128203; What we check</h4>
          <ul style="margin:0;padding-left:18px;">
            <li style="margin-bottom:6px;"><strong>Logframe linkage</strong>
              &mdash; does your result tie to an approved indicator?</li>
            <li style="margin-bottom:6px;"><strong>Evidence quality</strong>
              &mdash; direct, verified, recent, defensible?</li>
            <li style="margin-bottom:6px;"><strong>Beneficiary voice</strong>
              &mdash; were they part of the evidence?</li>
            <li style="margin-bottom:6px;"><strong>Definition clarity</strong>
              &mdash; would two readers interpret it the same way?</li>
            <li><strong>Submission completeness</strong>
              &mdash; is your package donor-ready?</li>
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="is-not-grid">
          <div class="is-col" style="color: #1B5E20 !important;">
            <h4>&#10003; What this IS</h4>
            <ul style="color: #1B5E20 !important;">
              <li style="color: #1B5E20 !important;">A quick confidence check for reported results before submission</li>
              <li style="color: #1B5E20 !important;">A transparent guide that shows what to fix and why</li>
              <li style="color: #1B5E20 !important;">Privacy-conscious — your raw documents are processed and discarded, never stored</li>
              <li style="color: #1B5E20 !important;">Your first 3 checks are free</li>
            </ul>
          </div>
          <div class="isnot-col" style="color: #C62828 !important;">
            <h4 style="color: #C62828 !important;">&#10007; What this is NOT</h4>
            <ul style="color: #C62828 !important;">
              <li style="color: #C62828 !important;">A full reporting system, database, or audit tool</li>
              <li style="color: #C62828 !important;">A replacement for your M&amp;E/MEL framework</li>
              <li style="color: #C62828 !important;">An AI that invents or assumes missing data</li>
              <li style="color: #C62828 !important;">A gatekeeper that decides who passes or fails</li>
            </ul>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("📁 Resume a previous session"):
        uploaded_json = st.file_uploader(
            "Upload a previously saved inputs JSON",
            type=["json"],
            key="resume_json_upload",
            help="Upload a JSON file previously downloaded via 'Download Draft (JSON)' on the Review & Submit tab.",
        )
        if uploaded_json is not None:
            try:
                data = json.loads(uploaded_json.read())
                _load_from_inputs_json(data)
            except Exception as exc:
                st.error(f"Could not read the file: {exc}")

    st.markdown(
        """
        <div style="border-left:3px solid #8A6500;padding:8px 12px;margin:8px 0 12px 0;
                    background:transparent;">
          <p style="margin:0;font-size:0.85rem;color:#212121;">
            <strong style="color:#1B5E20;">&#128204; Real case from 2024:</strong>
            An African consultancy&rsquo;s final donor report was rejected three times
            for missing M&amp;E data and logframe gaps. 40+ hours of senior staff rework.
            Impact-Receipts catches these issues before they reach your donor.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "We store your account email and usage status to manage your free checks. "
        "Uploaded documents are processed (including by AI for Instant Report Check) "
        "but not stored. Anonymised text snippets are saved only if you opt in below."
    )
    st.markdown(
        '<p style="color:#8A6500;font-style:italic;font-size:14px;margin:4px 0 8px 0;">'
        "Anchored in USAID DQA, OECD-DAC, FCDO, and Bond Evidence Principles.</p>",
        unsafe_allow_html=True,
    )

    if st.button("Score My Result Statement →", type="primary", use_container_width=True, key="cta_bottom"):
        if not st.session_state.get("has_seen_tutorial"):
            st.session_state["tutorial_step"] = 1
        _go_to_screen(1, reset=True)

    st.markdown(
        """
        <div class="gtm-card">
          <p><strong>Want a deeper check?</strong></p>
          <p class="gtm-sub">I personally run free pilot verifications on 1&ndash;3 of your results
          before your next submission. Real teams have caught logframe gaps, evidence
          inconsistencies, and missing audit components &mdash; before donors flagged them.</p>
          <div class="gtm-btn-gold">
            <a href="https://wa.me/233503648195" target="_blank">Book a Free Pilot Check</a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="gold-info-box">
          &#128172; Questions before you start? Chat with us on WhatsApp:
          <a href="https://wa.me/233503648195">+233 50 364 8195</a>
        </div>
        <p style="color:#616161;font-style:italic;font-size:0.85rem;margin:8px 0 4px 0;">
          I&rsquo;m a MEL practitioner in Accra who got tired of submitting results without a confidence check &mdash; so I built this.
        </p>
        """,
        unsafe_allow_html=True,
    )

    _render_tagline_footer()


# ---------------------------------------------------------------------------
# Screen 1 — Submission Form
# ---------------------------------------------------------------------------

def render_screen_1():
    _cur_tab = st.session_state.get("current_tab", 0)
    render_pitch_strip(["enter", "logframe", "evidence", "review"][_cur_tab])

    if st.session_state.pop("_scroll_to_content", False):
        import streamlit.components.v1 as components
        components.html(
            """<script>
            (function() {
                var p = window.parent;
                try { p.scrollTo(0, 0); } catch(e) {}
                try { p.document.documentElement.scrollTop = 0; } catch(e) {}
                try { p.document.body.scrollTop = 0; } catch(e) {}
                try {
                    var m = p.document.querySelector('[data-testid="stMain"]');
                    if (m) m.scrollTop = 0;
                } catch(e) {}
            })();
            </script>""",
            height=1,
        )

    _render_tutorial(1)

    # Persistent save-draft affordance — sidebar Save Draft isn't visible on mobile/narrow screens
    _sav_c1, _sav_c2, _sav_c3 = st.columns([4, 1, 1])
    with _sav_c1:
        if st.session_state.get("_last_saved_time"):
            st.caption(f"💾 Draft saved at {st.session_state['_last_saved_time']} — reload-safe.")
        else:
            st.caption("💾 Save your draft so you can resume later, even if your internet cuts out.")
    with _sav_c2:
        if st.button("Save", key="top_save_draft_btn", help="Save draft to disk"):
            _save_draft()
    with _sav_c3:
        if st.button("← Home", key="top_home_btn", help="Back to landing page"):
            _go_to_screen(0)
            st.toast("Draft saved!", icon="💾")

    _has_prefill = any(
        _ss_str(k).strip()
        for k in ("result_statement", "target_group", "timeframe",
                   "geographic_scope", "evidence_description")
    )

    with st.expander("ℹ️ How this works — new here? Start here.", expanded=False):
        st.markdown(
            """
**Fill in 4 short sections about your result → click Run Check → get your scores.**

| Tab | What you'll enter |
|-----|-------------------|
| **1. Result Basics** | Your result statement, target group, timeframe, and geography |
| **2. Logframe Linkage** | Your logframe indicator, target, and what you achieved |
| **3. Evidence & Verification** | Your evidence type, source, and who verified the data |
| **4. Review & Submit** | Donor framework, then click **Score My Result Statement →** |

**What you get back:**
- **Confidence score (0–5)** — how credible and strong your evidence is
- **Clarity score (0–5)** — how well-defined your result statement is
- A **plain-English verdict** with the single most important fix to make first

Takes 5–10 minutes. Your draft saves automatically as you go.
            """
        )
    if st.session_state.pop("_payment_success", False):
        st.success("✅ Payment confirmed! Upload your document below to run the Instant Report Check — or fill in the form manually.")

    if _has_prefill:
        _pf_c1, _pf_c2 = st.columns([3, 1])
        with _pf_c1:
            st.info("📂 Continuing from a previous session — your form fields are pre-populated.")
        with _pf_c2:
            if st.button("Clear and start fresh", key="clear_prefill"):
                _reset_all_slots()
                st.rerun()

    active = st.session_state.get("active_slots", 1)

    # --- UX: DYNAMIC SIDEBAR (v3.2) ---
    with st.sidebar:
        st.markdown("### 📋 Submission Summary")
        st.caption("Updates as you fill in the form")
        _sb_s = _slot_suffix(1)

        def _sb_field(icon, label, key, trunc=None):
            val = str(st.session_state.get(key, "")).strip()
            if trunc and len(val) > trunc:
                val = val[:trunc] + "…"
            if val and val not in ("(No donor specified)", "(No sector selected)"):
                st.markdown(f"{icon} **{label}:** {val}")
            else:
                st.caption(f"{icon} {label}: —")

        _sb_field("🎯", "Result",      "result_statement",  80)
        _sb_field("👥", "Target Group", "target_group")
        _sb_field("📍", "Geography",   "geographic_scope")
        _sb_field("📅", "Timeframe",   "timeframe")
        _sb_field("🏢", "Donor",       "donor_selected")
        _sb_field("📊", "Indicator",   "logframe_indicator", 60)
        _t = st.session_state.get("logframe_target", "")
        _a = st.session_state.get("logframe_achievement", "")
        if _t or _a:
            _t_d = _t if _t else "—"; _a_d = _a if _a else "—"
            st.markdown(f"🎯 Target→Actual: **{_t_d} → {_a_d}**")
        else:
            st.caption("🎯 Target→Actual: —")
        _sb_field("📎", "Evidence Type", f"evidence_type{_sb_s}")
        _sb_field("✅", "Verifier", f"verifier{_sb_s}")

        st.markdown("---")
        try:
            _sb_sub = _build_submission_from_session(1)
            _sb_ev  = _evaluator.evaluate_submission(_sb_sub)
            _sb_c   = _sb_ev.get("raw_confidence_score", 0)
            _sb_cl  = _sb_ev.get("clarity_score", 0)
            def _sbe(v): return "🟢" if v >= 4.0 else "🟡" if v >= 3.0 else "🔴"
            st.markdown(f"**Confidence:** {_sbe(_sb_c)} {_sb_c}/5.0")
            st.markdown(f"**Clarity:** {_sbe(_sb_cl)} {_sb_cl}/5.0")
        except Exception:
            st.caption("Fill in the form to see live scores")

        st.markdown("---")
        if st.button("💾 Save Draft", key="sidebar_save_draft", use_container_width=True):
            _save_draft()
            st.toast("Draft saved!", icon="💾")
    # --- END UX: DYNAMIC SIDEBAR (v3.2) ---

    # Auto-save timer toast
    if "screen1_start_time" not in st.session_state:
        st.session_state["screen1_start_time"] = time.time()
    _elapsed = time.time() - st.session_state.get("screen1_start_time", time.time())
    if _elapsed > 300 and not st.session_state.get("save_reminded"):
        st.toast("⏰ You've been working for 5+ minutes. Download your draft from Tab 4 before continuing.", icon="💾")
        st.session_state["save_reminded"] = True

    _tab_cols = st.columns(4)
    for _ti, (_tc, _tn) in enumerate(zip(_tab_cols, _UX_TAB_NAMES)):
        with _tc:
            if st.button(
                f"● {_tn}" if _ti == _cur_tab else f"{_ti + 1}. {_tn}",
                key=f"_tab_nav_{_ti}",
                type="primary" if _ti == _cur_tab else "secondary",
                use_container_width=True,
            ):
                st.session_state["current_tab"] = _ti
                st.rerun()

    if _cur_tab == 0:
        render_commentary("enter")
        with st.expander("📋 Submission context — sector, donor, project", expanded=not _has_prefill):
            st.selectbox(
                "Sector (optional — helps tailor examples)",
                key="sector",
                options=SECTOR_OPTIONS,
                help="Select your sector to see sector-specific example placeholders in the evidence description field.",
            )
            _sector_val = st.session_state.get("sector", SECTOR_OPTIONS[0])
            if _sector_val == "Other":
                st.text_input(
                    "Specify your sector",
                    key="sector_other",
                    placeholder="e.g., Disaster Response, Gender Equality, Financial Inclusion",
                )
            st.selectbox(
                "Primary donor for this submission",
                key="donor_selected",
                options=["(No donor specified)", "USAID", "FCDO", "GIZ", "RVO", "World Bank", "AfDB", "EU / EuropeAid", "Other"],
                index=0,
                help="Select your primary donor to receive tailored reporting tips and donor-specific diagnostic guidance.",
            )
            st.selectbox(
                "Donor reporting framework for the crosswalk table",
                key="donor_framework",
                options=list(DONOR_PROFILES.keys()),
                format_func=lambda k: DONOR_PROFILES[k]["label"],
                index=0,
                help="Choose which audit framework's standards are shown alongside each sub-score in the donor framework crosswalk.",
            )
            st.text_input(
                "Project name (optional — used to group/compare indicators in Trends over time)",
                key="project_name",
                placeholder="e.g., Northern Region WASH Programme",
            )
            _donor_val = st.session_state.get("donor_selected", "(No donor specified)")
            if _donor_val == "Other":
                st.text_input(
                    "Specify donor name",
                    key="donor_other",
                    placeholder="e.g., DFID, KfW, Bill & Melinda Gates Foundation",
                )
            if _donor_val in DONOR_GUIDANCE:
                _dg = DONOR_GUIDANCE[_donor_val]
                with st.expander(f"💡 {_donor_val} reporting tips", expanded=True):
                    st.markdown(f"**Key emphasis:** {_dg['key_emphasis']}")
                    st.markdown(f"**Most common rejection:** {_dg['common_rejection']}")
                    st.markdown(f"**Tip:** {_dg['tip']}")
            st.session_state["remembered_sector"] = st.session_state.get("sector", "")
            st.session_state["remembered_donor"]  = st.session_state.get("donor_selected", "")
        # --- IRC fill summary banner (shown once after extraction) ---
        _irc_summary = st.session_state.pop("_irc_summary", None)
        if _irc_summary:
            st.success(
                f"⚡ Instant Check complete — {_irc_summary['filled']} fields auto-filled across all tabs. "
                "Use the tab buttons above to review each section before submitting."
            )
            if _irc_summary.get("skipped"):
                st.info(f"ℹ️ Left blank (not found in document): {_irc_summary['skipped']}")
            if _irc_summary.get("confidence_note"):
                st.info(f"ℹ️ {_irc_summary['confidence_note']}")
            if _irc_summary.get("compliance_gaps"):
                st.warning(f"⚠️ Compliance gaps not found: {_irc_summary['compliance_gaps']}")
        # --- END IRC fill summary banner ---

        with st.expander("📦 Submission Package Completeness Check (Recommended)", expanded=st.session_state.get("_irc_used", False)):
            st.caption(
                "Most donor rejections happen because something was missing from the submission package "
                "— not because the work was bad. Confirm what your donor expects."
            )
            st.selectbox(
                "What type of submission is this for?",
                options=[
                    "Select submission type...",
                    "Quarterly progress report",
                    "Annual progress report",
                    "Baseline report",
                    "Mid-term review",
                    "End-line evaluation",
                    "Final/closeout report",
                    "Project proposal",
                    "Financial report",
                    "MEL plan",
                    "Others (Special/Ad-hoc reports)",
                ],
                key="submission_type",
            )
            st.caption(
                "Options: Quarterly progress report · Annual report · Baseline/mid-term/end-line · "
                "Final/closeout report · Project proposal · Financial report · MEL plan · Ad-hoc report"
            )
            _sub_type = st.session_state.get("submission_type", "")
            _checklist_items = SUBMISSION_CHECKLIST.get(_sub_type, [])
            if _checklist_items:
                st.markdown(f"**Tick what your donor requires for a {_sub_type}:**")
                _chk_cols = [_checklist_items[i::2] for i in range(2)]
                _cl1, _cl2 = st.columns(2)
                for _col, _chunk in zip([_cl1, _cl2], _chk_cols):
                    with _col:
                        for _ckey, _clabel in _chunk:
                            st.checkbox(_clabel, key=_ckey)
                _n_ticked = sum(st.session_state.get(k, False) for k, _ in _checklist_items)
                _n_total  = len(_checklist_items)
                if _n_ticked == _n_total:
                    st.success(f"✅ All {_n_total} required items confirmed for {_sub_type}.")
                else:
                    st.info(f"{_n_ticked} of {_n_total} required item(s) confirmed.")
            elif _sub_type and _sub_type not in ("Choose an option...", "Select submission type...", ""):
                st.info("No standard checklist defined for this submission type.")
            else:
                st.caption("Select a submission type above to see the required items checklist.")
            st.caption(
                "**Common rejection cause:** Submitting a narrative report without the audit report "
                "(for final reports) or without the financial report (for quarterly reports). "
                "Always confirm the package list with your donor before submission."
            )

        col_h, col_add = st.columns([5, 1])
        with col_h:
            label = "Tell us about your result" if active == 1 else f"Tell us about your results ({active} added)"
            st.markdown(f"## {label}")
        with col_add:
            if active < 3:
                st.markdown("<div style='padding-top:22px'></div>", unsafe_allow_html=True)
                if st.button("＋ Add Another Result", use_container_width=True,
                             help="Add a second or third result to this submission (max 3)."):
                    st.session_state["active_slots"] = active + 1
                    st.rerun()

        # --- UX: INSTANT REPORT CHECK (v3.2) ---
        _entry_mode = st.session_state.get("entry_mode", "✍️ Fill in manually")
        st.markdown("**How would you like to fill in the form?**")
        _em_col1, _em_col2 = st.columns(2)
        with _em_col1:
            if st.button(
                "✍️ Fill in manually",
                use_container_width=True,
                type="primary" if _entry_mode == "✍️ Fill in manually" else "secondary",
                key="btn_fill_manual",
                help="Type your result details directly into each field.",
            ):
                st.session_state["entry_mode"] = "✍️ Fill in manually"
                st.rerun()
        with _em_col2:
            if st.button(
                "⚡ Instant Report Check",
                use_container_width=True,
                type="primary" if _entry_mode == "⚡ Instant Report Check" else "secondary",
                key="btn_irc",
                help="Upload your draft report — AI extracts and fills all fields automatically.",
            ):
                st.session_state["entry_mode"] = "⚡ Instant Report Check"
                st.rerun()
        if _entry_mode == "⚡ Instant Report Check":
            if not st.session_state.get("user_email"):
                st.markdown("#### 📧 Enter your email to unlock Instant Report Check")
                _render_email_gate_inline("_irc")
            with st.expander(
                "⚡ Instant Report Check — Upload your draft report to auto-fill this form",
                expanded=True,
            ):
                st.caption(
                    "Upload your donor report (PDF, DOCX, TXT, CSV, PPTX, or Excel), or a previously "
                    "downloaded Impact-Receipts draft (JSON) to pick up where you left off. "
                    "Responsible AI pre-fills fields across all tabs using only what's written in your document — "
                    "it never invents or assumes missing data. Always review before submitting."
                )
                _irc_paid_flag = (st.session_state.get("is_paid") or
                                  is_still_paid(get_user(st.session_state.get("user_email",""))))
                _irc_files = []
                if not _irc_paid_flag:
                    st.info("🔒 **Instant Report Check is a paid feature.** "
                            "Upgrade to auto-fill all form fields from your uploaded document.")
                    _render_paywall(irc_context=True)
                else:
                    _irc_files = st.file_uploader(
                        "Upload report file(s) (or a previously downloaded draft.json)",
                        type=["pdf", "docx", "txt", "csv", "pptx", "xlsx", "xls", "json"],
                        key="instant_report_upload",
                        accept_multiple_files=True,
                    )
                    # --- track and display when each file was added ---
                    _irc_upload_times = st.session_state.setdefault("_irc_upload_times", {})
                    for _f in _irc_files:
                        _fkey = f"{_f.name}_{_f.size}"
                        if _fkey not in _irc_upload_times:
                            _irc_upload_times[_fkey] = datetime.now().strftime("%H:%M:%S")
                    if _irc_files:
                        for _f in _irc_files:
                            _fkey = f"{_f.name}_{_f.size}"
                            st.caption(f"📄 {_f.name} — added {_irc_upload_times.get(_fkey, '')}")
                _irc_run_clicked = (_irc_paid_flag and st.button("🔍 Run Instant Check", key="run_instant_check")
                                     and bool(_irc_files))
                _irc_is_draft_json = (_irc_run_clicked and len(_irc_files) == 1
                                       and _irc_files[0].name.lower().endswith(".json"))

                if _irc_is_draft_json:
                    # --- v3.4: returning user re-upload of a previously downloaded draft ---
                    _irc_file = _irc_files[0]
                    try:
                        _irc_file.seek(0)
                        _draft_data = json.loads(_irc_file.read())
                        if not ("slots" in _draft_data or "active_slots" in _draft_data
                                or "result_statement" in _draft_data):
                            st.error("This JSON doesn't look like an Impact-Receipts draft. "
                                     "Please upload a file downloaded via 'Download Draft (JSON)' "
                                     "or 'Save Inputs (JSON)'.")
                        else:
                            _load_from_inputs_json(_draft_data)
                    except Exception as _draft_exc:
                        st.error(f"Could not read the draft file: {_draft_exc}")
                    # --- END v3.4 ---
                elif _irc_run_clicked:
                    _irc_should_rerun = False
                    with st.spinner("Reading your document(s) and pre-filling the form…"):
                        try:
                            # Step 1: extract and combine raw text from all uploaded documents
                            _doc_files = [f for f in _irc_files if not f.name.lower().endswith(".json")]
                            _full_text, _raw_fields, _ext_err = _irc_extract_combined(_doc_files)
                            if _ext_err:
                                st.warning(_ext_err)
                                st.stop()
                            else:
                                # Step 2: Claude API extraction
                                try:
                                    _irc_key = st.secrets.get("ANTHROPIC_API_KEY")
                                except Exception:
                                    _irc_key = None
                                _irc_key = _irc_key or os.environ.get("ANTHROPIC_API_KEY")
                                if not _irc_key:
                                    st.error("⚠️ ANTHROPIC_API_KEY not set. Rule-based extraction only.")
                                    # Fallback to rule-based
                                    _irc_filled = 0
                                    for _ef, _sf in _IRC_FIELD_MAP.items():
                                        _v = _raw_fields.get(_ef, "")
                                        if _v: st.session_state[_sf] = _v; _irc_filled += 1
                                    if _irc_filled:
                                        st.session_state["_irc_summary"] = {
                                            "filled": _irc_filled,
                                            "skipped": "",
                                            "confidence_note": "",
                                            "compliance_gaps": "",
                                        }
                                        st.session_state["_tab2_auto_advanced"] = True
                                        st.session_state["_irc_used"] = True
                                        st.session_state["_irc_fill_version"] = st.session_state.get("_irc_fill_version", 0) + 1
                                        _irc_should_rerun = True
                                else:
                                    _irc_client = _anthropic.Anthropic(api_key=_irc_key)
                                    # Build few-shot block
                                    _fewshot = {}
                                    _irc_sector = st.session_state.get("sector", "Other")
                                    for _ff in ["result_statement","target_group","timeframe",
                                                "geographic_scope","logframe_indicator",
                                                "logframe_target","logframe_achievement","evidence_description"]:
                                        _fex = get_examples(_ff, _irc_sector, k=3)
                                        if _fex: _fewshot[_ff] = _fex
                                    import json as _ijsonfs
                                    _fewshot_str = _ijsonfs.dumps(_fewshot, indent=2) if _fewshot else ""
                                    _irc_msgs = [{"role": "user", "content": [
                                        *([{"type":"text","text":f"Field examples for better extraction:\n{_fewshot_str}"}] if _fewshot_str else []),
                                        {"type":"text","text":f"Extract all fields from this report:\n\n{_full_text[:60000]}"}
                                    ]}]
                                    # Run the AI call in a background thread so we can
                                    # show a live elapsed-time indicator while it works.
                                    _irc_timer_ph = st.empty()
                                    _irc_api_result = {}

                                    def _irc_call_api():
                                        try:
                                            _irc_api_result["resp"] = _irc_client.messages.create(
                                                model="claude-haiku-4-5-20251001",
                                                max_tokens=3072,
                                                system=INSTANT_CHECK_SYSTEM_PROMPT,
                                                messages=_irc_msgs,
                                            )
                                        except Exception as _irc_api_exc:
                                            _irc_api_result["error"] = _irc_api_exc

                                    _irc_thread = threading.Thread(target=_irc_call_api, daemon=True)
                                    _irc_start_t = time.time()
                                    _irc_thread.start()
                                    while _irc_thread.is_alive():
                                        _irc_elapsed = time.time() - _irc_start_t
                                        _irc_timer_ph.info(f"🤖 Extracting fields with AI… {_irc_elapsed:.0f}s elapsed (usually 10-30s)")
                                        time.sleep(0.5)
                                    _irc_thread.join()
                                    _irc_timer_ph.empty()
                                    if "error" in _irc_api_result:
                                        raise _irc_api_result["error"]
                                    _irc_resp = _irc_api_result["resp"]
                                    import json as _ijson3
                                    _irc_raw = (_irc_resp.content[0].text if _irc_resp.content else "").strip()
                                    if _irc_raw.startswith("```"):
                                        _irc_parts = _irc_raw.split("```")
                                        if len(_irc_parts) >= 3:
                                            _irc_raw = _irc_parts[1].lstrip("json\n").strip()
                                    if not _irc_raw:
                                        raise ValueError("Model returned an empty response. Try a different document or fill the form manually.")
                                    _irc_data = _ijson3.loads(_irc_raw)
                                    _rb  = _irc_data.get("result_basics", {})
                                    _ll  = _irc_data.get("logframe_linkage", {})
                                    _ev3 = _irc_data.get("evidence_verification", {})
                                    _em  = _irc_data.get("extraction_metadata", {})
                                    _irc_filled = 0
                                    _skipped = []

                                    def _irc_to_str(val):
                                        """Coerce any extracted value to a plain string safe for text widgets."""
                                        if isinstance(val, list):
                                            return ", ".join(str(v) for v in val if v not in (None, "", "Not found"))
                                        if isinstance(val, dict):
                                            return ", ".join(f"{k}: {v}" for k, v in val.items())
                                        if val is None:
                                            return ""
                                        return str(val)

                                    def _irc_set(key, val):
                                        nonlocal _irc_filled
                                        try:
                                            sval = _irc_to_str(val)
                                            if sval and sval != "Not found":
                                                st.session_state[key] = sval; _irc_filled += 1
                                            else:
                                                _skipped.append(key)
                                        except Exception:
                                            _skipped.append(key)

                                    # --- Result Basics ---
                                    _irc_set("result_statement", _rb.get("result_statement"))
                                    _irc_set("target_group",     _rb.get("target_group"))
                                    _irc_set("timeframe",        _rb.get("timeframe"))
                                    _irc_set("geographic_scope", _rb.get("geographic_scope"))

                                    # --- Logframe Linkage ---
                                    _irc_set("logframe_indicator",   _ll.get("indicator_name"))
                                    _irc_set("logframe_target",      _ll.get("original_target"))
                                    _irc_set("logframe_achievement", _ll.get("actual_achievement"))

                                    # --- Evidence & Verification ---
                                    _irc_set("evidence_description", _ev3.get("evidence_narrative"))
                                    _vmt = None
                                    try:
                                        _vmt = _irc_match_option(_irc_to_str(_ev3.get("evidence_type","")), EVIDENCE_TYPES)
                                        if _vmt: st.session_state["evidence_type"] = _vmt; _irc_filled += 1
                                    except Exception:
                                        pass
                                    try:
                                        _irmt = _irc_match_option(_irc_to_str(_ev3.get("internal_review","")), INTERNAL_REVIEW_OPTIONS)
                                        if _irmt: st.session_state["internal_review"] = _irmt; _irc_filled += 1
                                    except Exception:
                                        pass
                                    try:
                                        _ermt = _irc_match_option(_irc_to_str(_ev3.get("external_review","")), EXTERNAL_REVIEW_OPTIONS)
                                        if _ermt: st.session_state["external_review"] = _ermt; _irc_filled += 1
                                    except Exception:
                                        pass
                                    for _dkk, _skk in [("reporting_period_start","reporting_start"),
                                                        ("reporting_period_end","reporting_end"),
                                                        ("evidence_collection_date","evidence_date")]:
                                        try:
                                            _pdd = _irc_parse_date(_irc_to_str(_ev3.get(_dkk,"")))
                                            if _pdd: st.session_state[_skk] = _pdd; _irc_filled += 1
                                        except Exception:
                                            pass
                                    _ver3 = _em.get("implementing_org") or _em.get("report_prepared_by","")
                                    _irc_set("verifier", _ver3)

                                    # --- Sector ---
                                    try:
                                        _sec_raw = _irc_to_str(_rb.get("sector",""))
                                        if _sec_raw and _sec_raw != "Not found":
                                            _sec_mt = _irc_match_option(_sec_raw, SECTOR_OPTIONS)
                                            if _sec_mt and _sec_mt != SECTOR_OPTIONS[0]:
                                                st.session_state["sector"] = _sec_mt; _irc_filled += 1
                                            else:
                                                st.session_state["sector"] = "Other"
                                                st.session_state["sector_other"] = _sec_raw
                                                _irc_filled += 1
                                    except Exception:
                                        pass

                                    # --- Primary donor ---
                                    try:
                                        _donor_raw = _irc_to_str(_rb.get("primary_donor",""))
                                        if _donor_raw and _donor_raw != "Not found":
                                            _don_mt = _irc_match_option(_donor_raw, ["USAID", "FCDO", "GIZ", "RVO", "World Bank", "AfDB", "EU / EuropeAid"])
                                            if _don_mt:
                                                st.session_state["donor_selected"] = _don_mt; _irc_filled += 1
                                            else:
                                                st.session_state["donor_selected"] = "Other"
                                                st.session_state["donor_other"] = _donor_raw
                                                _irc_filled += 1
                                    except Exception:
                                        pass

                                    # --- Submission type ---
                                    _matched_sub_type = None
                                    try:
                                        _sub_raw = _irc_to_str(_rb.get("submission_type",""))
                                        if _sub_raw and _sub_raw != "Not found":
                                            _matched_sub_type = _irc_match_option(_sub_raw, list(SUBMISSION_CHECKLIST.keys()))
                                            if _matched_sub_type:
                                                st.session_state["submission_type"] = _matched_sub_type; _irc_filled += 1
                                    except Exception:
                                        pass

                                    # --- Documents referenced -> tick required checklist items ---
                                    try:
                                        _docs_ref = _irc_data.get("documents_referenced", [])
                                        if _matched_sub_type and isinstance(_docs_ref, list) and _docs_ref:
                                            for _ckey, _clabel in SUBMISSION_CHECKLIST.get(_matched_sub_type, []):
                                                for _docref in _docs_ref:
                                                    _docref_str = _irc_to_str(_docref)
                                                    if _docref_str and _irc_match_option(_docref_str, [_clabel]):
                                                        st.session_state[_ckey] = True
                                                        _irc_filled += 1
                                                        break
                                    except Exception:
                                        pass

                                    # --- Compliance fields ---
                                    try:
                                        _con_raw = _irc_to_str(_ev3.get("consent_documented",""))
                                        if _con_raw and _con_raw != "Not found":
                                            _con_mt = _irc_match_option(_con_raw, list(CONSENT_CHECKLIST_MAP.keys()))
                                            if _con_mt: st.session_state["gov_consent_status"] = _con_mt; _irc_filled += 1
                                    except Exception:
                                        pass
                                    try:
                                        _anon_raw = _irc_to_str(_ev3.get("data_anonymised",""))
                                        if _anon_raw and _anon_raw != "Not found":
                                            _anon_mt = _irc_match_option(_anon_raw, list(ANON_CHECKLIST_MAP.keys()))
                                            if _anon_mt: st.session_state["gov_anonymization_status"] = _anon_mt; _irc_filled += 1
                                    except Exception:
                                        pass
                                    try:
                                        _law_raw = _irc_to_str(_ev3.get("data_protection_compliant",""))
                                        if _law_raw and _law_raw != "Not found":
                                            _law_mt = _irc_match_option(_law_raw, list(LAW_CHECKLIST_MAP.keys()))
                                            if _law_mt: st.session_state["gov_compliance_law_status"] = _law_mt; _irc_filled += 1
                                    except Exception:
                                        pass

                                    # --- Funder Readiness inputs (v3.5) ---
                                    _fri = _irc_data.get("funder_readiness_inputs", {})
                                    _irc_set("learning_notes",     _fri.get("learning_and_adaptation"))
                                    _irc_set("limitations_notes",  _fri.get("limitations"))
                                    _irc_set("additional_context", _fri.get("result_owner_and_decision"))
                                    try:
                                        _attr_raw = _irc_to_str(_fri.get("attribution_vs_contribution",""))
                                        if _attr_raw and _attr_raw != "Not found":
                                            _attr_mt = _irc_match_option(_attr_raw, ["Yes","No","Not sure"])
                                            if _attr_mt: st.session_state["attribution_contribution"] = _attr_mt; _irc_filled += 1
                                    except Exception:
                                        pass
                                    try:
                                        _disagg_raw = _irc_to_str(_fri.get("disaggregation_status",""))
                                        if _disagg_raw and _disagg_raw != "Not found":
                                            _disagg_mt = _irc_match_option(_disagg_raw, ["Yes — fully disaggregated","Partially disaggregated","No"])
                                            if _disagg_mt: st.session_state["disaggregation_status"] = _disagg_mt; _irc_filled += 1
                                    except Exception:
                                        pass

                                    # --- Beneficiary voice ---
                                    try:
                                        _bv_raw = _irc_to_str(_rb.get("beneficiary_voice",""))
                                        if _bv_raw and _bv_raw != "Not found":
                                            _bv_mt = _irc_match_option(_bv_raw, _BV_OPTIONS)
                                            if _bv_mt and _bv_mt != _BV_OPTIONS[0]:
                                                st.session_state["beneficiary_voice"] = _bv_mt; _irc_filled += 1
                                    except Exception:
                                        pass

                                    # --- Strengthen this evidence -> tick verifiable checks ---
                                    try:
                                        _esc = _irc_data.get("evidence_strengthening_checks", [])
                                        if _vmt and isinstance(_esc, list) and _esc:
                                            for _ekey, _elabel in EVIDENCE_STRENGTHEN_CHECKLIST.get(_vmt, []):
                                                for _eitem in _esc:
                                                    _eitem_str = _irc_to_str(_eitem)
                                                    if _eitem_str and _irc_match_option(_eitem_str, [_elabel]):
                                                        st.session_state[_ekey] = True
                                                        _irc_filled += 1
                                                        break
                                    except Exception:
                                        pass

                                    # store summary for persistent banner; disable auto-advance
                                    _skip_str3 = ", ".join(_skipped[:6]) if _skipped else ""
                                    _conf3 = _irc_to_str(_em.get("confidence_note",""))
                                    _cgaps = [f for f in ["consent_documented","data_anonymised","data_protection_compliant"] if _ev3.get(f,"") == "Not found"]
                                    _glab = {"consent_documented":"Consent","data_anonymised":"Anonymisation","data_protection_compliant":"Data protection"}
                                    st.session_state["_irc_summary"] = {
                                        "filled": _irc_filled,
                                        "skipped": _skip_str3,
                                        "confidence_note": _conf3 if _conf3 and _conf3 != "Not found" else "",
                                        "compliance_gaps": ", ".join(_glab.get(g,g) for g in _cgaps),
                                    }
                                    # prevent auto-advance from swallowing logframe/evidence tabs
                                    st.session_state["_tab2_auto_advanced"] = True
                                    st.session_state["_irc_used"] = True
                                    st.session_state["_irc_fill_version"] = st.session_state.get("_irc_fill_version", 0) + 1
                                    _irc_should_rerun = True
                        except Exception as _irc_exc:
                            st.error(f"Extraction failed: {_irc_exc}. Please fill the form manually.")
                    if _irc_should_rerun:
                        st.rerun()
        # --- END UX: INSTANT REPORT CHECK (v3.2) ---

        for slot in range(1, active + 1):
            if active > 1:
                st.markdown(f"---\n#### Result {slot}")
            _render_tab1_slot(slot)

        # --- v3.3: auto-advance to Logframe tab when tab1 complete ---
        _t1_done = all([
            _ss_str("result_statement").strip(),
            _ss_str("target_group").strip(),
            _ss_str("timeframe").strip(),
            _ss_str("geographic_scope").strip(),
        ])
        if _t1_done:
            if st.button("Next: Logframe Linkage →", key="tab1_next_btn", type="primary"):
                st.session_state["current_tab"] = 1
                st.session_state["_tab2_auto_advanced"] = False
                st.session_state["_scroll_to_content"] = True
                st.rerun()
        else:
            st.caption("Fill in all four fields above to continue.")
        # --- END v3.3 ---

    elif _cur_tab == 1:
        render_commentary("logframe")
        for slot in range(1, active + 1):
            if active > 1:
                st.markdown(f"---\n#### Result {slot}")
            _render_tab2_slot(slot)

        # --- v3.3: next button / auto-advance to Evidence tab when logframe complete ---
        _t2_done = all([
            _ss_str("logframe_indicator").strip(),
            _ss_str("logframe_target").strip(),
            _ss_str("logframe_achievement").strip(),
        ])
        # IRC users may have logframe fields legitimately left blank (not in the
        # source document) — don't block navigation for them; manual fill-in
        # still requires all three fields before proceeding.
        _t2_can_advance = _t2_done or st.session_state.get("_irc_used", False)
        if _t2_can_advance:
            if st.button("Next: Evidence & Verification →", key="tab2_next_btn", type="primary"):
                st.session_state["current_tab"] = 2
                st.session_state["_tab2_auto_advanced"] = True
                st.session_state["_scroll_to_content"] = True
                st.rerun()
            if not _t2_done:
                st.caption("Some logframe fields weren't found in your uploaded report — you can fill them in now or continue and complete them later.")
        else:
            st.caption("Fill in all three logframe fields above to continue.")
        # --- END v3.3 ---

    elif _cur_tab == 2:
        render_commentary("evidence")
        for slot in range(1, active + 1):
            if active > 1:
                st.markdown(f"---\n#### Result {slot}")
            _render_tab3_slot(slot)

        # --- v3.3: next button to Review & Submit ---
        if st.button("Next: Review & Submit →", key="tab3_next_btn", type="primary"):
            st.session_state["current_tab"] = 3
            st.session_state["_scroll_to_content"] = True
            st.rerun()
        # --- END v3.3 ---

    elif _cur_tab == 3:
        render_commentary("review")
        st.caption("Review your scores, download your draft, and submit when ready.")

        _REQUIRED_FIELDS_B = [
            ("result_statement",     "Result statement (Tab 1)"),
            ("target_group",         "Target group (Tab 1)"),
            ("timeframe",            "Timeframe (Tab 1)"),
            ("geographic_scope",     "Geographic scope (Tab 1)"),
            ("evidence_description", "Evidence description (Tab 3)"),
            ("evidence_type",        "Evidence type (Tab 3)"),
        ]
        _TAB_IDX_B = {
            "result_statement": 0, "target_group": 0, "timeframe": 0, "geographic_scope": 0,
            "evidence_description": 2, "evidence_type": 2,
        }
        _missing_b = [
            (key, lbl) for key, lbl in _REQUIRED_FIELDS_B
            if not str(st.session_state.get(key, "")).strip()
            or st.session_state.get(key, "") in (EVIDENCE_TYPES[0], "Choose an option...", "")
        ]
        _completed_b = len(_REQUIRED_FIELDS_B) - len(_missing_b)
        st.progress(_completed_b / len(_REQUIRED_FIELDS_B),
                    text=f"Form completion: {_completed_b}/{len(_REQUIRED_FIELDS_B)} required fields")
        if _missing_b:
            with st.expander(f"⚠ {len(_missing_b)} required field(s) incomplete", expanded=True):
                for _fk, _fl in _missing_b:
                    st.markdown(f"- {_fl}")
                if st.button("→ Fix: Jump to First Missing Field", key="jump_missing_b", type="primary"):
                    _first_b = _TAB_IDX_B[_missing_b[0][0]]
                    st.session_state["current_tab"] = _first_b
                    st.rerun()

        # --- UX: ACTIONABLE SCORE PREVIEW (v3.2) ---
        try:
            _banner_sub = _build_submission_from_session(1)
            _banner_ev  = _evaluator.evaluate_submission(_banner_sub)
            _banner_c   = round(_banner_ev.get("raw_confidence_score", 0) * 20, 1)
            _banner_cl  = round(_banner_ev.get("clarity_score", 0) * 20, 1)
            if _banner_c >= 75 and _banner_cl >= 75:
                st.success("✅ Strong Submission — Your result meets quality thresholds for donor submission.")
            elif _banner_c >= 50 or _banner_cl >= 50:
                st.warning("⚠️ Submission Needs Work — Address the items below before submitting.")
            else:
                st.error("🔴 High Risk — This result is likely to be queried or rejected. Fix critical issues first.")
        except Exception:
            pass
        # --- END UX: ACTIONABLE SCORE PREVIEW (v3.2) ---

        with st.expander("ℹ️ How scoring works"):
            st.markdown("""
**Confidence Score (0–5.0)** — measures how credible and traceable your evidence is.
- **Directness** (0–2.0): target 1.5+ — how directly the evidence links to the result
- **Verification** (0–2.0): target 1.5+ — how rigorously evidence was reviewed
- **Recency** (0–1.0): target 0.7+ — how recently the evidence was collected

**Clarity Score (0–5.0)** — measures how precisely the result is defined and measurable.
- **Definition** (0–1.25): target 1.0+ — who, what, where, by when
- **Measurement** (0–1.25): target 1.0+ — indicator, baseline, target stated
- **Integrity** (0–1.0): completeness and audit trail
- **Scope** (0–0.75): geographic and demographic coverage
- **Governance** (0–0.75): named owner and decision use

A **content quality penalty** (×0.5 to ×1.0) applies when the result statement or evidence description appears to be placeholder text.
""")

        with st.expander("📊 Live Score Preview", expanded=True):
            _render_live_score_preview(1)

        st.divider()

        # Consent checkbox for example library
        st.checkbox(
            "📚 Allow my anonymised entries to improve extraction quality for other MEL officers. "
            "(Act 843 / NDPA compliant — no names or organisations are stored.)",
            key="consent_examples",
        )
        # --- Usage tracking ---
        _email_now = st.session_state.get("user_email", "")
        _u_now = get_user(_email_now) if _email_now else None
        _checks_now = (_u_now or {}).get("free_checks_used", 0)
        _paid_now = st.session_state.get("is_paid") or is_still_paid(_u_now)
        _check_allowed = _paid_now or _checks_now < FREE_CHECKS_LIMIT
        if not _check_allowed:
            _render_paywall()
        # --- End usage tracking ---
        if _check_allowed and st.button("Score My Result Statement →", type="primary", use_container_width=True):
            mandatory = [
                st.session_state.get("result_statement", ""),
                st.session_state.get("target_group", ""),
                st.session_state.get("timeframe", ""),
                st.session_state.get("geographic_scope", ""),
                st.session_state.get("evidence_description", ""),
            ]
            ev_type = st.session_state.get("evidence_type", "")
            ev_other = _ss_str("evidence_type_other").strip()
            if ev_type == "Other" and not ev_other:
                st.warning("Please specify your evidence type in Tab 3 — Evidence & Verification.")
            elif not all(mandatory) or _missing_b:
                _missing_labels = ", ".join(lbl for _, lbl in _missing_b) or "required fields"
                st.warning(f"Please complete the following before running the check: {_missing_labels}.")
            else:
                if not st.session_state.get("has_seen_tutorial"):
                    st.session_state["tutorial_step"] = 2
                for slot in range(1, active + 1):
                    s = _slot_suffix(slot)
                    raw = st.session_state.get(f"uploaded_files_widget{s}") or []
                    st.session_state[f"uploaded_files{s}"] = [f.name for f in raw]
                st.session_state["active_slots_run"] = active
                st.session_state["evaluations"]       = None
                st.session_state["submissions_snapshot"] = None
                # --- Save anonymised examples on consent ---
                if st.session_state.get("consent_examples") and _email_now:
                    _ex_sector = st.session_state.get("sector", "Other")
                    for _ex_field in ["result_statement", "target_group", "timeframe",
                                      "geographic_scope", "logframe_indicator",
                                      "logframe_target", "logframe_achievement",
                                      "evidence_description"]:
                        _ex_val = st.session_state.get(_ex_field, "")
                        _ex_clean = _anonymize_value(_ex_val)
                        if _ex_clean:
                            save_example(_ex_field, _ex_sector, _ex_clean)
                # --- Track usage ---
                if not _paid_now and _email_now:
                    increment_checks(_email_now)
                # --- End tracking ---
                st.session_state["screen"] = 2
                st.rerun()

        _save_draft()
        st.caption(f"💾 Auto-saved across all tabs · Last saved {st.session_state.get('_last_saved_time', '--:--')}")
        if os.path.exists(_DRAFT_PATH):
            try:
                with open(_DRAFT_PATH, encoding="utf-8") as _df:
                    _draft_bytes = _df.read().encode("utf-8")
                st.download_button(
                    "📥 Download Draft (JSON)",
                    data=_draft_bytes,
                    file_name="impact_receipts_draft.json",
                    mime="application/json",
                    use_container_width=True,
                    help="Download your draft to restore later via 'Resume Previous Session' on the landing page.",
                )
            except Exception:
                pass

        st.divider()

        if st.session_state.get("confirm_reset"):
            st.warning("Clear all inputs and start over?")
            cf1, cf2 = st.columns(2)
            with cf1:
                if st.button("Yes, clear everything", type="primary", use_container_width=True):
                    st.session_state["confirm_reset"] = False
                    _clear_draft()
                    _go_to_screen(1, reset=True)
            with cf2:
                if st.button("Cancel", use_container_width=True):
                    st.session_state["confirm_reset"] = False
                    st.rerun()
        else:
            if st.button("Start Fresh", use_container_width=False):
                st.session_state["confirm_reset"] = True
                st.rerun()

        if st.button("← Back to Home", use_container_width=False):
            _go_to_screen(0)

    _save_draft()
    _render_tagline_footer()


# ---------------------------------------------------------------------------
# Screen 2 — Confidence Snapshot & Next Steps
# ---------------------------------------------------------------------------

def render_how_scoring_works_panel() -> None:
    """Render a reference panel explaining all eight scoring criteria."""
    with st.expander("ℹ️ How scoring works", expanded=False):
        st.caption(
            "Confidence and Clarity are each built from rule-based sub-criteria. "
            "No AI scoring is used — every score below follows a fixed rubric."
        )
        for axis, axis_title in (("confidence", "Confidence"), ("clarity", "Clarity")):
            st.markdown(f"**{axis_title} criteria**")
            for key, guide in _SCORING_GUIDE.items():
                if guide["axis"] != axis:
                    continue
                label = guide["label"]
                definition = guide["definition"]
                weak = guide["weak_example"]
                strong = guide["strong_example"]
                improve = guide["improve_actions"]
                if key in ("measurement", "definition"):
                    st.markdown(f"**{label} / {guide['qualitative_label']}** (max {guide['max_score']})")
                    st.markdown(f"{definition}")
                    st.caption(guide["qualitative_definition"])
                else:
                    st.markdown(f"**{label}** (max {guide['max_score']})")
                    st.markdown(definition)
                st.caption(f"Why it matters: {guide['why_it_matters']}")
                col_weak, col_strong = st.columns(2)
                with col_weak:
                    st.markdown("*Weak example*")
                    st.caption(weak)
                with col_strong:
                    st.markdown("*Strong example*")
                    st.caption(strong)
                st.markdown("How to improve:")
                for action in improve:
                    st.markdown(f"- {action}")
                if key in ("measurement", "definition"):
                    st.markdown(f"How to improve ({guide['qualitative_label']} — for case studies, "
                                 f"outcome harvesting, beneficiary narratives):")
                    for action in guide["qualitative_improve_actions"]:
                        st.markdown(f"- {action}")
                st.markdown("---")


def render_personalized_weakness_panel(
    direct_score: float, verify_score: float, recency_score: float,
    definition_score: float, measurement_score: float,
    integrity_score: float, scope_score: float, governance_score: float,
    is_qualitative: bool = False,
    n: int = 3,
) -> None:
    """Show the n weakest scoring criteria for this submission with improvement actions."""
    scores = {
        "directness": direct_score,
        "verification": verify_score,
        "recency": recency_score,
        "definition": definition_score,
        "measurement": measurement_score,
        "integrity": integrity_score,
        "scope": scope_score,
        "governance": governance_score,
    }
    axis_order = {"confidence": 0, "clarity": 1}
    ranked = sorted(
        scores.items(),
        key=lambda item: (
            item[1] / _SCORING_GUIDE[item[0]]["max_score"],
            axis_order[_SCORING_GUIDE[item[0]]["axis"]],
        ),
    )
    st.markdown("#### Where to focus first")
    for key, score in ranked[:n]:
        guide = _SCORING_GUIDE[key]
        max_score = guide["max_score"]
        if key in ("measurement", "definition") and is_qualitative:
            label = guide["qualitative_label"]
            improve = guide["qualitative_improve_actions"]
        else:
            label = guide["label"]
            improve = guide["improve_actions"]
        st.warning(f"**{label}** is one of your weakest areas ({score}/{max_score})")
        for action in improve:
            st.markdown(f"- {action}")


def _build_reviewer_info(slot: int) -> dict:
    """Read the current review-handoff fields for one submission slot from
    session state. Read live (not from the evaluation snapshot) so exports
    reflect reviewer input entered after the snapshot was taken."""
    s = _slot_suffix(slot)
    return {
        "review_status":     st.session_state.get(f"review_status{s}", _SUBMISSION_STATUS_OPTIONS[0]),
        "reviewer_name":     st.session_state.get(f"reviewer_name{s}", ""),
        "reviewer_role":     st.session_state.get(f"reviewer_role{s}", ""),
        "reviewer_date":     st.session_state.get(f"reviewer_date{s}", ""),
        "reviewer_decision": st.session_state.get(f"reviewer_decision{s}", ""),
        "reviewer_notes":    st.session_state.get(f"reviewer_notes{s}", ""),
    }


def _render_review_handoff(submission: dict, ev: dict, card_idx: int):
    """Lightweight review-handoff layer (v3.6): per-submission status,
    reviewer name/role/date/decision/notes, and an exportable review summary
    that reuses the existing HTML/PDF/DOCX report builders.

    Known limitation: no user accounts, authentication, or real-time
    multi-user support — reviewer identity is free text within this session,
    consistent with the rest of the app."""
    slot = card_idx + 1
    s = _slot_suffix(slot)

    with st.expander("📝 Review & sign-off", expanded=False):
        st.caption(
            "Optional — record a reviewer's decision before handing this result back "
            "to the field officer or passing it up the chain. No accounts or logins: "
            "these fields live only in this browser session unless you click "
            "**Save Draft** below, which writes them (with the rest of this submission) "
            "to inputs/draft.json so they survive a reload."
        )
        rc1, rc2 = st.columns(2)
        with rc1:
            st.selectbox("Status", _SUBMISSION_STATUS_OPTIONS, key=f"review_status{s}")
            st.text_input("Reviewer name", key=f"reviewer_name{s}")
            st.text_input("Reviewer role", key=f"reviewer_role{s}")
        with rc2:
            st.selectbox(
                "Decision", _REVIEW_DECISION_OPTIONS, key=f"reviewer_decision{s}",
                format_func=lambda d: d or "Select decision...",
            )
            st.text_input("Review date", key=f"reviewer_date{s}", placeholder="YYYY-MM-DD")
        st.text_area(
            "Reviewer notes (overall or per criterion)",
            key=f"reviewer_notes{s}", height=100,
        )

        if st.button("💾 Save Draft (incl. review notes)", key=f"review_save_draft_{card_idx}"):
            _save_draft()
            st.toast("Draft saved, including review notes!", icon="💾")

        review_info = _build_reviewer_info(slot)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_html = _build_review_summary_html(submission, ev, review_info, timestamp, chart_id=str(card_idx))

        dl1, dl2, dl3 = st.columns(3)
        with dl1:
            st.download_button(
                "⬇️ Review Summary (HTML)",
                data=summary_html,
                file_name=f"review_summary_{slot}_{timestamp}.html",
                mime="text/html",
                key=f"review_summary_html_btn_{card_idx}",
            )
        with dl2:
            summary_pdf = _html_to_pdf_bytes(summary_html)
            if summary_pdf:
                st.download_button(
                    "📄 Review Summary (PDF)",
                    data=summary_pdf,
                    file_name=f"review_summary_{slot}_{timestamp}.pdf",
                    mime="application/pdf",
                    key=f"review_summary_pdf_btn_{card_idx}",
                )
            else:
                st.caption("PDF: install xhtml2pdf to enable PDF export.")
        with dl3:
            if _HAS_DOCX:
                st.download_button(
                    "📄 Review Summary (DOCX)",
                    data=_build_review_summary_docx(submission, ev, review_info, timestamp),
                    file_name=f"review_summary_{slot}_{timestamp}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"review_summary_docx_btn_{card_idx}",
                )
            else:
                st.caption("DOCX: install python-docx to enable DOCX export.")


_PLAIN_ENGLISH_VERDICT = {
    "STRONG":             "This result is well-positioned for submission. The fixes below are refinements, not blockers.",
    "MISLEADING":         "Your evidence is solid, but the result definition needs sharpening before a donor will accept it.",
    "UNDEREVIDENCED":     "The result is clearly defined, but the evidence won't survive a donor's scrutiny yet.",
    "NEEDS REFINEMENT":   "This result is on track — address the top fix below and it will be submission-ready.",
    "FUNDAMENTALLY WEAK": "Both the definition and the evidence need rework. Start with the Confidence fixes below.",
}


def _render_result_card(submission: dict, ev: dict, card_idx: int = 0, donor: str = ""):
    conf_score   = ev.get("confidence_score", 0)
    clar_score   = ev.get("clarity_score", 0)
    conf_label   = ev.get("confidence_label", "High Risk")
    clar_label   = ev.get("clarity_label",   "High Risk")
    conf_meaning = ev.get("confidence_meaning", "")
    clar_meaning = ev.get("clarity_meaning",    "")
    verdict      = ev.get("verdict", "")
    conf_comp    = ev.get("confidence_components", {})
    clar_comp    = ev.get("clarity_components", {})
    fixes        = ev.get("fixes", [])

    snippet = submission.get("result_statement", "")
    if len(snippet) > 120:
        snippet = snippet[:120] + "..."
    st.markdown(f"**{snippet}**")
    st.divider()

    # Diagnostic state badge
    content_issues    = ev.get("content_issues", [])
    bv_voice_field    = submission.get("beneficiary_voice", "")
    diag_state, diag_sub = get_diagnostic_state(conf_score, clar_score, content_issues, bv_voice_field)

    # Headline: is this good enough to submit?
    if diag_state != "INVALID INPUT":
        _render_readiness_banner(diag_state)

    diag_cfg = _DIAGNOSTIC_BADGE.get(diag_state, {"bg": "#9E9E9E", "text": "#FFFFFF", "subtitle": ""})
    _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"
    st.markdown(
        f"<div class='diagnostic-badge' style='background:{diag_cfg['bg']};color:{diag_cfg['text']};{_pca}'>"
        f"{diag_state} &nbsp;·&nbsp; {diag_sub}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Plain-English "what this means" — shown before the score wall
    render_commentary("report")
    render_scoreboard(
        confidence=round(conf_score * 20),
        clarity=round(clar_score * 20),
        verified=True,
    )
    _pev = _PLAIN_ENGLISH_VERDICT.get(diag_state, "")
    if _pev:
        st.info(_pev)

    # Single biggest-impact fix surfaced up-front (all non-STRONG states)
    if fixes and diag_state not in ("STRONG", "INVALID INPUT"):
        _top = fixes[0]
        _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"
        st.markdown(
            f"<div style='background:#FFF9C4;border-left:4px solid #F57F17;border-radius:6px;"
            f"padding:10px 14px;margin:8px 0;font-size:0.9rem;{_pca}'>"
            f"🎯 <strong>Biggest single fix:</strong> {_top['message']} "
            f"<em>({_top['score_impact']})</em></div>",
            unsafe_allow_html=True,
        )

    # INVALID INPUT early exit
    if diag_state == "INVALID INPUT":
        st.error("Input Quality Issue Detected")
        st.markdown(
            "Your responses appear to be placeholder text. Impact-Receipts scores **real** "
            "reported results. Please return to Screen 1 and provide genuine content."
        )
        for issue in content_issues:
            st.markdown(f"- {issue}")
        raw_conf = ev.get("raw_confidence_score")
        mult = ev.get("content_quality_multiplier", 1.0)
        if raw_conf is not None:
            st.caption(
                f"Raw score before quality adjustment: {raw_conf}/5.0 — multiplier applied: ×{mult}"
            )
        if st.button("← Edit Submission", key=f"invalid_back_{card_idx}"):
            st.session_state["screen"] = 1
            st.session_state["evaluations"] = None
            st.rerun()
        st.divider()
        return

    # --- Four Funder Questions summary (top of report) ---
    ev_top      = (submission.get("evidence") or [{}])[0]
    ev_type_top = ev_top.get("type", "") or "Not specified"
    ladder_top  = ev.get("evidence_ladder", {})
    fr_top      = ev.get("funder_readiness", {})
    direct_level = conf_comp.get("direct_level", 0)
    verify_level = conf_comp.get("verify_level", 0)
    def_score    = clar_comp.get("definition_score", 0)

    st.markdown("### What Funders Want to Know")
    fq_col1, fq_col2 = st.columns(2)
    with fq_col1:
        st.markdown("**1. What has changed?**")
        st.markdown(snippet if snippet else "_Not yet described._")
        st.caption(f"Directness: Level {direct_level}/5 · Definition: {def_score}/1.25")

        st.markdown("**3. How strong is the evidence?**")
        st.markdown(f"Confidence: **{conf_score}/5.0** ({conf_label})")
        st.caption(_VERIFICATION_TIPS.get(verify_level, ""))

    with fq_col2:
        st.markdown("**2. How do you know?**")
        dominant = ladder_top.get("dominant_tier")
        if dominant:
            st.markdown(f"Evidence type: **{ev_type_top}** — evidence base is mainly **{dominant}**-tier.")
        else:
            st.markdown(f"Evidence type: **{ev_type_top}**")
        st.caption(_DIRECTNESS_TIPS.get(direct_level, ""))

        st.markdown("**4. What did you learn?**")
        learn = fr_top.get("learning", {})
        if learn.get("detected"):
            st.markdown("Yes — the report describes what was learned and how the program adapted.")
        else:
            st.markdown("_Not yet stated._ Add a sentence on what you learned and changed as a result.")

    st.divider()

    # Logframe linkage panel (guarded for backward-compat with stale evaluator deploys)
    linkage = ev.get("logframe_linkage", {})
    if linkage:
        lk_state = linkage.get("state", "MISSING")
        lk_rat   = linkage.get("rationale", "")
        lk_issues = linkage.get("issues", [])
        st.markdown("#### Logframe Linkage")
        if lk_state == "STRONG":
            st.success(f"✓ {lk_rat}")
        elif lk_state == "WEAK":
            st.warning(f"⚠️ {lk_rat}")
            for iss in lk_issues:
                st.markdown(f"- {iss}")
        else:
            st.error(f"❌ {lk_rat}")
            st.markdown(
                "**Highest-impact missing piece:** Donors will reject results that cannot "
                "be traced to an approved indicator from your Technical Proposal."
            )
            for iss in lk_issues:
                st.markdown(f"- {iss}")

    # Reporting period validation on Screen 2
    rp_start_str = submission.get("reporting_start", "")
    rp_end_str   = submission.get("reporting_end", "")
    ev_date_str  = (submission.get("evidence") or [{}])[0].get("recency", "")
    if rp_start_str and rp_end_str and ev_date_str and hasattr(_evaluator, "validate_reporting_period"):
        try:
            from datetime import date as _d
            _rp_s2 = _d.fromisoformat(rp_start_str)
            _rp_e2 = _d.fromisoformat(rp_end_str)
            _ev2   = _d.fromisoformat(ev_date_str)
            _, _rp2_msg, _rp2_sev = _evaluator.validate_reporting_period(_ev2, _rp_s2, _rp_e2)
            if _rp2_sev == "WARNING":
                st.warning(f"📅 Reporting Period Issue: {_rp2_msg}")
                st.caption("This is a common cause of donor flags. Address before submission.")
            elif _rp2_sev == "ERROR":
                st.error(f"📅 Reporting Period Error: {_rp2_msg}")
        except (ValueError, TypeError, AttributeError):
            pass

    # Dual-axis columns
    col_conf, col_clar = st.columns(2)

    with col_conf:
        st.markdown("#### Confidence Score")
        st.markdown(_axis_badge_html(conf_label, conf_score, 5.0), unsafe_allow_html=True)
        st.caption(conf_meaning)
        dl = conf_comp.get("direct_level", 0)
        vl = conf_comp.get("verify_level", 0)
        rl = conf_comp.get("recency_level", 0)
        ds = conf_comp.get("direct_score", 0)
        vs = conf_comp.get("verify_score", 0)
        rs = conf_comp.get("recency_score", 0)
        _dir_rationale = conf_comp.get("direct_rationale") or _evaluator.get_score_rationale("directness", dl, ds, 2.0)
        _verify_rationale = conf_comp.get("verify_rationale") or _evaluator.get_score_rationale("verification", vl, vs, 2.0)
        st.metric("Directness", f"{ds}/2.0", help=_dir_rationale)
        st.metric("Verification", f"{vs}/2.0", help=_verify_rationale)
        st.metric("Recency", f"{rs}/1.0",
                  help=_evaluator.get_score_rationale("recency", rl, rs, 1.0))
        bv_bonus = conf_comp.get("bv_bonus", 0.0)
        st.metric("Beneficiary Voice Bonus", f"+{bv_bonus}/0.5",
                  help=BENEFICIARY_VOICE_TOOLTIP)
        _render_subscore_chart([
            ("Directness", ds, 2.0, _dir_rationale),
            ("Verification", vs, 2.0, _verify_rationale),
            ("Recency", rs, 1.0, _evaluator.get_score_rationale("recency", rl, rs, 1.0)),
        ], key=f"snapshot_conf_chart_{card_idx}")

    with col_clar:
        st.markdown("#### Clarity Score")
        st.markdown(_axis_badge_html(clar_label, clar_score, 5.0), unsafe_allow_html=True)
        st.caption(clar_meaning)
        def_s  = clar_comp.get("definition_score",  0)
        meas_s = clar_comp.get("measurement_score", 0)
        integ  = clar_comp.get("integrity_score",   0)
        scope  = clar_comp.get("scope_score",       0)
        gov    = clar_comp.get("governance_score",  0)
        is_qual    = clar_comp.get("is_qualitative", False)
        def_label  = "Narrative Definition" if is_qual else "Definition"
        def_tip    = _CLARITY_TIPS["definition_qualitative"] if is_qual else _CLARITY_TIPS["definition"]
        meas_label = "Sourcing & Triangulation" if is_qual else "Measurement"
        meas_tip   = _CLARITY_TIPS["measurement_qualitative"] if is_qual else _CLARITY_TIPS["measurement"]
        st.metric(def_label, f"{def_s}/1.25",
                  help=f"{def_tip}\n\n{TOOLTIP_DEFINITION}")
        st.metric(meas_label, f"{meas_s}/1.25",
                  help=f"{meas_tip}\n\n{TOOLTIP_MEASUREMENT}")
        st.metric("Integrity", f"{integ}/1.0",
                  help=f"{_CLARITY_TIPS['integrity']}\n\n{TOOLTIP_INTEGRITY}")
        st.metric("Scope", f"{scope}/0.75",
                  help=f"{_CLARITY_TIPS['scope']}\n\n{TOOLTIP_SCOPE}")
        st.metric("Governance", f"{gov}/0.75",
                  help=f"{_CLARITY_TIPS['governance']}\n\n{TOOLTIP_GOVERNANCE}")
        _render_subscore_chart([
            (def_label, def_s, 1.25, def_tip),
            (meas_label, meas_s, 1.25, meas_tip),
            ("Integrity", integ, 1.0, _CLARITY_TIPS["integrity"]),
            ("Scope", scope, 0.75, _CLARITY_TIPS["scope"]),
            ("Governance", gov, 0.75, _CLARITY_TIPS["governance"]),
        ], key=f"snapshot_clar_chart_{card_idx}")

    # Governance gap callout — surfaced here so it's visible outside the Clarity column
    if gov < 0.6:
        st.warning(
            "⚠️ **Governance gap flagged.** Your data-compliance sub-score is low. "
            "Return to the **Governance tab** on the form to complete the checklist — "
            "this affects your Clarity score and Act 843 / NDPA compliance (Ghana)."
        )

    # place this here: scoring transparency layer (explanation + personalized weakness panel)
    render_how_scoring_works_panel()
    render_personalized_weakness_panel(
        direct_score=ds, verify_score=vs, recency_score=rs,
        definition_score=def_s, measurement_score=meas_s,
        integrity_score=integ, scope_score=scope, governance_score=gov,
        is_qualitative=is_qual,
    )

    # Evidence Ladder (rule-based, no score impact)
    ladder = ev.get("evidence_ladder", {})
    if ladder:
        st.markdown("#### Evidence Ladder")
        st.caption(
            "Rule-based check of the evidence sources you described — does this "
            "report rely mainly on Basic, Moderate, or Stronger evidence? Hover "
            "over a rung below for details."
        )
        _render_evidence_ladder_chart(ladder, key=f"ladder_chart_{card_idx}")
        st.info(ladder.get("suggestion", ""))

    # Indicator Maturity (rule-based, count-only indicator detection)
    maturity = ev.get("indicator_maturity", {})
    if maturity.get("flagged"):
        st.markdown("#### Indicator Maturity")
        st.caption(
            "This indicator is written as a raw count. Funders increasingly expect "
            "indicators that show whether the result was sustained or verified."
        )
        _your_indicator = (submission.get("logframe_indicator", "") or "").strip() or "(not specified)"
        st.markdown(f"**Your indicator (as written):** {_your_indicator}")
        _maturity_rows = [{"Level": level, "Example wording": wording} for level, wording in maturity["rows"]]
        _maturity_rows[0]["Level"] = "👈 " + _maturity_rows[0]["Level"] + " — what you wrote"
        st.table(_maturity_rows)
        st.caption(
            f"Measurement score adjusted by **{maturity['adjustment']}** for this "
            "count-only indicator framing."
        )

    # Funder Readiness flags (informational only — no score impact)
    st.markdown("#### Funder Readiness")
    st.caption(
        "Two quick checks funders increasingly look for — these do not affect "
        "your Confidence or Clarity scores."
    )
    fr = ev.get("funder_readiness", {})
    lim = fr.get("limitations", {})
    learn = fr.get("learning", {})

    if lim.get("detected"):
        st.success("Limitations disclosed — the report states what the data can't confidently say.")
    else:
        st.warning(
            "No limitations disclosure detected. Consider adding a sentence on what "
            "this data cannot confirm or cannot be generalized to."
        )

    if learn.get("detected"):
        st.success("Learning & adaptation stated — the report describes what was learned and changed.")
    else:
        st.warning(
            "No learning/adaptation statement detected. Consider adding what your "
            "organization learned and how the program adapted as a result."
        )

    # Additional advisory flags (v3.4, score-neutral)
    attrib = submission.get("attribution_contribution", "Not specified")
    disagg = submission.get("disaggregation_status", "Not specified")
    if attrib != "Not specified" or disagg != "Not specified":
        st.markdown("#### Additional Advisory Flags")
        st.caption("Optional checklist answers — advisory only, no effect on your score.")
        if attrib != "Not specified":
            st.markdown(f"- **Attribution vs. contribution distinguished:** {attrib}")
        if disagg != "Not specified":
            st.markdown(f"- **Beneficiary data disaggregated (women, youth, PWD, rural):** {disagg}")

    # Verdict banner
    css_class = _VERDICT_CSS.get(verdict, "")
    st.markdown(
        f"<div class='verdict-banner {css_class}'>{verdict}</div>",
        unsafe_allow_html=True,
    )

    # What To Fix — tailored by diagnostic state
    conf_fixes = [f for f in fixes if f.get("dimension") == "confidence"]
    clar_fixes = [f for f in fixes if f.get("dimension") == "clarity"]

    def _render_conf_fixes(offset=0):
        for j, fix in enumerate(conf_fixes):
            st.checkbox(
                f"{fix['message']}  _({fix['score_impact']})_",
                value=False,
                key=f"fix_conf_{card_idx}_{j + offset}",
            )

    def _render_clar_fixes(offset=0):
        for j, fix in enumerate(clar_fixes):
            st.checkbox(
                f"{fix['message']}  _({fix['score_impact']})_",
                value=False,
                key=f"fix_clar_{card_idx}_{j + offset}",
            )

    if diag_state == "STRONG":
        st.success("No further fixes flagged by this tool's checks.")
        if fixes:
            smallest = fixes[0]
            st.caption(f"Optional refinement: {smallest['message']} ({smallest['score_impact']})")

    elif diag_state == "MISLEADING":
        if clar_fixes:
            st.markdown("##### Sharpen your definition (Clarity) — priority fixes")
            _render_clar_fixes()
        if conf_fixes:
            with st.expander("Confidence fixes (secondary)"):
                _render_conf_fixes()

    elif diag_state == "UNDEREVIDENCED":
        if conf_fixes:
            st.markdown("##### Strengthen your evidence (Confidence) — priority fixes")
            _render_conf_fixes()
        if clar_fixes:
            with st.expander("Clarity fixes (secondary)"):
                _render_clar_fixes()

    elif diag_state == "FUNDAMENTALLY WEAK":
        st.error("This result requires fundamental rework. Both axes need attention.")
        if conf_fixes:
            st.markdown("##### Strengthen your evidence (Confidence)")
            _render_conf_fixes()
        if clar_fixes:
            st.markdown("##### Sharpen your definition (Clarity)")
            _render_clar_fixes()

    elif diag_state == "NEEDS REFINEMENT":
        all_fixes = fixes[:3]
        if all_fixes:
            st.markdown("##### Top fixes to address before submission")
            for j, fix in enumerate(all_fixes):
                dim = fix.get("dimension", "conf")
                st.checkbox(
                    f"{fix['message']}  _({fix['score_impact']})_",
                    value=False,
                    key=f"fix_{dim}_{card_idx}_top_{j}",
                )

    else:
        if conf_fixes:
            st.markdown("##### Strengthen your evidence (Confidence)")
            _render_conf_fixes()
        if clar_fixes:
            st.markdown("##### Sharpen your definition (Clarity)")
            _render_clar_fixes()

    filenames = submission.get("attached_filenames", [])
    if filenames:
        st.caption(f"Attached documents: {', '.join(filenames)}")

    bv_bonus = conf_comp.get("bv_bonus", 0.0)
    if bv_bonus < 0.5:
        bv_fix = BENEFICIARY_VOICE_WHATTOFIX.get(bv_bonus, BENEFICIARY_VOICE_WHATTOFIX[0.0])
        with st.expander("Improve Beneficiary Voice →"):
            st.caption(bv_fix)

    if donor and donor != "Other/Not specified" and donor in DONOR_DIAGNOSTICS:
        st.subheader(f"{donor}-Specific Guidance")
        st.caption(f"Diagnostic language adapted for {donor} submission standards")
        donor_map = DONOR_DIAGNOSTICS[donor]
        checks = [
            ("Directness",       conf_comp.get("direct_score", 0),  2.0),
            ("Verification",     conf_comp.get("verify_score", 0),  2.0),
            ("Recency",          conf_comp.get("recency_score", 0), 1.0),
            ("BeneficiaryVoice", conf_comp.get("bv_bonus", 0.0),    0.5),
        ]
        for dim, raw_score, max_val in checks:
            if dim not in donor_map:
                continue
            level = "low" if (raw_score / max_val) < 0.6 else "high"
            st.markdown(f"**{dim}:** {donor_map[dim][level]}")

    with st.expander("📋 Evidence statement for your report"):
        st.code(_generate_evidence_statement(submission), language=None)
        st.caption("Edit this to match your exact context before pasting into your narrative report.")

    with st.expander("📱 Share this result (WhatsApp / email)"):
        def _share_icon(s):
            return "✅" if s >= 4.0 else "⚠️" if s >= 3.0 else "🔴"
        _tf = fixes[0]["message"] if fixes else "No major gaps — ready to refine."
        _wa_text = (
            f"📊 Impact-Receipts Pre-Submission Check\n"
            f"Confidence: {conf_score}/5.0 {_share_icon(conf_score)}  ·  "
            f"Clarity: {clar_score}/5.0 {_share_icon(clar_score)}\n"
            f"Top fix: {_tf}\n"
            f"Verdict: {verdict}"
        )
        st.code(_wa_text, language=None)
        st.caption("Tap the copy icon above and paste into WhatsApp or your team chat.")

    render_fulltime(
        confidence=round(conf_score * 20),
        clarity=round(clar_score * 20),
        summary=_PLAIN_ENGLISH_VERDICT.get(diag_state, verdict),
    )
    _render_review_handoff(submission, ev, card_idx)
    render_season_teaser()

    st.divider()


def render_screen_2():
    render_pitch_strip("report")
    # Run evaluations once, cache results
    if not st.session_state.get("evaluations"):
        active = st.session_state.get("active_slots_run", st.session_state.get("active_slots", 1))
        subs, evs = [], []
        try:
            render_var_review()
            with st.spinner("VAR reviewing evidence…"):
                for slot in range(1, active + 1):
                    sub = _build_submission_from_session(slot)
                    ev  = _evaluator.evaluate_submission(sub)
                    save_all_files(sub, ev)
                    subs.append(sub)
                    evs.append(ev)
            st.session_state["evaluations"]        = evs
            st.session_state["submissions_snapshot"] = subs
            st.rerun()
        except Exception as exc:
            st.session_state["error_message"] = (
                f"Something went wrong during evaluation:\n\n{exc}\n\nPlease go back and try again."
            )

    if st.session_state.get("error_message"):
        st.error(st.session_state["error_message"])
        if st.button("← Edit Submission"):
            st.session_state["screen"] = 1
            st.session_state["evaluations"]  = None
            st.session_state["error_message"] = None
            st.rerun()
        return

    evs  = st.session_state.get("evaluations") or []
    subs = st.session_state.get("submissions_snapshot") or []

    if not evs:
        st.warning("No evaluation results found. Please go back and try again.")
        if st.button("← Edit Submission"):
            _go_to_screen(1)
        return

    _render_tutorial(2)

    n = len(evs)
    st.markdown(
        "<h2 style='color:#1B5E20;margin-bottom:4px;'>Your Confidence Snapshot</h2>"
        "<p style='color:#8A6500;font-style:italic;font-size:0.95rem;margin-bottom:16px;'>"
        "Here&rsquo;s what would move your result from where it is now to where it needs to be.</p>",
        unsafe_allow_html=True,
    )

    _nav_c1, _nav_c2 = st.columns(2)
    with _nav_c1:
        if st.button("← Edit Submission", key="back_to_form"):
            st.session_state["evaluations"] = None
            _go_to_screen(1)
    with _nav_c2:
        st.caption("**Next steps:** Edit & re-run · Download report below · Submit to donor")

    for i, (sub, ev) in enumerate(zip(subs, evs)):
        if n > 1:
            st.markdown(f"### Result {i + 1}")
        _render_result_card(sub, ev, card_idx=i,
                            donor=st.session_state.get("donor_selected", ""))

    with st.expander("📚 Methodology & Citations", expanded=False):
        st.markdown("""
**Impact-Receipts v3.0 scoring methodology is anchored in:**

- **Data Quality Standards** — adapted from USAID ADS 201.3.5.7, OECD-DAC 2019 evaluation criteria, and FCDO DQA guidance. Used for all Confidence and Clarity sub-scores.

- **Bond Evidence Principles 2024 (refresh)** — particularly Voice & Inclusion (operationalised as the Beneficiary Voice dimension) and Triangulation.

- **60 Decibels Lean Data Methodology** — informs the Beneficiary Voice scoring rubric.

- **Audit Logic** — classical audit independence principle (auditor independence from preparer) operationalised in Verification scoring.

**Why this matters for your donor:** Every sub-score traces to a named, citable standard. Hover over any score to see its specific anchor.

*Impact-Receipts is a pre-submission verification tool, not an audit. It does not replace formal evaluation but identifies gaps that would weaken external review.*
""")
        st.markdown("**Donor framework crosswalk** — how each sub-score maps to the standards your donor audits against:")
        st.markdown(
            build_donor_crosswalk_html(st.session_state.get("donor_framework", "Generic")),
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class="gtm-card">
          <p><strong>Want me to run this check with you?</strong></p>
          <p class="gtm-sub">I personally review results for MEL professionals before their
          submissions. 20 minutes, free for the first session.</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <div class="gtm-btn-gold">
              <a href="https://wa.me/233503648195" target="_blank">Book a Free Pilot with the Founder</a>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # LinkedIn — modern share-offsite endpoint opens the share dialog correctly
    app_url = "https://impact-integrity-diagnostic.streamlit.app"
    li_url  = f"https://www.linkedin.com/sharing/share-offsite/?url={urllib.parse.quote(app_url, safe='')}"
    st.markdown(
        f"Found this useful? "
        f"<a href='{li_url}' target='_blank'>Share Impact-Receipts on LinkedIn</a>"
        f" with a MEL colleague.",
        unsafe_allow_html=True,
    )


    # --- Stage 2 Engagement Card ---
    st.markdown("---")
    with st.container(border=True):
        st.markdown("#### 🎯 Recommended Next Step: Stage 2 Diagnostic Engagement")
        st.info(
            "This diagnostic provides a first-pass profile of your submission readiness posture. "
            "A Stage 2 Engagement with Impact-Receipts offers a structured deep-dive: facilitated "
            "sessions with your MEL/Reporting lead, prioritised fixes to strengthen the compliance, "
            "ethics, clarity, and confidence level of your reported results, and support in aligning "
            "your submission with the relevant donor-required checklists. This moves your submission "
            "from a first-pass profile toward submission-ready integrity."
        )
        if st.button("✉️ Request a Stage 2 Conversation", key="stage2_request_btn", type="primary"):
            st.session_state["_show_stage2_mail_options"] = True

        if st.session_state.get("_show_stage2_mail_options"):
            _s2_to      = "info@impact-receipts.com"
            _s2_subject = "Stage 2 Conversation Request"
            _s2_body = (
                "Hello Impact-Receipts team,\n\n"
                "I would like to request a Stage 2 Diagnostic Engagement conversation "
                "following my Instant Confidence & Clarity Check.\n\n"
                "(Please attach your downloaded report to this email before sending.)\n\n"
                "Organisation:\n"
                "Programme/Project:\n"
            )
            _s2_subject_enc = urllib.parse.quote(_s2_subject)
            _s2_body_enc    = urllib.parse.quote(_s2_body)

            _s2_link_style = (
                "display:inline-block;background:#1B5E20;color:white;padding:8px 18px;"
                "border-radius:8px;text-decoration:none;font-weight:700;font-size:0.85rem;"
                "text-align:center;width:100%;box-sizing:border-box;"
            )
            st.caption("Choose how you'd like to send your request:")
            _s2_c1, _s2_c2, _s2_c3 = st.columns(3)
            with _s2_c1:
                st.markdown(
                    f'<a href="mailto:{_s2_to}?subject={_s2_subject_enc}&body={_s2_body_enc}"'
                    f' style="{_s2_link_style}">📧 Default Mail App</a>',
                    unsafe_allow_html=True,
                )
            with _s2_c2:
                st.markdown(
                    f'<a href="https://mail.google.com/mail/?view=cm&fs=1&to={_s2_to}'
                    f'&su={_s2_subject_enc}&body={_s2_body_enc}"'
                    f' target="_blank" style="{_s2_link_style}">Gmail</a>',
                    unsafe_allow_html=True,
                )
            with _s2_c3:
                st.markdown(
                    f'<a href="https://outlook.office.com/mail/deeplink/compose?to={_s2_to}'
                    f'&subject={_s2_subject_enc}&body={_s2_body_enc}"'
                    f' target="_blank" style="{_s2_link_style}">Outlook</a>',
                    unsafe_allow_html=True,
                )
        st.caption("Tip: download your report below and attach it to the email before sending.")
    # --- End Stage 2 Card ---

    _render_tutorial(3)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_report = _build_html_report(subs[0], evs[0], timestamp) if n == 1 else \
                  _build_combined_html_report(subs, evs, timestamp)

    col_dl, col_json, col_add, col_fresh = st.columns([2, 1.5, 1, 1])
    with col_dl:
        st.download_button(
            label="⬇️ Download HTML Report",
            data=html_report,
            file_name=f"impact_receipts_{timestamp}.html",
            mime="text/html",
            use_container_width=True,
        )
        if st.session_state.get("lite_mode", False):
            st.caption("Low-bandwidth mode: report will be a smaller, self-contained file viewable offline.")
        _pdf_bytes = _html_to_pdf_bytes(html_report)
        if _pdf_bytes:
            st.download_button(
                label="📄 Download PDF Report",
                data=_pdf_bytes,
                file_name=f"impact_receipts_{timestamp}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="pdf_download_btn",
            )
            with st.expander("Report handoff details"):
                st.text_input("Prepared by (your name)", key="report_prepared_by")
                st.selectbox("Status", _REPORT_STATUS_OPTIONS, key="report_status")
                st.text_area("Notes for reviewer (optional)", key="report_notes", height=80)
            _summary_html = _build_verification_summary_html(subs, evs, timestamp)
            _summary_pdf  = _html_to_pdf_bytes(_summary_html)
            if _summary_pdf:
                st.download_button(
                    label="📋 Download Verification Summary (PDF)",
                    data=_summary_pdf,
                    file_name=f"verification_summary_{timestamp}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="verification_summary_pdf_btn",
                )

            st.markdown(f"##### {_DONOR_TEMPLATE_COPY['section_header']}")
            if _HAS_DOCX:
                _donor_key = st.selectbox(
                    _DONOR_TEMPLATE_COPY["selector_label"],
                    options=list(_DONOR_TEMPLATES.keys()),
                    format_func=lambda k: _DONOR_TEMPLATES[k]["label"],
                    key="donor_template_select",
                )
                _template = _DONOR_TEMPLATES[_donor_key]
                _field_rows = _donor_template_field_rows(_template, subs[0], evs[0])

                with st.expander(f"{_DONOR_TEMPLATE_COPY['preview_label']} — {_template['label']}"):
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(_field_rows)[["Section", "Template field", "Diagnostic source", "Value"]],
                        use_container_width=True, hide_index=True,
                    )

                _missing_required = [r["Template field"] for r in _field_rows if r["required"] and not r["provided"]]
                if _missing_required:
                    st.warning(
                        _DONOR_TEMPLATE_COPY["missing_required_intro"] + "\n"
                        + "\n".join(f"- {m}" for m in _missing_required)
                    )

                st.download_button(
                    label=f"📄 Download {_template['label']} Template (DOCX)",
                    data=_build_donor_template_docx(_template, subs[0], evs[0], timestamp),
                    file_name=f"{_donor_key}_template_{timestamp}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    key="donor_template_docx_btn",
                )
            else:
                st.caption(_DONOR_TEMPLATE_COPY["no_docx"])
        else:
            st.caption("PDF: install xhtml2pdf to enable one-click PDF download.")
    with col_json:
        st.download_button(
            label="Save Inputs (JSON)",
            data=_build_inputs_json(timestamp),
            file_name=f"impact-receipts-inputs-{timestamp}.json",
            mime="application/json",
            use_container_width=True,
            help="Save your form inputs as JSON so you can reload them later for iteration.",
        )
    with col_add:
        if n < 3:
            if st.button("＋ Add Another Result", use_container_width=True):
                st.session_state["active_slots"] = n + 1
                st.session_state["evaluations"]  = None
                st.session_state["submissions_snapshot"] = None
                st.session_state["screen"] = 1
                st.rerun()
    with col_fresh:
        if st.button("Check Another Result", use_container_width=True):
            _clear_draft()
            _go_to_screen(1, reset=True)

    _all_fixes = []
    for _ev in evs:
        _all_fixes.extend(_ev.get("fixes", []))
    if _all_fixes:
        with st.expander("💡 Suggested fixes to improve your submission", expanded=True):
            for _fix in _all_fixes[:5]:
                _fix_msg    = _fix.get("message", "")
                _fix_impact = _fix.get("score_impact", "")
                if _fix_impact:
                    st.markdown(f"- {_fix_msg} *({_fix_impact})*")
                else:
                    st.markdown(f"- {_fix_msg}")

    _render_tagline_footer()


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------

def save_all_files(submission: dict, evaluation: dict) -> dict:
    os.makedirs("inputs", exist_ok=True)
    os.makedirs("evaluations", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug      = _make_slug(submission.get("result_statement", "result"))
    base      = f"{timestamp}_{slug}"

    paths = {
        "input":      os.path.join("inputs",      f"{base}_input.json"),
        "evaluation": os.path.join("evaluations", f"{base}_evaluation.json"),
        "output":     os.path.join("outputs",     f"{base}_report.md"),
    }

    with open(paths["input"], "w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2, ensure_ascii=False, default=str)

    save_eval = {k: v for k, v in evaluation.items() if not k.startswith("_")}

    # --- Trends over time: additive fields, no scoring math changed ---
    _conf_comp = evaluation.get("confidence_components", {}) or {}
    _clar_comp = evaluation.get("clarity_components", {}) or {}
    _indicator_label = (submission.get("logframe_indicator") or "").strip()
    save_eval.update({
        "indicator_id":    _indicator_label.lower(),
        "indicator_label": _indicator_label,
        "project_name":    submission.get("project_name", ""),
        "submission_date": datetime.now().strftime("%Y-%m-%d"),
        "import_source":   submission.get("import_source", "manual"),
        "sub_scores": {
            "Directness":   _conf_comp.get("direct_score"),
            "Verification": _conf_comp.get("verify_score"),
            "Recency":      _conf_comp.get("recency_score"),
            "Definition":   _clar_comp.get("definition_score"),
            "Measurement":  _clar_comp.get("measurement_score"),
            "Integrity":    _clar_comp.get("integrity_score"),
            "Scope":        _clar_comp.get("scope_score"),
            "Governance":   _clar_comp.get("governance_score"),
        },
    })
    # --- END Trends over time ---

    with open(paths["evaluation"], "w", encoding="utf-8") as f:
        json.dump(save_eval, f, indent=2, ensure_ascii=False)

    report = _build_html_report(submission, evaluation, timestamp)
    with open(paths["output"], "w", encoding="utf-8") as f:
        f.write(report)

    return paths


def _make_slug(text: str, max_len: int = 45) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len]


# ---------------------------------------------------------------------------
# Trends over time
# ---------------------------------------------------------------------------

_TREND_COPY = {
    "header": "📈 Trends over time",
    "intro": "See how each indicator's Confidence and Clarity scores change across reporting cycles.",
    "no_data": "No saved submissions yet. Run a check on Screen 2 to start building history for this view.",
    "one_point": "Not enough history yet to show a trend — only one submission recorded so far for this indicator.",
    "select_primary": "Select an indicator/result to view its trend",
    "select_compare": "Compare with other indicators (optional)",
    "delta_caption": "Change since previous submission ({prev_date} → {curr_date}):",
}

_TREND_SUB_SCORE_DIMS = [
    "Directness", "Verification", "Recency", "Definition",
    "Measurement", "Integrity", "Scope", "Governance",
]


def _load_trend_history():
    """Scan evaluations/*_evaluation.json and build a tidy history of saved
    submissions: one row per file with indicator_id, indicator_label,
    project_name, date, confidence_score, clarity_score, and the 8 sub-scores.

    Pre-existing evaluation files (saved before this feature) are backfilled
    from their paired inputs/*_input.json and filename timestamp. Rows with
    no indicator label are skipped — never fabricated.
    """
    import glob
    import pandas as pd

    rows = []
    for path in sorted(glob.glob(os.path.join("evaluations", "*_evaluation.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                ev = json.load(f)
        except Exception:
            continue

        base = os.path.basename(path)[: -len("_evaluation.json")]

        indicator_label = ev.get("indicator_label")
        project_name    = ev.get("project_name")
        date_str        = ev.get("submission_date")
        sub_scores      = ev.get("sub_scores")

        if indicator_label is None or project_name is None:
            sub = {}
            input_path = os.path.join("inputs", f"{base}_input.json")
            if os.path.exists(input_path):
                try:
                    with open(input_path, encoding="utf-8") as f:
                        sub = json.load(f)
                except Exception:
                    sub = {}
            if indicator_label is None:
                indicator_label = (sub.get("logframe_indicator") or "").strip()
            if project_name is None:
                project_name = sub.get("project_name", "")

        if not date_str:
            try:
                date_str = datetime.strptime(base[:15], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d")
            except ValueError:
                date_str = ""

        if not indicator_label:
            continue  # can't place on a per-indicator trend without a label

        if not sub_scores:
            _conf_comp = ev.get("confidence_components", {}) or {}
            _clar_comp = ev.get("clarity_components", {}) or {}
            sub_scores = {
                "Directness":   _conf_comp.get("direct_score"),
                "Verification": _conf_comp.get("verify_score"),
                "Recency":      _conf_comp.get("recency_score"),
                "Definition":   _clar_comp.get("definition_score"),
                "Measurement":  _clar_comp.get("measurement_score"),
                "Integrity":    _clar_comp.get("integrity_score"),
                "Scope":        _clar_comp.get("scope_score"),
                "Governance":   _clar_comp.get("governance_score"),
            }

        row = {
            "indicator_id":     indicator_label.strip().lower(),
            "indicator_label":  indicator_label,
            "project_name":     project_name or "",
            "date":             date_str,
            "confidence_score": ev.get("confidence_score"),
            "clarity_score":    ev.get("clarity_score"),
        }
        for dim in _TREND_SUB_SCORE_DIMS:
            row[dim] = sub_scores.get(dim)
        rows.append(row)

    return pd.DataFrame(rows)


def _trend_indicator_options(history_df):
    """Return {indicator_id: display_label} for the selectors, in first-seen order."""
    options = {}
    for _, row in history_df.iterrows():
        iid = row["indicator_id"]
        if iid in options:
            continue
        label = row["indicator_label"]
        if row.get("project_name"):
            label = f"{label} — {row['project_name']}"
        options[iid] = label
    return options


def _render_trend_chart(plot_df, value_col, y_title, color_col=None):
    """Render a date-vs-score line chart, Altair normally, st.line_chart in lite mode."""
    if st.session_state.get("lite_mode", False):
        if color_col:
            pivoted = plot_df.pivot(index="date", columns=color_col, values=value_col)
        else:
            pivoted = plot_df.set_index("date")[[value_col]]
        st.line_chart(pivoted)
        return

    import altair as alt
    enc = {
        "x": alt.X("date:T", title="Date"),
        "y": alt.Y(f"{value_col}:Q", title=y_title, scale=alt.Scale(domain=[0, 5])),
        "tooltip": ["date:T", f"{value_col}:Q"] + ([f"{color_col}:N"] if color_col else []),
    }
    if color_col:
        enc["color"] = alt.Color(f"{color_col}:N", title=None)
        enc["tooltip"] = ["date:T", f"{color_col}:N", f"{value_col}:Q"]
    chart = alt.Chart(plot_df).mark_line(point=True).encode(**enc).properties(width="container")
    st.altair_chart(chart, use_container_width=True)


def render_trends_view(history_df) -> None:
    """Render the 'Trends over time' section for a selected indicator,
    with optional side-by-side comparison against other indicators."""
    import pandas as pd

    if history_df.empty:
        st.info(_TREND_COPY["no_data"])
        return

    options = _trend_indicator_options(history_df)
    ids = list(options.keys())

    primary_id = st.selectbox(
        _TREND_COPY["select_primary"],
        options=ids,
        format_func=lambda i: options[i],
        key="trend_primary_indicator",
    )
    compare_ids = st.multiselect(
        _TREND_COPY["select_compare"],
        options=[i for i in ids if i != primary_id],
        format_func=lambda i: options[i],
        key="trend_compare_indicators",
    )

    primary_df = (history_df[history_df["indicator_id"] == primary_id]
                   .sort_values("date").reset_index(drop=True))

    if len(primary_df) == 1:
        row = primary_df.iloc[0]
        st.info(_TREND_COPY["one_point"])
        cols = st.columns(2)
        cols[0].metric("Confidence", f"{row['confidence_score']}/5.0")
        cols[1].metric("Clarity", f"{row['clarity_score']}/5.0")
        sub_cols = st.columns(4)
        for i, dim in enumerate(_TREND_SUB_SCORE_DIMS):
            val = row.get(dim)
            if pd.notna(val):
                sub_cols[i % 4].metric(dim, val)
    else:
        long_rows = []
        for _, row in primary_df.iterrows():
            long_rows.append({"date": row["date"], "series": "Confidence", "score": row["confidence_score"]})
            long_rows.append({"date": row["date"], "series": "Clarity", "score": row["clarity_score"]})
        _render_trend_chart(pd.DataFrame(long_rows), "score", "Score (0-5)", color_col="series")

        prev, curr = primary_df.iloc[-2], primary_df.iloc[-1]
        st.caption(_TREND_COPY["delta_caption"].format(prev_date=prev["date"], curr_date=curr["date"]))
        cols = st.columns(2)
        cols[0].metric("Confidence", f"{curr['confidence_score']}/5.0",
                        delta=round(curr["confidence_score"] - prev["confidence_score"], 2))
        cols[1].metric("Clarity", f"{curr['clarity_score']}/5.0",
                        delta=round(curr["clarity_score"] - prev["clarity_score"], 2))
        sub_cols = st.columns(4)
        for i, dim in enumerate(_TREND_SUB_SCORE_DIMS):
            cv, pv = curr.get(dim), prev.get(dim)
            if pd.isna(cv) or pd.isna(pv):
                continue
            delta = round(cv - pv, 2)
            if delta != 0:
                sub_cols[i % 4].metric(dim, cv, delta=delta)

    if compare_ids:
        compare_df = history_df[history_df["indicator_id"].isin([primary_id] + compare_ids)].copy()
        compare_df["label"] = compare_df["indicator_id"].map(options)
        st.markdown("##### Confidence comparison")
        _render_trend_chart(compare_df.sort_values("date"), "confidence_score", "Confidence (0-5)", color_col="label")
        st.markdown("##### Clarity comparison")
        _render_trend_chart(compare_df.sort_values("date"), "clarity_score", "Clarity (0-5)", color_col="label")


# ---------------------------------------------------------------------------
# Donor template export
# ---------------------------------------------------------------------------

_DONOR_TEMPLATE_COPY = {
    "section_header": "Donor Template Export",
    "selector_label": "Export for:",
    "preview_label": "Preview field mapping",
    "missing_required_intro": "Before exporting, note: these required fields have no verified data yet and will be marked \"Not provided\" in the export:",
    "no_docx": "Donor template export needs python-docx. Install it to enable this.",
}

_DONOR_TEMPLATES = {
    "generic": {
        "label": "Generic",
        "sections": [
            {
                "heading": "Result Overview",
                "fields": [
                    {"label": "Project / Programme Name", "source": "submission.project_name"},
                    {"label": "Result Statement",          "source": "submission.result_statement"},
                    {"label": "Logframe Indicator",         "source": "submission.logframe_indicator"},
                    {"label": "Reporting Period",           "source": "submission.timeframe"},
                    {"label": "Target Group",               "source": "submission.target_group"},
                    {"label": "Geographic Scope",           "source": "submission.geographic_scope"},
                ],
                "required": ["Project / Programme Name", "Result Statement", "Logframe Indicator"],
            },
            {
                "heading": "Evidence Quality Scores",
                "fields": [
                    {"label": "Confidence Score (0-5)", "source": "evaluation.confidence_score"},
                    {"label": "Confidence Rating",       "source": "evaluation.confidence_label"},
                    {"label": "Clarity Score (0-5)",     "source": "evaluation.clarity_score"},
                    {"label": "Clarity Rating",          "source": "evaluation.clarity_label"},
                ],
                "required": [],
            },
            {
                "heading": "Verification & Sign-off",
                "fields": [
                    {"label": "Internal Review Level", "source": "submission.internal_review"},
                    {"label": "External Review Level", "source": "submission.external_review"},
                    {"label": "Prepared By",            "source": "session.report_prepared_by"},
                    {"label": "Status",                 "source": "session.report_status"},
                ],
                "required": [],
            },
        ],
    },
    "usaid": {
        "label": "USAID",
        "sections": [
            {
                "heading": "Activity / Indicator Information",
                "fields": [
                    {"label": "Activity Name",          "source": "submission.project_name"},
                    {"label": "Performance Indicator",  "source": "submission.logframe_indicator"},
                    {"label": "Reporting Period",        "source": "submission.timeframe"},
                    {"label": "Target",                  "source": "submission.logframe_target"},
                    {"label": "Achieved Result",         "source": "submission.logframe_achievement"},
                ],
                "required": ["Activity Name", "Performance Indicator", "Target", "Achieved Result"],
            },
            {
                "heading": "Data Quality Assessment (DQA)",
                "fields": [
                    {"label": "Validity (Directness)",                  "source": "subscore.Directness"},
                    {"label": "Reliability / Integrity (Verification)", "source": "subscore.Verification"},
                    {"label": "Timeliness (Recency)",                   "source": "subscore.Recency"},
                    {"label": "Precision (Definition)",                 "source": "subscore.Definition"},
                    {"label": "Precision (Measurement)",                "source": "subscore.Measurement"},
                    {"label": "Integrity (Ethics)",                     "source": "subscore.Integrity"},
                    {"label": "Confidence Rating",                      "source": "evaluation.confidence_label"},
                    {"label": "Clarity Rating",                         "source": "evaluation.clarity_label"},
                ],
                "required": ["Validity (Directness)", "Reliability / Integrity (Verification)"],
            },
            {
                "heading": "DQA Limitations & Sign-off",
                "fields": [
                    {"label": "Known Data Limitations", "source": "submission.limitations_notes"},
                    {"label": "Prepared By",             "source": "session.report_prepared_by"},
                    {"label": "Status",                  "source": "session.report_status"},
                ],
                "required": [],
            },
        ],
    },
}


def _resolve_donor_field_value(source: str, submission: dict, evaluation: dict):
    """Resolve a 'namespace.key' source string from a donor template config
    against the current submission/evaluation/session data.
    Returns (value, provided) — provided=False means no real data exists,
    caller must render 'Not provided' and never fabricate a value."""
    if not source:
        return None, False
    namespace, _, key = source.partition(".")
    if namespace == "submission":
        val = submission.get(key)
    elif namespace == "evaluation":
        val = evaluation.get(key)
    elif namespace == "subscore":
        conf = evaluation.get("confidence_components", {}) or {}
        clar = evaluation.get("clarity_components", {}) or {}
        val = {
            "Directness":   conf.get("direct_score"),
            "Verification": conf.get("verify_score"),
            "Recency":      conf.get("recency_score"),
            "Definition":   clar.get("definition_score"),
            "Measurement":  clar.get("measurement_score"),
            "Integrity":    clar.get("integrity_score"),
            "Scope":        clar.get("scope_score"),
            "Governance":   clar.get("governance_score"),
        }.get(key)
    elif namespace == "session":
        val = st.session_state.get(key)
    else:
        val = None
    provided = val is not None and str(val).strip() != ""
    return val, provided


def _donor_template_field_rows(template: dict, submission: dict, evaluation: dict) -> list:
    """One row per template field: section, label, source, value (or
    'Not provided'), provided flag, required flag. Used for both the
    mapping-preview table and the pre-export checklist."""
    rows = []
    for section in template["sections"]:
        required = set(section.get("required", []))
        for field in section["fields"]:
            value, provided = _resolve_donor_field_value(field["source"], submission, evaluation)
            rows.append({
                "Section": section["heading"],
                "Template field": field["label"],
                "Diagnostic source": field["source"],
                "Value": value if provided else "Not provided",
                "provided": provided,
                "required": field["label"] in required,
            })
    return rows


def _build_donor_template_docx(template: dict, submission: dict, evaluation: dict, timestamp: str) -> bytes:
    """Render submission/evaluation into the selected donor template as an
    editable DOCX. Fields with no verified data are written literally as
    'Not provided' — never inferred or fabricated."""
    import io

    doc = _docx.Document()
    doc.add_heading(f"{template['label']} Report", level=0)
    doc.add_paragraph(f"Generated by Impact-Receipts: {timestamp}")

    for section in template["sections"]:
        doc.add_heading(section["heading"], level=1)
        table = doc.add_table(rows=0, cols=2)
        table.style = "Light Grid Accent 1"
        for field in section["fields"]:
            value, provided = _resolve_donor_field_value(field["source"], submission, evaluation)
            cells = table.add_row().cells
            cells[0].text = field["label"]
            cells[1].text = str(value) if provided else "Not provided"

    doc.add_heading("About this export", level=1)
    doc.add_paragraph(
        f"Evaluated using {METHODOLOGY_STACK}. {_LIMITS_DISCLAIMER} "
        "Fields marked 'Not provided' had no verified data entered for this "
        "submission and were intentionally left blank."
    )

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _html_to_pdf_bytes(html: str) -> bytes | None:
    """Convert an HTML report string to PDF bytes via xhtml2pdf, or None if unavailable."""
    try:
        from xhtml2pdf import pisa as _pisa
        import io as _io2
        buf = _io2.BytesIO()
        _pisa.CreatePDF(src=html, dest=buf)
        if buf.tell() > 0:
            buf.seek(0)
            return buf.getvalue()
    except ImportError:
        pass
    return None


def _generate_evidence_statement(submission: dict) -> str:
    """Generate a copy-pasteable evidence statement for the narrative report
    from the submission data already entered. No AI — template only."""
    ev      = (submission.get("evidence") or [{}])[0]
    ev_type = ev.get("type", "")
    recency = ev.get("recency", "")
    verifier= ev.get("verified_by", "")
    tg      = submission.get("target_group", "")
    tf      = submission.get("timeframe", "")
    bv      = submission.get("beneficiary_voice", "")
    parts   = [f"Evidence for this result was collected via {ev_type}" if ev_type else "Evidence was collected"]
    if tg:  parts[0] += f" among {tg}"
    if tf:  parts[0] += f" during {tf}"
    parts[0] += "."
    if verifier:
        parts.append(f"Data were independently reviewed by {verifier}.")
    if bv and not any(skip in bv for skip in ("No beneficiary", "Not applicable", "Choose")):
        parts.append(f"Beneficiary perspective: {bv}.")
    if recency:
        parts.append(f"Evidence date: {recency}.")
    return " ".join(parts)


def _build_markdown_report(submission: dict, evaluation: dict, timestamp: str) -> str:
    conf_score = evaluation.get("confidence_score", 0)
    clar_score = evaluation.get("clarity_score", 0)
    conf_label = evaluation.get("confidence_label", "")
    clar_label = evaluation.get("clarity_label", "")
    verdict    = evaluation.get("verdict", "")
    fixes      = evaluation.get("fixes", [])
    conf_comp  = evaluation.get("confidence_components", {})
    clar_comp  = evaluation.get("clarity_components", {})
    filenames  = submission.get("attached_filenames", [])

    lines = [
        "# Impact-Receipts Evaluation Report",
        f"**Generated:** {timestamp}",
        f"**Confidence Score:** {conf_score}/5.0 ({conf_label})",
        f"**Clarity Score:** {clar_score}/5.0 ({clar_label})",
        f"**Verdict:** {verdict}",
        "",
        "---",
        "",
        "## Result Statement",
        f"{submission.get('result_statement', '-')}",
        "",
        f"- **Target Group:** {submission.get('target_group', '-')}",
        f"- **Timeframe:** {submission.get('timeframe', '-')}",
        f"- **Geographic Scope:** {submission.get('geographic_scope', '-')}",
        "",
    ]

    if filenames:
        lines += [f"- **Attached documents:** {', '.join(filenames)}", ""]

    lines += [
        "---",
        "",
        "## Confidence Score Breakdown",
        "",
        "| Component | Level | Score |",
        "|---|---|---|",
        f"| Directness   | {conf_comp.get('direct_level', '-')}/5  | {conf_comp.get('direct_score', '-')}/2.0 |",
        f"| Verification | {conf_comp.get('verify_level', '-')}/5  | {conf_comp.get('verify_score', '-')}/2.0 |",
        f"| Recency      | {conf_comp.get('recency_level', '-')}/5 | {conf_comp.get('recency_score', '-')}/1.0 |",
        f"| **Total**    |                                          | **{conf_score}/5.0** |",
        "",
        "## Clarity Score Breakdown",
        "",
        "| Component   | Score | Max  |",
        "|---|---|---|",
        f"| Definition  | {clar_comp.get('definition_score', '-')}  | 1.25 |",
        f"| Measurement | {clar_comp.get('measurement_score', '-')} | 1.25 |",
        f"| Integrity   | {clar_comp.get('integrity_score', '-')}   | 1.0  |",
        f"| Scope       | {clar_comp.get('scope_score', '-')}       | 0.75 |",
        f"| Governance  | {clar_comp.get('governance_score', '-')}  | 0.75 |",
        f"| **Total**   | **{clar_score}**                          | **5.0** |",
        "",
        "---",
        "",
        "## What To Fix",
        "",
    ]

    conf_fixes = [f for f in fixes if f.get("dimension") == "confidence"]
    clar_fixes = [f for f in fixes if f.get("dimension") == "clarity"]

    if conf_fixes:
        lines.append("### Strengthen your evidence (Confidence)")
        for fix in conf_fixes:
            lines.append(f"- [ ] {fix['message']}  *({fix['score_impact']})*")
        lines.append("")

    if clar_fixes:
        lines.append("### Sharpen your definition (Clarity)")
        for fix in clar_fixes:
            lines.append(f"- [ ] {fix['message']}  *({fix['score_impact']})*")
        lines.append("")

    if not fixes:
        lines += ["No further fixes flagged by this tool's checks.", ""]

    lines += [
        "---",
        "",
        f"*Evaluated using: {METHODOLOGY_STACK}*",
    ]

    return "\n".join(lines)



# ---------------------------------------------------------------------------
# Portfolio / Framework Dashboard — helpers
# ---------------------------------------------------------------------------

_PORTFOLIO_SUBSCORE_DIMENSIONS = [
    ("Directness",   2.0),
    ("Verification", 2.0),
    ("Recency",      1.0),
    ("Definition",   1.25),
    ("Measurement",  1.25),
    ("Integrity",    1.0),
    ("Scope",        0.75),
    ("Governance",   0.75),
]


def _portfolio_template_csv() -> bytes:
    """Build a one-row example CSV for the Portfolio Dashboard upload."""
    import pandas as pd

    headers = [c[0] for c in _PORTFOLIO_COLUMNS]
    example = {c[0]: c[2] for c in _PORTFOLIO_COLUMNS}
    df = pd.DataFrame([example], columns=headers)
    return df.to_csv(index=False).encode("utf-8")


def _portfolio_row_to_submission(row: dict) -> dict:
    """Map one CSV/Excel row to an evaluator-compatible submission dict."""
    def _get(key, default=""):
        val = row.get(key, default)
        if val is None:
            return default
        val = str(val).strip()
        if val.lower() == "nan":
            return default
        return val or default

    internal_review = _get("internal_review", "Not reviewed") or "Not reviewed"
    external_review = _get("external_review", "No external review") or "No external review"

    def _get_bool(key):
        return _get(key, "FALSE").strip().lower() in ("true", "yes", "1", "x")

    return {
        "result_statement":   _get("result_statement"),
        "target_group":       _get("target_group"),
        "timeframe":          _get("timeframe"),
        "geographic_scope":   _get("geographic_scope"),
        "additional_context": "",
        "learning_notes":     _get("learning_notes"),
        "limitations_notes":  _get("limitations_notes"),
        "internal_review":    internal_review,
        "external_review":    external_review,
        "logframe_indicator":   _get("logframe_indicator"),
        "logframe_target":      _get("logframe_target"),
        "logframe_achievement": _get("logframe_achievement"),
        "evidence": [{
            "type":        _get("evidence_type"),
            "description": _get("evidence_description"),
            "recency":     _get("evidence_date"),
            "verified_by": _get("verifier"),
        }],
        "qualitative_rigor_checklist": {
            "sourcing_documented":           _get_bool("qual_sourcing_documented"),
            "triangulated":                  _get_bool("qual_triangulated"),
            "bias_considered":               _get_bool("qual_bias_considered"),
            "beneficiary_voice_represented": _get_bool("qual_beneficiary_voice_represented"),
            "consent_ethics_addressed":      _get_bool("qual_consent_ethics_addressed"),
        },
    }


def _evaluate_portfolio(df):
    """Evaluate each row of a portfolio DataFrame.

    Returns (results_df, warnings) where results_df is sorted by
    confidence_score ascending (weakest indicators first).
    """
    import pandas as pd

    required = [c[0] for c in _PORTFOLIO_COLUMNS if c[1]]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        return None, [f"Missing required column(s): {', '.join(missing_cols)}"]

    rows = []
    warnings = []
    for i, row in df.iterrows():
        row_dict = row.to_dict()
        label = str(row_dict.get("indicator_name", "")).strip() or f"Row {i + 2}"
        try:
            sub = _portfolio_row_to_submission(row_dict)
            ev = _evaluator.evaluate_submission(sub)
            conf_comp = ev.get("confidence_components", {})
            clar_comp = ev.get("clarity_components", {})
            sub_scores = {
                "Directness":   conf_comp.get("direct_score", 0),
                "Verification": conf_comp.get("verify_score", 0),
                "Recency":      conf_comp.get("recency_score", 0),
                "Definition":   clar_comp.get("definition_score", 0),
                "Measurement":  clar_comp.get("measurement_score", 0),
                "Integrity":    clar_comp.get("integrity_score", 0),
                "Scope":        clar_comp.get("scope_score", 0),
                "Governance":   clar_comp.get("governance_score", 0),
            }
            result_row = {
                "indicator_name":   label,
                "logframe_indicator": sub.get("logframe_indicator", ""),
                "confidence_score": ev.get("confidence_score", 0),
                "clarity_score":    ev.get("clarity_score", 0),
                "verdict":          ev.get("verdict", ""),
                "top_fix":          (ev.get("fixes") or [{}])[0].get("message", "") if ev.get("fixes") else "",
            }
            for dim, max_val in _PORTFOLIO_SUBSCORE_DIMENSIONS:
                pct = round(min(sub_scores[dim] / max_val, 1.0) * 100, 1) if max_val else 0.0
                result_row[dim] = pct
            rows.append(result_row)
        except Exception as exc:
            warnings.append(f"{label}: could not be evaluated ({exc})")

    if not rows:
        return None, warnings or ["No rows could be evaluated."]

    results_df = pd.DataFrame(rows).sort_values("confidence_score", ascending=True).reset_index(drop=True)
    return results_df, warnings


def _portfolio_heatmap_chart(results_df):
    """Build an Altair heatmap: rows = indicators, columns = sub-score dimensions."""
    import pandas as pd
    import altair as alt

    dims = [d for d, _ in _PORTFOLIO_SUBSCORE_DIMENSIONS]
    long_df = results_df.melt(
        id_vars=["indicator_name"], value_vars=dims,
        var_name="Dimension", value_name="% of target",
    )
    order = list(results_df["indicator_name"])

    return (
        alt.Chart(long_df)
        .mark_rect()
        .encode(
            x=alt.X("Dimension:N", sort=dims, title=None),
            y=alt.Y("indicator_name:N", sort=order, title=None),
            color=alt.Color(
                "% of target:Q",
                scale=alt.Scale(domain=[0, 100], scheme="redyellowgreen"),
                legend=alt.Legend(title="% of target"),
            ),
            tooltip=[
                alt.Tooltip("indicator_name:N", title="Indicator"),
                alt.Tooltip("Dimension:N", title="Dimension"),
                alt.Tooltip("% of target:Q", title="% of target"),
            ],
        )
        .properties(width="container", height=alt.Step(28))
    )


# ---------------------------------------------------------------------------
# CSV Import — bulk submissions from external M&E exports
# ---------------------------------------------------------------------------

_CSV_IMPORT_COPY = {
    "header": "📥 Import Submissions from CSV",
    "intro": (
        "Upload a CSV export from your M&E system (KoboToolbox, DHIS2, Excel, "
        "etc.), map its columns to diagnostic fields, then preview and confirm "
        "before importing. Imported submissions are scored by the same checks "
        "as manual entries and flagged \"Imported — unverified\" until reviewed."
    ),
    "not_mapped": "— Not mapped —",
    "new_mapping": "— New mapping —",
    "profile_label": "Mapping profile",
    "save_profile_label": "Save this mapping as a profile",
    "save_profile_button": "💾 Save profile",
    "profile_saved": "Mapping profile saved.",
    "preview_header": "Preview",
    "summary_template": "{n} row(s) • {m} with missing required fields • {d} duplicate(s)",
    "skip_incomplete": "Skip rows with missing required fields",
    "confirm_checkbox": "I've reviewed this preview and want to import these rows",
    "import_button": "Import & Score",
    "import_done": (
        "Imported {k} submission(s), scored, and flagged \"Imported — unverified\". "
        "Review the Internal/External Review fields and verify the underlying "
        "evidence before relying on these results in a donor report."
    ),
    "no_rows": "No rows left to import after applying your settings.",
    "parse_error_prefix": "Could not read this CSV",
}

# (target_key, label, required, value_type) — value_type in {"text", "bool", "date"}
_CSV_IMPORT_FIELDS = [
    ("result_statement",         "Result Statement",        True,  "text"),
    ("target_group",              "Target Group",            True,  "text"),
    ("timeframe",                 "Timeframe",               True,  "text"),
    ("geographic_scope",          "Geographic Scope",        True,  "text"),
    ("evidence_type",             "Evidence Type",           True,  "text"),
    ("evidence_description",      "Evidence Description",    True,  "text"),
    ("evidence_date",             "Evidence Date / Recency", False, "date"),
    ("verified_by",               "Evidence Verified By",    False, "text"),
    ("internal_review",           "Internal Review Level",   False, "text"),
    ("external_review",           "External Review Level",   False, "text"),
    ("logframe_indicator",        "Logframe Indicator",      False, "text"),
    ("logframe_target",           "Logframe Target",         False, "text"),
    ("logframe_achievement",      "Logframe Achievement",    False, "text"),
    ("learning_notes",            "Learning Notes",          False, "text"),
    ("limitations_notes",         "Limitations Notes",       False, "text"),
    ("beneficiary_voice",         "Beneficiary Voice",       False, "text"),
    ("project_name",              "Project Name",            False, "text"),
    ("donor",                     "Donor",                    False, "text"),
    ("sector",                    "Sector",                   False, "text"),
    ("qual_sourcing_documented",  "Qual: Sourcing Documented (true/false)", False, "bool"),
    ("qual_triangulated",         "Qual: Triangulated (true/false)",       False, "bool"),
    ("qual_bias_considered",      "Qual: Bias Considered (true/false)",    False, "bool"),
    ("qual_beneficiary_voice_represented", "Qual: Beneficiary Voice Represented (true/false)", False, "bool"),
    ("qual_consent_ethics_addressed",      "Qual: Consent/Ethics Addressed (true/false)",      False, "bool"),
]

_CSV_IMPORT_PROFILES_PATH = "csv_import_profiles.json"


def _load_import_profiles() -> dict:
    """Load saved CSV column-mapping profiles. Returns {} if none exist yet."""
    if not os.path.exists(_CSV_IMPORT_PROFILES_PATH):
        return {}
    try:
        with open(_CSV_IMPORT_PROFILES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_import_profiles(profiles: dict) -> None:
    """Persist CSV column-mapping profiles to disk."""
    with open(_CSV_IMPORT_PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)


def _parse_import_csv(uploaded_file):
    """Read an uploaded CSV robustly: tries utf-8-sig/latin-1, sniffs the
    delimiter, detects an extra title row before the real header, strips
    whitespace, and drops fully-blank rows.

    Returns (df, None) on success or (None, error_message) on failure.
    """
    import csv
    import io
    import pandas as pd

    raw = uploaded_file.getvalue()
    text = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None, f"{_CSV_IMPORT_COPY['parse_error_prefix']}: unrecognised text encoding."

    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return None, f"{_CSV_IMPORT_COPY['parse_error_prefix']}: the file appears to be empty."

    sample = "\n".join(lines[:10])
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","

    # Header-row detection: find the first line whose field count (>= 2)
    # matches the next line's field count — handles an extra title row.
    header_idx = 0
    for i in range(min(len(lines) - 1, 5)):
        this_count = len(lines[i].split(delimiter))
        next_count = len(lines[i + 1].split(delimiter))
        if this_count >= 2 and this_count == next_count:
            header_idx = i
            break

    try:
        df = pd.read_csv(
            io.StringIO("\n".join(lines)),
            sep=delimiter,
            skiprows=header_idx,
            skip_blank_lines=True,
            dtype=str,
        )
    except Exception as exc:
        return None, f"{_CSV_IMPORT_COPY['parse_error_prefix']}: {exc}"

    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    df = df.dropna(how="all")

    if df.empty:
        return None, f"{_CSV_IMPORT_COPY['parse_error_prefix']}: no data rows found."

    return df.reset_index(drop=True), None


def _csv_row_to_submission(row: dict, column_map: dict, profile_name: str) -> dict:
    """Build a full submission dict from one CSV row using column_map
    (target_key -> CSV column name). Unmapped fields stay empty/False —
    never inferred or fabricated. Marks the result as an unverified import."""

    def _val(target_key, default=""):
        col = column_map.get(target_key)
        if not col:
            return default
        v = row.get(col)
        if v is None:
            return default
        v = str(v).strip()
        if not v or v.lower() == "nan":
            return default
        return v

    def _bool(target_key):
        return _val(target_key).strip().lower() in ("true", "yes", "1", "x")

    return {
        "result_statement":   _val("result_statement"),
        "target_group":       _val("target_group"),
        "timeframe":          _val("timeframe"),
        "geographic_scope":   _val("geographic_scope"),
        "additional_context": "",
        "learning_notes":     _val("learning_notes"),
        "limitations_notes":  _val("limitations_notes"),
        "internal_review":    _val("internal_review", "Not reviewed") or "Not reviewed",
        "external_review":    _val("external_review", "No external review") or "No external review",
        "attached_filenames": [],
        "beneficiary_voice":  _val("beneficiary_voice"),
        "logframe_indicator":   _val("logframe_indicator"),
        "logframe_target":      _val("logframe_target"),
        "logframe_achievement": _val("logframe_achievement"),
        "reporting_start": "",
        "reporting_end":   "",
        "provenance_checklist": {
            "sampling_documented":     "Choose an option...",
            "double_counting_checked": "Choose an option...",
            "collection_tool_named":   "Choose an option...",
            "collector_independent":   "Choose an option...",
            "recall_period_ok":        "Choose an option...",
            "auditor_traceable":       "Choose an option...",
        },
        "qualitative_evidence": False,
        "qualitative_rigor_checklist": {
            "sourcing_documented":           _bool("qual_sourcing_documented"),
            "triangulated":                  _bool("qual_triangulated"),
            "bias_considered":               _bool("qual_bias_considered"),
            "beneficiary_voice_represented": _bool("qual_beneficiary_voice_represented"),
            "consent_ethics_addressed":      _bool("qual_consent_ethics_addressed"),
        },
        "attribution_contribution": "",
        "disaggregation_status": "",
        "review_status":     _SUBMISSION_STATUS_OPTIONS[0],
        "reviewer_name":     "",
        "reviewer_role":     "",
        "reviewer_date":     "",
        "reviewer_decision": "",
        "reviewer_notes":    "",
        "donor":          _val("donor"),
        "sector":         _val("sector"),
        "project_name":   _val("project_name"),
        "submission_type": "",
        "evidence": [{
            "type":        _val("evidence_type"),
            "description": _val("evidence_description"),
            "recency":     _val("evidence_date"),
            "verified_by": _val("verified_by"),
        }],
        "verification_status": "Imported — unverified",
        "import_source":    "csv",
        "import_profile":   profile_name,
        "import_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _validate_import_rows(submissions: list) -> list:
    """Return one issue-record per submission: missing required fields,
    type mismatches, and within-import duplicates. Annotation only — never
    blocks or alters the mapped values."""
    import pandas as pd

    required_targets = [(t, label) for t, label, req, _ in _CSV_IMPORT_FIELDS if req]
    bool_targets = [t for t, _, _, vt in _CSV_IMPORT_FIELDS if vt == "bool"]
    date_targets = [t for t, _, _, vt in _CSV_IMPORT_FIELDS if vt == "date"]

    issues = []
    seen = set()
    for i, sub in enumerate(submissions):
        row_issues = {"row": i + 1, "missing_required": [], "type_issues": [], "duplicate": False}

        ev0 = (sub.get("evidence") or [{}])[0]
        field_values = {
            "result_statement":    sub.get("result_statement", ""),
            "target_group":        sub.get("target_group", ""),
            "timeframe":           sub.get("timeframe", ""),
            "geographic_scope":    sub.get("geographic_scope", ""),
            "evidence_type":       ev0.get("type", ""),
            "evidence_description": ev0.get("description", ""),
            "evidence_date":       ev0.get("recency", ""),
        }
        for target_key, label in required_targets:
            if not str(field_values.get(target_key, "")).strip():
                row_issues["missing_required"].append(label)

        for target_key in bool_targets:
            qual = sub.get("qualitative_rigor_checklist", {})
            raw = ""  # already coerced to bool in _csv_row_to_submission; nothing to flag here
        for target_key in date_targets:
            raw = ev0.get("recency", "")
            if raw and pd.to_datetime(raw, errors="coerce") is pd.NaT:
                row_issues["type_issues"].append(f"{target_key}: '{raw}' is not a recognisable date")

        dup_key = (
            sub.get("result_statement", "").strip().lower(),
            sub.get("logframe_indicator", "").strip().lower(),
        )
        if dup_key in seen:
            row_issues["duplicate"] = True
        seen.add(dup_key)

        issues.append(row_issues)

    return issues


def render_csv_import_view():
    """Bulk CSV import: upload -> map columns -> preview/validate -> commit.
    Each confirmed row is scored via _evaluator.evaluate_submission() and
    persisted via save_all_files(), exactly like a manual submission."""
    import pandas as pd

    st.caption(_CSV_IMPORT_COPY["intro"])

    uploaded = st.file_uploader("Upload CSV", type=["csv"], key="csv_import_upload")
    if uploaded is None:
        return

    df, err = _parse_import_csv(uploaded)
    if err:
        st.error(err)
        return

    profiles = _load_import_profiles()
    profile_options = [_CSV_IMPORT_COPY["new_mapping"]] + list(profiles.keys())
    selected_profile = st.selectbox(_CSV_IMPORT_COPY["profile_label"], profile_options, key="csv_import_profile_select")
    saved_map = profiles.get(selected_profile, {}) if selected_profile != _CSV_IMPORT_COPY["new_mapping"] else {}

    column_options = [_CSV_IMPORT_COPY["not_mapped"]] + list(df.columns)
    column_map = {}
    for target_key, label, required, _ in _CSV_IMPORT_FIELDS:
        display_label = f"{label} *" if required else label
        default_col = saved_map.get(target_key, "")
        default_idx = column_options.index(default_col) if default_col in column_options else 0
        choice = st.selectbox(display_label, column_options, index=default_idx, key=f"csv_import_map_{target_key}")
        if choice != _CSV_IMPORT_COPY["not_mapped"]:
            column_map[target_key] = choice

    profile_name_input = st.text_input(
        _CSV_IMPORT_COPY["save_profile_label"],
        value=selected_profile if selected_profile != _CSV_IMPORT_COPY["new_mapping"] else "",
        key="csv_import_profile_name",
    )
    if st.button(_CSV_IMPORT_COPY["save_profile_button"], key="csv_import_save_profile_btn"):
        if profile_name_input.strip():
            profiles[profile_name_input.strip()] = column_map
            _save_import_profiles(profiles)
            st.success(_CSV_IMPORT_COPY["profile_saved"])

    submissions = [
        _csv_row_to_submission(row, column_map, profile_name_input.strip() or "unnamed")
        for row in df.to_dict(orient="records")
    ]
    issues = _validate_import_rows(submissions)

    n_rows = len(submissions)
    n_missing = sum(1 for iss in issues if iss["missing_required"])
    n_dupes = sum(1 for iss in issues if iss["duplicate"])

    st.markdown(f"##### {_CSV_IMPORT_COPY['preview_header']}")
    preview_df = df.copy()
    preview_df["Issues"] = [
        "; ".join(
            (["Missing: " + ", ".join(iss["missing_required"])] if iss["missing_required"] else [])
            + iss["type_issues"]
            + (["Duplicate"] if iss["duplicate"] else [])
        ) or "—"
        for iss in issues
    ]
    st.dataframe(preview_df, use_container_width=True)
    st.caption(_CSV_IMPORT_COPY["summary_template"].format(n=n_rows, m=n_missing, d=n_dupes))

    skip_incomplete = st.checkbox(_CSV_IMPORT_COPY["skip_incomplete"], value=False, key="csv_import_skip_incomplete")
    confirmed = st.checkbox(_CSV_IMPORT_COPY["confirm_checkbox"], value=False, key="csv_import_confirm")

    if st.button(_CSV_IMPORT_COPY["import_button"], disabled=not confirmed, key="csv_import_commit_btn"):
        to_import = [
            (sub, iss) for sub, iss in zip(submissions, issues)
            if not (skip_incomplete and iss["missing_required"])
        ]
        if not to_import:
            st.warning(_CSV_IMPORT_COPY["no_rows"])
        else:
            results = []
            for sub, _iss in to_import:
                ev = _evaluator.evaluate_submission(sub)
                save_all_files(sub, ev)
                results.append({
                    "indicator": sub.get("logframe_indicator") or sub.get("result_statement", "")[:60],
                    "confidence_score": ev.get("confidence_score", 0),
                    "clarity_score":    ev.get("clarity_score", 0),
                    "verdict":          ev.get("verdict", ""),
                })
            st.success(_CSV_IMPORT_COPY["import_done"].format(k=len(results)))
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Screen 3 — Portfolio / Framework Dashboard
# ---------------------------------------------------------------------------

def render_screen_3():
    import pandas as pd

    if st.button("← Back to Home", key="portfolio_back"):
        _go_to_screen(0)

    st.markdown("## 📊 Portfolio Dashboard")
    st.caption(
        "Upload your whole logframe (one row per indicator/result) to see which "
        "indicators and sub-scores are weakest across your portfolio."
    )

    st.download_button(
        "Download CSV template",
        data=_portfolio_template_csv(),
        file_name="impact_receipts_portfolio_template.csv",
        mime="text/csv",
        key="portfolio_template_dl",
    )
    st.caption(_PORTFOLIO_REVIEW_HINT)

    uploaded = st.file_uploader(
        "Upload your completed logframe (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        key="portfolio_upload",
    )

    if uploaded is not None:
        try:
            if uploaded.name.lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(uploaded)
            else:
                df = pd.read_csv(uploaded)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            df = None

        if df is not None:
            results_df, warnings = _evaluate_portfolio(df)
            st.session_state["portfolio_results"] = results_df
            st.session_state["portfolio_warnings"] = warnings

    results_df = st.session_state.get("portfolio_results")
    warnings = st.session_state.get("portfolio_warnings") or []

    for w in warnings:
        st.warning(w)

    if results_df is not None and not results_df.empty:
        dims = [d for d, _ in _PORTFOLIO_SUBSCORE_DIMENSIONS]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Indicators evaluated", len(results_df))
        with col2:
            st.metric("Avg Confidence", f"{results_df['confidence_score'].mean():.1f}/5.0")
        with col3:
            st.metric("Avg Clarity", f"{results_df['clarity_score'].mean():.1f}/5.0")

        weakest_dim = results_df[dims].mean().idxmin()
        weakest_dim_pct = results_df[dims].mean().min()
        st.markdown(
            f"**Systemic gap:** *{weakest_dim}* is your portfolio's weakest sub-score "
            f"on average ({weakest_dim_pct:.0f}% of target) — start here for the biggest "
            f"improvement across multiple indicators."
        )

        st.markdown("#### Heatmap — weakest indicators & sub-scores")
        st.caption(
            "For rows using a qualitative evidence type (case study, outcome harvesting, "
            "beneficiary narrative or testimony), the \"Measurement\" column reflects "
            "Sourcing & Triangulation (case/respondent selection, triangulation, and bias "
            "mitigation) instead of measurement precision."
        )
        if st.session_state.get("lite_mode", False):
            st.caption(
                "Heatmap hidden in low-bandwidth mode — see the results table "
                "below for the same data."
            )
        else:
            st.altair_chart(_portfolio_heatmap_chart(results_df), use_container_width=True, key="portfolio_heatmap")

        st.markdown("#### Results table")
        st.dataframe(
            results_df[["indicator_name", "confidence_score", "clarity_score", "verdict", "top_fix"]],
            use_container_width=True,
        )

        st.download_button(
            "Download results (CSV)",
            data=results_df.to_csv(index=False).encode("utf-8"),
            file_name="impact_receipts_portfolio_results.csv",
            mime="text/csv",
            key="portfolio_results_dl",
        )

        with st.expander("Report handoff details"):
            st.text_input("Prepared by (your name)", key="report_prepared_by")
            st.selectbox("Status", _REPORT_STATUS_OPTIONS, key="report_status")
            st.text_area("Notes for reviewer (optional)", key="report_notes", height=80)

        _timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _portfolio_summary_html = _build_portfolio_verification_summary_html(results_df, warnings, _timestamp)
        _portfolio_summary_pdf  = _html_to_pdf_bytes(_portfolio_summary_html)
        if _portfolio_summary_pdf:
            st.download_button(
                "📋 Download Verification Summary (PDF)",
                data=_portfolio_summary_pdf,
                file_name=f"portfolio_verification_summary_{_timestamp}.pdf",
                mime="application/pdf",
                key="portfolio_verification_summary_pdf_btn",
            )
        else:
            st.caption("PDF: install xhtml2pdf to enable one-click PDF download.")

    # place this here: end of render_screen_3(), after the existing portfolio block
    st.divider()
    with st.expander(_CSV_IMPORT_COPY["header"]):
        render_csv_import_view()

    st.divider()
    st.markdown(f"### {_TREND_COPY['header']}")
    st.caption(_TREND_COPY["intro"])
    render_trends_view(_load_trend_history())


def _build_html_report(submission: dict, evaluation: dict, timestamp: str, chart_id: str = "0") -> str:
    lite = st.session_state.get("lite_mode", False)
    conf_score = evaluation.get("confidence_score", 0)
    clar_score = evaluation.get("clarity_score", 0)
    conf_label = evaluation.get("confidence_label", "")
    clar_label = evaluation.get("clarity_label", "")
    verdict    = evaluation.get("verdict", "")
    fixes      = evaluation.get("fixes", [])
    conf_comp  = evaluation.get("confidence_components", {})
    clar_comp  = evaluation.get("clarity_components", {})
    filenames  = submission.get("attached_filenames", [])

    badge_colors = {
        "Strong":     ("#C8E6C9", "#1B5E20"),
        "Acceptable": ("#FFF9C4", "#F57F17"),
        "Weak":       ("#FFE0B2", "#E65100"),
        "High Risk":  ("#FFCDD2", "#B71C1C"),
    }
    _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"

    def badge(label, score, max_s):
        bg, fg = badge_colors.get(label, ("#F5F5F5", "#212121"))
        return (f"<div style='background:{bg};color:{fg};padding:10px 14px;"
                f"border-radius:8px;font-weight:700;font-size:0.9rem;margin-bottom:6px;{_pca}'>"
                f"{score}/{max_s} &nbsp; {label.upper()}</div>")

    def bar(value, max_v):
        pct = min(value / max_v * 100, 100) if max_v else 0
        fill_px = round(pct / 100 * 120)
        return (f"<div style='background:#E0E0E0;border-radius:4px;height:10px;width:120px;margin-bottom:10px;{_pca}'>"
                f"<div style='background:#1B5E20;width:{fill_px}px;height:10px;border-radius:4px;{_pca}'></div></div>")

    def row(label, score, max_v, tip=""):
        title = f' title="{tip}"' if tip else ""
        return (f"<tr><td{title} style='padding:6px 8px;font-size:0.88rem;'>{label}</td>"
                f"<td style='padding:6px 8px;font-family:monospace;'>{score}/{max_v}</td>"
                f"<td style='padding:6px 8px;width:120px;'>{bar(score, max_v)}</td></tr>")

    conf_fixes = [f for f in fixes if f.get("dimension") == "confidence"]
    clar_fixes = [f for f in fixes if f.get("dimension") == "clarity"]

    def fix_items(items):
        if not items:
            return ""
        return "".join(
            f"<li style='margin-bottom:6px;'>{f['message']} "
            f"<em style='color:#616161;'>({f['score_impact']})</em></li>"
            for f in items
        )

    verdict_colors = {
        "Strong KPI — well-positioned for submission": "#1B5E20",
        "Misleading KPI — sharpen the definition before submission": "#E65100",
        "Well-defined but weak evidence — strengthen the verification chain": "#F57F17",
        "High risk — strengthen both axes before relying on this result": "#B71C1C",
    }
    verdict_bg = verdict_colors.get(verdict, "#1B5E20")

    # Headline: is this good enough to submit?
    _diag_state, _ = get_diagnostic_state(
        conf_score, clar_score,
        evaluation.get("content_issues", []),
        submission.get("beneficiary_voice", ""),
    )
    _readiness_html = _readiness_banner_html(_diag_state)

    files_row = (f"<p><strong>Attached documents:</strong> {', '.join(filenames)}</p>"
                 if filenames else "")

    dl = conf_comp.get("direct_level", 0)
    vl = conf_comp.get("verify_level", 0)
    rl = conf_comp.get("recency_level", 0)
    ds = conf_comp.get("direct_score", 0)
    vs = conf_comp.get("verify_score", 0)
    rs = conf_comp.get("recency_score", 0)
    def_s  = clar_comp.get("definition_score", 0)
    meas_s = clar_comp.get("measurement_score", 0)
    integ  = clar_comp.get("integrity_score", 0)
    scope  = clar_comp.get("scope_score", 0)
    gov    = clar_comp.get("governance_score", 0)
    is_qual    = clar_comp.get("is_qualitative", False)
    def_label  = "Narrative Definition" if is_qual else "Definition"
    def_tip    = _CLARITY_TIPS["definition_qualitative"] if is_qual else _CLARITY_TIPS["definition"]
    meas_label = "Sourcing & Triangulation" if is_qual else "Measurement"
    meas_tip   = _CLARITY_TIPS["measurement_qualitative"] if is_qual else _CLARITY_TIPS["measurement"]

    # --- Overview chart for report ---
    _r_conf, _r_clar, _r_eth, _r_comp = _overview_score_values(evaluation)
    _overview_b64 = "" if lite else _build_overview_chart_b64(_r_conf, _r_clar, _r_eth, _r_comp)
    _overview_alt = (
        f"Overview chart of diagnostic scores out of 100: Confidence {_r_conf:.0f}, "
        f"Clarity {_r_clar:.0f}, Ethics {_r_eth:.0f}, Compliance {_r_comp:.0f}."
    )
    _overview_img = (f'<img src="data:image/png;base64,{_overview_b64}" '
                     f'alt="{_overview_alt}" style="max-width:420px;width:100%;display:block;margin:0 auto 12px;" />'
                     ) if _overview_b64 else ""
    _overview_legend = (
        "<ul style='font-size:0.8rem;color:#616161;max-width:560px;margin:0 auto 16px;padding-left:20px;'>"
        "<li><strong>Confidence</strong> — how directly the evidence supports the result, "
        "how independently it was verified, and how recent it is.</li>"
        "<li><strong>Clarity</strong> — how precisely the result is defined, measured, "
        "and bounded in scope, with a documented audit trail.</li>"
        "<li><strong>Ethics</strong> — completeness and integrity of the underlying data "
        "(missing data, audit trail, sample adequacy). Feeds into Clarity.</li>"
        "<li><strong>Compliance</strong> — consent, anonymisation, and data-protection-law status "
        "for any beneficiary data used as evidence. Feeds into Clarity.</li>"
        "<li style='margin-top:6px;'>Bar color shows the score band: "
        "<span style='color:#1B5E20;font-weight:700;'>green = 75&ndash;100 (strong)</span>, "
        "<span style='color:#8A6500;font-weight:700;'>gold = 50&ndash;74 (acceptable)</span>, "
        "<span style='color:#C62828;font-weight:700;'>red = below 50 (needs work)</span>.</li>"
        "</ul>"
    ) if _overview_b64 else ""

    # --- Interactive (vega-embed) sub-score charts for the downloadable report ---
    if lite:
        _conf_chart_div = ""
        _clar_chart_div = ""
        _charts_script = ""
    else:
        _conf_spec_json = _subscore_chart([
            (f"Directness (Level {dl}/5)", ds, 2.0, _DIRECTNESS_TIPS.get(dl, "")),
            (f"Verification (Level {vl}/5)", vs, 2.0, _VERIFICATION_TIPS.get(vl, "")),
            (f"Recency (Level {rl}/5)", rs, 1.0, _RECENCY_TIPS.get(rl, "")),
        ]).to_json()
        _clar_spec_json = _subscore_chart([
            (def_label, def_s, 1.25, def_tip),
            (meas_label, meas_s, 1.25, meas_tip),
            ("Integrity", integ, 1.0, _CLARITY_TIPS["integrity"]),
            ("Scope", scope, 0.75, _CLARITY_TIPS["scope"]),
            ("Governance", gov, 0.75, _CLARITY_TIPS["governance"]),
        ]).to_json()
        _conf_chart_div = f'<div id="conf-chart-{chart_id}" class="no-print" style="margin-top:10px;"></div>'
        _clar_chart_div = f'<div id="clar-chart-{chart_id}" class="no-print" style="margin-top:10px;"></div>'
        _charts_script = f"""
<script type="application/json" id="conf-spec-{chart_id}">{_conf_spec_json}</script>
<script type="application/json" id="clar-spec-{chart_id}">{_clar_spec_json}</script>
<script>
(function(){{
  function renderImpactReceiptsCharts_{chart_id}(){{
    if (!window.vegaEmbed) {{ setTimeout(renderImpactReceiptsCharts_{chart_id}, 200); return; }}
    var confSpec = JSON.parse(document.getElementById('conf-spec-{chart_id}').textContent);
    var clarSpec = JSON.parse(document.getElementById('clar-spec-{chart_id}').textContent);
    vegaEmbed('#conf-chart-{chart_id}', confSpec, {{actions: false}});
    vegaEmbed('#clar-chart-{chart_id}', clarSpec, {{actions: false}});
  }}
  renderImpactReceiptsCharts_{chart_id}();
}})();
</script>
"""

    _methodology_table = (
        "<div style='max-width:620px;margin:0 auto 24px;'>"
        "<p style='font-size:0.85rem;font-weight:700;color:#1B5E20;margin-bottom:6px;'>What this report checks:</p>"
        "<table style='width:100%;font-size:0.8rem;'>"
        "<tr><th>Check</th><th>Reflected in</th></tr>"
        "<tr><td>Logframe linkage — does your result tie to an approved indicator?</td>"
        "<td>Clarity &rarr; Measurement</td></tr>"
        "<tr><td>Evidence quality — direct, verified, recent, defensible?</td>"
        "<td>Confidence</td></tr>"
        "<tr><td>Beneficiary voice — were they part of the evidence?</td>"
        "<td>Confidence (bonus)</td></tr>"
        "<tr><td>Definition clarity — would two readers interpret it the same way?</td>"
        "<td>Clarity &rarr; Definition</td></tr>"
        "<tr><td>Submission completeness — is your package donor-ready?</td>"
        "<td>Advisory only — not scored</td></tr>"
        "</table>"
        "<p style='font-size:0.75rem;color:#9E9E9E;margin-top:6px;'>"
        "Confidence and Clarity are your two top-line scores. Ethics and Compliance are the "
        "Integrity and Governance sub-scores within Clarity, shown separately above so you can "
        "see what's driving your Clarity score — see definitions above.</p>"
        "<p style='font-size:0.85rem;font-weight:700;color:#1B5E20;margin:16px 0 6px;'>"
        "Donor framework crosswalk &mdash; how each sub-score maps to the standards your donor audits against:</p>"
        f"{build_donor_crosswalk_html(st.session_state.get('donor_framework', 'Generic'))}"
        "</div>"
    )
    _meta_donor  = submission.get("donor") or st.session_state.get("donor_selected", "Not specified")
    if _meta_donor == "(No donor specified)":
        _meta_donor = "Not specified"

    _meta_sector = submission.get("sector") or st.session_state.get("sector", "Not specified")
    if _meta_sector == "(No sector selected)":
        _meta_sector = "Not specified"

    _meta_rtype = submission.get("submission_type") or st.session_state.get("submission_type", "Not specified")
    if _meta_rtype == "Select submission type...":
        _meta_rtype = "Not specified"
    _meta_html = (
        "<table style='margin-bottom:20px;'><tbody>"
        f"<tr><td style='padding:5px 12px;font-weight:700;'>Donor</td><td style='padding:5px 12px;'>{_meta_donor}</td></tr>"
        f"<tr><td style='padding:5px 12px;font-weight:700;'>Sector</td><td style='padding:5px 12px;'>{_meta_sector}</td></tr>"
        f"<tr><td style='padding:5px 12px;font-weight:700;'>Report Type</td><td style='padding:5px 12px;'>{_meta_rtype}</td></tr>"
        "</tbody></table>"
    )
    # --- End radar ---

    fixes_html = ""
    if conf_fixes:
        fixes_html += ("<h3 style='color:#1B5E20;'>Strengthen your evidence (Confidence)</h3>"
                       f"<ul>{fix_items(conf_fixes)}</ul>")
    if clar_fixes:
        fixes_html += ("<h3 style='color:#1B5E20;'>Sharpen your definition (Clarity)</h3>"
                       f"<ul>{fix_items(clar_fixes)}</ul>")
    if not fixes:
        fixes_html = "<p style='color:#1B5E20;font-weight:700;'>No further fixes flagged by this tool's checks.</p>"

    # --- What Funders Want to Know (four-question summary) ---
    ladder   = evaluation.get("evidence_ladder", {})
    maturity = evaluation.get("indicator_maturity", {})
    fr       = evaluation.get("funder_readiness", {})
    ev_top      = (submission.get("evidence") or [{}])[0]
    ev_type_top = ev_top.get("type", "") or "Not specified"
    dominant    = ladder.get("dominant_tier")
    learn       = fr.get("learning", {})
    lim         = fr.get("limitations", {})

    q2_answer = f"Evidence type: <strong>{ev_type_top}</strong>"
    if dominant:
        q2_answer += f" &mdash; evidence base is mainly <strong>{dominant}</strong>-tier."
    q4_answer = ("Yes &mdash; the report describes what was learned and how the program adapted."
                  if learn.get("detected") else
                  "Not yet stated. Add a sentence on what you learned and changed as a result.")

    four_questions_html = f"""
<h2>What Funders Want to Know</h2>
<table>
  <tr><th>Question</th><th>Answer</th></tr>
  <tr><td><strong>1. What has changed?</strong></td>
      <td>{submission.get('result_statement', '-')}<br/>
          <span style="color:#616161;font-size:0.85rem;">Directness: Level {dl}/5 &middot; Definition: {def_s}/1.25</span></td></tr>
  <tr><td><strong>2. How do you know?</strong></td><td>{q2_answer}</td></tr>
  <tr><td><strong>3. How strong is the evidence?</strong></td>
      <td>Confidence: <strong>{conf_score}/5.0</strong> ({conf_label})</td></tr>
  <tr><td><strong>4. What did you learn?</strong></td><td>{q4_answer}</td></tr>
</table>
"""

    # --- Evidence Ladder ---
    ladder_html = ""
    if ladder:
        tier_descriptions = {
            "Basic": "Attendance, registration, logs, photos",
            "Moderate": "Follow-up surveys, testimonials",
            "Stronger": "Business/regulatory records, mentor verification, "
                        "baseline/endline, external evaluation, comparison groups",
        }
        counts = ladder.get("tier_counts", {})
        ladder_rows = "".join(
            f"<tr><td>{tier}{' &#128072;' if tier == dominant else ''}</td>"
            f"<td>{tier_descriptions[tier]}</td>"
            f"<td style='font-family:monospace;'>{counts.get(tier, 0)}</td></tr>"
            for tier in _evaluator.EVIDENCE_LADDER_TIERS
        )
        ladder_html = f"""
<h2>Evidence Ladder</h2>
<p style="color:#616161;font-size:0.85rem;">Rule-based check of the evidence sources you described — does this report rely mainly on Basic, Moderate, or Stronger evidence?</p>
<table><tr><th>Tier</th><th>Description</th><th>Sources detected</th></tr>{ladder_rows}</table>
<p>{ladder.get('suggestion', '')}</p>
"""

    # --- Indicator Maturity ---
    maturity_html = ""
    if maturity.get("flagged"):
        _maturity_row_parts = []
        for i, (level, wording) in enumerate(maturity["rows"]):
            tr_style = ' style="background:#FFF9E0;"' if i == 0 else ""
            level_label = f"\U0001F448 {level} — what you wrote" if i == 0 else level
            _maturity_row_parts.append(
                f"<tr{tr_style}><td>{level_label}</td><td>{wording}</td></tr>"
            )
        maturity_rows = "".join(_maturity_row_parts)
        _your_indicator = (submission.get("logframe_indicator", "") or "").strip() or "(not specified)"
        maturity_html = f"""
<h2>Indicator Maturity</h2>
<p style="color:#616161;font-size:0.85rem;">This indicator is written as a raw count. Funders increasingly expect indicators that show whether the result was sustained or verified.</p>
<p><strong>Your indicator (as written):</strong> {_your_indicator}</p>
<table><tr><th>Level</th><th>Example wording</th></tr>{maturity_rows}</table>
<p>Measurement score adjusted by <strong>{maturity['adjustment']}</strong> for this count-only indicator framing.</p>
"""

    # --- Funder Readiness flags ---
    lim_text = ("Limitations disclosed &mdash; the report states what the data can't confidently say."
                 if lim.get("detected") else
                 "No limitations disclosure detected. Consider adding a sentence on what this data "
                 "cannot confirm or cannot be generalized to.")
    learn_text = ("Learning &amp; adaptation stated &mdash; the report describes what was learned and changed."
                   if learn.get("detected") else
                   "No learning/adaptation statement detected. Consider adding what your organization "
                   "learned and how the program adapted as a result.")
    funder_readiness_html = f"""
<h2>Funder Readiness</h2>
<p style="color:#616161;font-size:0.85rem;">These checks do not affect your Confidence or Clarity scores.</p>
<ul>
  <li>{lim_text}</li>
  <li>{learn_text}</li>
</ul>
"""

    # --- Additional advisory flags (v3.4, score-neutral) ---
    attrib = submission.get("attribution_contribution", "Not specified")
    disagg = submission.get("disaggregation_status", "Not specified")
    advisory_html = ""
    if attrib != "Not specified" or disagg != "Not specified":
        advisory_items = ""
        if attrib != "Not specified":
            advisory_items += f"<li><strong>Attribution vs. contribution distinguished:</strong> {attrib}</li>"
        if disagg != "Not specified":
            advisory_items += f"<li><strong>Beneficiary data disaggregated (women, youth, PWD, rural):</strong> {disagg}</li>"
        advisory_html = f"""
<h2>Additional Advisory Flags</h2>
<p style="color:#616161;font-size:0.85rem;">Optional checklist answers — advisory only, no effect on your score.</p>
<ul>{advisory_items}</ul>
"""

    _vega_scripts = "" if lite else (
        '<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>'
    )
    _lite_note = (
        '<p style="color:#8A6500;font-size:0.85rem;">'
        'Low-bandwidth mode &mdash; simplified report (no embedded charts).</p>'
    ) if lite else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Impact-Receipts Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"/>
{_vega_scripts}
<style>
  body{{font-family:'Inter',sans-serif;color:#212121;max-width:860px;margin:40px auto;padding:0 24px;}}
  h1,h2,h3{{color:#1B5E20;}} h1{{font-size:1.6rem;}} h2{{font-size:1.2rem;border-bottom:1px solid #8A6500;padding-bottom:4px;margin-top:28px;}}
  table{{width:100%;border-collapse:collapse;margin-bottom:16px;}}
  td,th{{border:1px solid #E0E0E0;text-align:left;}}
  th{{background:#F5F5F5;padding:7px 8px;font-size:0.85rem;}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px;}}
  .footer{{color:#616161;font-style:italic;font-size:0.8rem;border-top:1px solid #E0E0E0;margin-top:32px;padding-top:12px;}}
  @media print{{
    body{{margin:20px;}}
    .no-print{{display:none;}}
    *{{-webkit-print-color-adjust:exact !important;print-color-adjust:exact !important;}}
  }}
</style>
</head>
<body>
<h1>Impact-Receipts Evaluation Report</h1>
<p style="color:#616161;font-size:0.88rem;">Generated: {timestamp}</p>
{_lite_note}
{_meta_html}
{_overview_img}
{_overview_legend}
{_methodology_table}
<h2>Result Statement</h2>
<p>{submission.get('result_statement', '-')}</p>
<p><strong>Target Group:</strong> {submission.get('target_group', '-')}<br/>
   <strong>Timeframe:</strong> {submission.get('timeframe', '-')}<br/>
   <strong>Geographic Scope:</strong> {submission.get('geographic_scope', '-')}</p>
{files_row}
{_readiness_html}
{four_questions_html}
<div style="background:{verdict_bg};color:white;border-radius:10px;padding:14px 20px;
     font-weight:700;text-align:center;margin:20px 0;font-size:1rem;
     -webkit-print-color-adjust:exact;print-color-adjust:exact;">
  {verdict}
</div>

<h2>Score Summary</h2>
<div class="grid">
  <div>
    <strong>Confidence Score</strong><br/>
    {badge(conf_label, conf_score, 5.0)}
    {bar(conf_score, 5.0)}
    <p style="color:#616161;font-size:0.85rem;">{evaluation.get('confidence_meaning','')}</p>
    <table>
      <tr><th>Component</th><th>Score</th><th>Bar</th></tr>
      {row(f"Directness (Level {dl}/5)", ds, 2.0, _DIRECTNESS_TIPS.get(dl,''))}
      {row(f"Verification (Level {vl}/5)", vs, 2.0, _VERIFICATION_TIPS.get(vl,''))}
      {row(f"Recency (Level {rl}/5)", rs, 1.0, _RECENCY_TIPS.get(rl,''))}
    </table>
    {_conf_chart_div}
  </div>
  <div>
    <strong>Clarity Score</strong><br/>
    {badge(clar_label, clar_score, 5.0)}
    {bar(clar_score, 5.0)}
    <p style="color:#616161;font-size:0.85rem;">{evaluation.get('clarity_meaning','')}</p>
    <table>
      <tr><th>Component</th><th>Score</th><th>Bar</th></tr>
      {row(def_label, def_s, 1.25, def_tip)}
      {row(meas_label, meas_s, 1.25, meas_tip)}
      {row("Integrity", integ, 1.0, _CLARITY_TIPS['integrity'])}
      {row("Scope", scope, 0.75, _CLARITY_TIPS['scope'])}
      {row("Governance", gov, 0.75, _CLARITY_TIPS['governance'])}
    </table>
    {_clar_chart_div}
  </div>
</div>
<p class="no-print" style="color:#9E9E9E;font-size:0.75rem;">Hover over the charts above for details (requires an internet connection to load the chart library).</p>
{_charts_script}
{ladder_html}
{maturity_html}
{funder_readiness_html}
{advisory_html}
<h2>What To Fix</h2>
{fixes_html}

<div class="footer">
  Evaluated using {METHODOLOGY_STACK}.<br/>
  Contact: <a href="mailto:info@impact-receipts.com">info@impact-receipts.com</a><br/>
  Tip: Print this page (Ctrl+P) and choose &ldquo;Save as PDF&rdquo; to get a PDF copy.
</div>
</body>
</html>"""


def _build_reviewer_signoff_section_html(review_info: dict) -> str:
    """Render the review-handoff fields (v3.6) as an HTML section to be
    appended to an existing report. Nothing is auto-filled — blanks are
    shown literally as 'Not provided'."""
    _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"
    status   = review_info.get("review_status", "") or _SUBMISSION_STATUS_OPTIONS[0]
    decision = review_info.get("reviewer_decision", "") or "Not yet decided"
    name     = review_info.get("reviewer_name", "") or "Not provided"
    role     = review_info.get("reviewer_role", "") or "Not provided"
    rdate    = review_info.get("reviewer_date", "") or "Not provided"
    notes    = review_info.get("reviewer_notes", "")

    bg, fg = _SUBMISSION_STATUS_COLORS.get(status, ("#F5F5F5", "#616161"))
    notes_html = (
        f"<div style='background:#FFF9C4;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:0.85rem;'>"
        f"<strong>Reviewer notes:</strong> {notes}</div>"
    ) if notes else ""

    return f"""
<h2>Review &amp; Sign-off</h2>
<div style="background:{bg};color:{fg};padding:6px 12px;border-radius:8px;font-weight:700;
     font-size:0.85rem;display:inline-block;margin-bottom:10px;{_pca}">
  STATUS: {status.upper()}
</div>
<p><strong>Decision:</strong> {decision}</p>
{notes_html}
<p style="margin-top:14px;">
  <strong>Reviewer:</strong> {name} &nbsp;&nbsp;
  <strong>Role:</strong> {role} &nbsp;&nbsp;
  <strong>Date:</strong> {rdate}
</p>
<p style="color:#9E9E9E;font-size:0.75rem;">
  No accounts or authentication are used — this reflects the reviewer information
  entered for this submission in the current session.
</p>
"""


def _build_review_summary_html(submission: dict, evaluation: dict, review_info: dict,
                                timestamp: str, chart_id: str = "0") -> str:
    """Review summary export (v3.6): reuses _build_html_report unchanged and
    appends a Review & Sign-off section capturing the submission, scores,
    gaps (via the existing report), and the reviewer's notes/decision."""
    base = _build_html_report(submission, evaluation, timestamp, chart_id=chart_id)
    section = _build_reviewer_signoff_section_html(review_info)
    return base.replace("</body>", section + "</body>")


def _build_review_summary_docx(submission: dict, evaluation: dict, review_info: dict, timestamp: str) -> bytes:
    """DOCX review summary (v3.6): reuses the existing donor-template DOCX
    table style for the submission/score/gaps content, then appends a
    Review & Sign-off table. Blanks are written literally as 'Not provided'."""
    import io

    conf_score = evaluation.get("confidence_score", 0)
    clar_score = evaluation.get("clarity_score", 0)
    conf_comp  = evaluation.get("confidence_components", {})
    clar_comp  = evaluation.get("clarity_components", {})
    fixes      = evaluation.get("fixes", [])

    doc = _docx.Document()
    doc.add_heading("Impact-Receipts Review Summary", level=0)
    doc.add_paragraph(f"Generated: {timestamp}")

    doc.add_heading("Result Statement", level=1)
    doc.add_paragraph(submission.get("result_statement", "") or "Not provided")
    table = doc.add_table(rows=0, cols=2)
    table.style = "Light Grid Accent 1"
    for label, value in [
        ("Target Group",     submission.get("target_group", "")),
        ("Timeframe",        submission.get("timeframe", "")),
        ("Geographic Scope", submission.get("geographic_scope", "")),
        ("Verdict",          evaluation.get("verdict", "")),
    ]:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = str(value) if value else "Not provided"

    doc.add_heading("Score Summary", level=1)
    score_table = doc.add_table(rows=0, cols=3)
    score_table.style = "Light Grid Accent 1"
    header = score_table.add_row().cells
    header[0].text, header[1].text, header[2].text = "Component", "Score", "Max"
    for label, value, max_val in [
        ("Confidence (overall)", conf_score, 5.0),
        ("Directness",   conf_comp.get("direct_score", "-"), 2.0),
        ("Verification", conf_comp.get("verify_score", "-"), 2.0),
        ("Recency",       conf_comp.get("recency_score", "-"), 1.0),
        ("Clarity (overall)", clar_score, 5.0),
        ("Definition",   clar_comp.get("definition_score", "-"), 1.25),
        ("Measurement",  clar_comp.get("measurement_score", "-"), 1.25),
        ("Integrity",    clar_comp.get("integrity_score", "-"), 1.0),
        ("Scope",        clar_comp.get("scope_score", "-"), 0.75),
        ("Governance",   clar_comp.get("governance_score", "-"), 0.75),
    ]:
        cells = score_table.add_row().cells
        cells[0].text = label
        cells[1].text = str(value)
        cells[2].text = str(max_val)

    doc.add_heading("Gaps / What To Fix", level=1)
    if fixes:
        for fix in fixes:
            doc.add_paragraph(f"{fix.get('message', '')} ({fix.get('score_impact', '')})", style="List Bullet")
    else:
        doc.add_paragraph("No further fixes flagged by this tool's checks.")

    doc.add_heading("Review & Sign-off", level=1)
    review_table = doc.add_table(rows=0, cols=2)
    review_table.style = "Light Grid Accent 1"
    for label, value in [
        ("Status",        review_info.get("review_status", "") or _SUBMISSION_STATUS_OPTIONS[0]),
        ("Decision",      review_info.get("reviewer_decision", "") or "Not yet decided"),
        ("Reviewer name", review_info.get("reviewer_name", "")),
        ("Reviewer role", review_info.get("reviewer_role", "")),
        ("Review date",   review_info.get("reviewer_date", "")),
    ]:
        cells = review_table.add_row().cells
        cells[0].text = label
        cells[1].text = str(value) if value else "Not provided"

    notes = review_info.get("reviewer_notes", "")
    if notes:
        doc.add_paragraph("Reviewer notes:")
        doc.add_paragraph(notes)

    doc.add_heading("About this export", level=1)
    doc.add_paragraph(
        f"Evaluated using {METHODOLOGY_STACK}. {_LIMITS_DISCLAIMER} "
        "This review summary has no user accounts or authentication — reviewer "
        "identity is free text entered for the current session."
    )

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_combined_html_report(submissions: list, evaluations: list, timestamp: str) -> str:
    parts = []
    for i, (sub, ev) in enumerate(zip(submissions, evaluations)):
        section = _build_html_report(sub, ev, timestamp, chart_id=str(i))
        # Strip outer HTML wrapper from all but the first, append just the body content
        if i == 0:
            parts.append(section)
        else:
            start = section.find("<h2>Result Statement</h2>")
            if start == -1:
                start = section.find("<h2 ")
            end   = section.rfind("</body>")
            insert_at = parts[0].rfind("</body>")
            divider = f"<hr style='margin:40px 0;border:2px solid #8A6500;'/><h2 style='color:#1B5E20;'>Result {i+1}</h2>"
            parts[0] = parts[0][:insert_at] + divider + section[start:end] + parts[0][insert_at:]
    return parts[0]


_VERIFICATION_SUMMARY_CSS = """
  body{font-family:'Inter',sans-serif;color:#212121;max-width:760px;margin:40px auto;padding:0 24px;}
  h1,h2,h3{color:#1B5E20;} h1{font-size:1.5rem;} h2{font-size:1.05rem;border-bottom:1px solid #8A6500;padding-bottom:4px;margin-top:22px;}
  table{width:100%;border-collapse:collapse;margin-bottom:14px;}
  td,th{border:1px solid #E0E0E0;text-align:left;padding:5px 8px;font-size:0.85rem;}
  th{background:#F5F5F5;}
  .signoff{margin-top:28px;border-top:1px solid #E0E0E0;padding-top:18px;font-size:0.9rem;}
  .signoff p{margin:6px 0;}
  .signoff .line{display:inline-block;min-width:220px;border-bottom:1px solid #212121;margin:0 6px;}
  .footer{color:#616161;font-style:italic;font-size:0.8rem;border-top:1px solid #E0E0E0;margin-top:28px;padding-top:12px;}
  @media print{ body{margin:20px;} *{-webkit-print-color-adjust:exact !important;print-color-adjust:exact !important;} }
"""

_VERIFICATION_SUMMARY_BADGE_COLORS = {
    "Strong":     ("#C8E6C9", "#1B5E20"),
    "Acceptable": ("#FFF9C4", "#F57F17"),
    "Weak":       ("#FFE0B2", "#E65100"),
    "High Risk":  ("#FFCDD2", "#B71C1C"),
}

_VERIFICATION_SUMMARY_VERDICT_COLORS = {
    "Strong KPI — well-positioned for submission": "#1B5E20",
    "Misleading KPI — sharpen the definition before submission": "#E65100",
    "Well-defined but weak evidence — strengthen the verification chain": "#F57F17",
    "High risk — strengthen both axes before relying on this result": "#B71C1C",
}

_REPORT_STATUS_OPTIONS = [
    "Draft – pending review",
    "Submitted for review",
    "Reviewed – changes requested",
    "Approved – ready to submit",
]

_REPORT_STATUS_COLORS = {
    "Draft – pending review":        ("#F5F5F5", "#616161"),
    "Submitted for review":           ("#FFF9C4", "#F57F17"),
    "Reviewed – changes requested":   ("#FFE0B2", "#E65100"),
    "Approved – ready to submit":     ("#C8E6C9", "#1B5E20"),
}


def _verification_summary_badge(label: str, score: float, max_s: float) -> str:
    bg, fg = _VERIFICATION_SUMMARY_BADGE_COLORS.get(label, ("#F5F5F5", "#212121"))
    _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"
    return (f"<div style='background:{bg};color:{fg};padding:8px 12px;"
            f"border-radius:8px;font-weight:700;font-size:0.85rem;display:inline-block;{_pca}'>"
            f"{score}/{max_s} &nbsp; {label.upper()}</div>")


def _verification_summary_signoff(prepared_by: str = "", status: str = "", notes: str = "", timestamp: str = "") -> str:
    bg, fg = _REPORT_STATUS_COLORS.get(status, ("#F5F5F5", "#212121"))
    status_html = (
        f"<div style='background:{bg};color:{fg};padding:6px 12px;border-radius:8px;"
        f"font-weight:700;font-size:0.85rem;display:inline-block;margin-bottom:10px;"
        f"-webkit-print-color-adjust:exact;print-color-adjust:exact;'>STATUS: {status.upper()}</div>"
    ) if status else ""
    notes_html = (
        f"<div style='background:#FFF9C4;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:0.85rem;'>"
        f"<strong>Notes for reviewer:</strong> {notes}</div>"
    ) if notes else ""
    prepared_line = prepared_by or "&nbsp;"
    return (
        f"{status_html}{notes_html}"
        "<div class='signoff'>"
        f"<p><strong>Prepared by:</strong> {prepared_line} &nbsp;&nbsp; <strong>Date:</strong> {timestamp}</p>"
        "<p><strong>Reviewed by:</strong> <span class='line'>&nbsp;</span> &nbsp;&nbsp; "
        "<strong>Date:</strong> <span class='line'>&nbsp;</span></p>"
        "<p><strong>Comments:</strong> <span class='line' style='min-width:400px;'>&nbsp;</span></p>"
        "<p><strong>Approved by:</strong> <span class='line'>&nbsp;</span> &nbsp;&nbsp; "
        "<strong>Date:</strong> <span class='line'>&nbsp;</span></p>"
        "</div>"
    )


def _build_verification_summary_html(submissions: list, evaluations: list, timestamp: str) -> str:
    """Build a short, printable per-result gap report for attaching to a submission."""
    _prepared_by = st.session_state.get("report_prepared_by", "")
    _status      = st.session_state.get("report_status", "")
    _notes       = st.session_state.get("report_notes", "")
    sections = []
    for i, (submission, evaluation) in enumerate(zip(submissions, evaluations)):
        conf_score = evaluation.get("confidence_score", 0)
        clar_score = evaluation.get("clarity_score", 0)
        conf_label = evaluation.get("confidence_label", "")
        clar_label = evaluation.get("clarity_label", "")
        verdict    = evaluation.get("verdict", "")
        fixes      = evaluation.get("fixes", [])
        conf_comp  = evaluation.get("confidence_components", {})
        clar_comp  = evaluation.get("clarity_components", {})
        verdict_bg = _VERIFICATION_SUMMARY_VERDICT_COLORS.get(verdict, "#1B5E20")
        is_qual    = clar_comp.get("is_qualitative", False)
        def_label  = "Narrative Definition" if is_qual else "Definition"
        meas_label = "Sourcing & Triangulation" if is_qual else "Measurement"

        sub_rows = "".join(
            f"<tr><td>{dim}</td><td style='font-family:monospace;'>{score}/{max_v}</td></tr>"
            for dim, score, max_v in [
                ("Directness",   conf_comp.get("direct_score", 0), 2.0),
                ("Verification", conf_comp.get("verify_score", 0), 2.0),
                ("Recency",      conf_comp.get("recency_score", 0), 1.0),
                (def_label,      clar_comp.get("definition_score", 0), 1.25),
                (meas_label,     clar_comp.get("measurement_score", 0), 1.25),
                ("Integrity",    clar_comp.get("integrity_score", 0), 1.0),
                ("Scope",        clar_comp.get("scope_score", 0), 0.75),
                ("Governance",   clar_comp.get("governance_score", 0), 0.75),
            ]
        )

        if fixes:
            fixes_html = "<ul>" + "".join(
                f"<li>{f['message']} <em style='color:#616161;'>({f['score_impact']})</em></li>"
                for f in fixes
            ) + "</ul>"
        else:
            fixes_html = "<p style='color:#1B5E20;font-weight:700;'>No further gaps flagged by this tool's checks.</p>"

        heading = "<h1>Verification Summary</h1>" if i == 0 else \
                  f"<hr style='margin:36px 0;border:2px solid #8A6500;'/><h1>Result {i + 1}</h1>"

        sections.append(f"""
{heading}
<p style="color:#616161;font-size:0.85rem;">Generated: {timestamp}</p>
<h2>Result Statement</h2>
<p>{submission.get('result_statement', '-')}</p>
<p><strong>Logframe Indicator:</strong> {submission.get('logframe_indicator', '-') or '-'}<br/>
   <strong>Target Group:</strong> {submission.get('target_group', '-')}<br/>
   <strong>Timeframe:</strong> {submission.get('timeframe', '-')}<br/>
   <strong>Geographic Scope:</strong> {submission.get('geographic_scope', '-')}</p>

<div style="background:{verdict_bg};color:white;border-radius:10px;padding:12px 18px;
     font-weight:700;text-align:center;margin:16px 0;font-size:0.95rem;
     -webkit-print-color-adjust:exact;print-color-adjust:exact;">
  {verdict}
</div>

<h2>Scores</h2>
<p>
  {_verification_summary_badge(conf_label, conf_score, 5.0)}
  &nbsp; {_verification_summary_badge(clar_label, clar_score, 5.0)}
</p>
<table><tr><th>Sub-score</th><th>Score</th></tr>{sub_rows}</table>

<h2>Gaps to Address</h2>
{fixes_html}
""")

    sections.append(f"""
<h2>Donor Framework Crosswalk</h2>
{build_donor_crosswalk_html(st.session_state.get('donor_framework', 'Generic'))}
<p style="color:#616161;font-size:0.8rem;">{_LIMITS_DISCLAIMER}</p>
{_verification_summary_signoff(_prepared_by, _status, _notes, timestamp)}
<div class="footer">
  Evaluated using {METHODOLOGY_STACK}.<br/>
  Contact: <a href="mailto:info@impact-receipts.com">info@impact-receipts.com</a>
</div>
""")

    body = "".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Verification Summary</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"/>
<style>{_VERIFICATION_SUMMARY_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


def _build_portfolio_verification_summary_html(results_df, warnings: list, timestamp: str) -> str:
    """Build a short, printable portfolio-level gap report for a reporting cycle."""
    _prepared_by = st.session_state.get("report_prepared_by", "")
    _status      = st.session_state.get("report_status", "")
    _notes       = st.session_state.get("report_notes", "")
    dims = [d for d, _ in _PORTFOLIO_SUBSCORE_DIMENSIONS]
    n = len(results_df)
    avg_conf = results_df["confidence_score"].mean() if n else 0
    avg_clar = results_df["clarity_score"].mean() if n else 0

    if n and dims:
        weakest_dim = results_df[dims].mean().idxmin()
        weakest_pct = results_df[dims].mean().min()
        systemic_gap_html = (
            f"<p><strong>Systemic gap:</strong> <em>{weakest_dim}</em> is this portfolio's "
            f"weakest sub-score on average ({weakest_pct:.0f}% of target) — start here for "
            f"the biggest improvement across multiple indicators.</p>"
        )
    else:
        systemic_gap_html = ""

    table_rows = "".join(
        f"<tr><td>{r['indicator_name']}</td><td>{r['logframe_indicator'] or '-'}</td>"
        f"<td style='font-family:monospace;'>{r['confidence_score']}/5.0</td>"
        f"<td style='font-family:monospace;'>{r['clarity_score']}/5.0</td>"
        f"<td>{r['verdict']}</td><td>{r['top_fix'] or '-'}</td></tr>"
        for _, r in results_df.iterrows()
    )

    warnings_html = ""
    if warnings:
        warnings_html = (
            "<h2>Rows Skipped</h2><ul>"
            + "".join(f"<li>{w}</li>" for w in warnings)
            + "</ul>"
        )

    body = f"""
<h1>Portfolio Verification Summary</h1>
<p style="color:#616161;font-size:0.85rem;">Generated: {timestamp}</p>
<p><strong>Indicators evaluated:</strong> {n}<br/>
   <strong>Average Confidence:</strong> {avg_conf:.1f}/5.0<br/>
   <strong>Average Clarity:</strong> {avg_clar:.1f}/5.0</p>
{systemic_gap_html}

<h2>Results by Indicator</h2>
<table>
  <tr><th>Indicator</th><th>Logframe Reference</th><th>Confidence</th><th>Clarity</th><th>Verdict</th><th>Top Fix</th></tr>
  {table_rows}
</table>
{warnings_html}

<h2>Donor Framework Crosswalk</h2>
{build_donor_crosswalk_html(st.session_state.get('donor_framework', 'Generic'))}
<p style="color:#616161;font-size:0.8rem;">{_LIMITS_DISCLAIMER}</p>
{_verification_summary_signoff(_prepared_by, _status, _notes, timestamp)}
<div class="footer">
  Evaluated using {METHODOLOGY_STACK}.<br/>
  Contact: <a href="mailto:info@impact-receipts.com">info@impact-receipts.com</a>
</div>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Portfolio Verification Summary</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"/>
<style>{_VERIFICATION_SUMMARY_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Impact-Receipts",
        page_icon="",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    st.markdown(CSS, unsafe_allow_html=True)
    inject_matchday_css()
    _init_session_state()

    with st.sidebar:
        st.toggle(
            "⚡ Low-bandwidth mode",
            key="lite_mode",
            help="Fewer interactive charts and a smaller, self-contained "
                 "downloadable report — for offices with slow or unreliable "
                 "internet.",
        )

    # --- Paystack payment callback handler ---
    # Paystack always appends "?trxref=...&reference=..." to the callback_url
    # on redirect, even if it already contains a "?" — so the callback_url is
    # kept bare (see utils/paystack.initialize_payment) and the paying user's
    # email is recovered from Paystack's own verify response below, rather
    # than round-tripped through our own query-string params.
    _paystack_ref = (
        st.query_params.get("paystack_ref", "")
        or st.query_params.get("reference", "")
        or st.query_params.get("trxref", "")
    )
    if _paystack_ref:
        _pay_result = verify_payment(_paystack_ref)
        if _pay_result.get("status") == "success":
            _pay_email = (_pay_result.get("email") or st.session_state.get("user_email") or "").strip().lower()
            if _pay_email:
                _days = 30 if _pay_result.get("plan") == "monthly" else 1
                upsert_user(_pay_email)
                mark_paid(_pay_email, days=_days)
                st.session_state["user_email"] = _pay_email
                st.session_state["is_paid"] = True
                st.session_state.pop("_pay_once_url", None)
                st.session_state.pop("_pay_monthly_url", None)
                st.session_state["screen"] = 1
                st.session_state["current_tab"] = 0
                st.session_state["entry_mode"] = "⚡ Instant Report Check"
                st.session_state["_payment_success"] = True
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()
            else:
                # Paid, but no email on either side yet — defer until the
                # user signs in via the email gate, which completes this.
                st.session_state["pending_paystack_ref"] = _paystack_ref
                try:
                    st.query_params.clear()
                except Exception:
                    pass
        elif _pay_result.get("status") == "failed":
            st.warning("Payment was not completed. Please try again.")
            try:
                st.query_params.clear()
            except Exception:
                pass
    # --- End Paystack handler ---

    screen = st.session_state["screen"]
    {0: render_screen_0, 1: render_screen_1, 2: render_screen_2, 3: render_screen_3}.get(
        screen, render_screen_0
    )()


if __name__ == "__main__":
    main()
