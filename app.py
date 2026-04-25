"""
app.py — Impact-Receipts: Pre-submission confidence check for MEL teams.

Run with:  streamlit run app.py

Three-screen flow driven by st.session_state["screen"] (0-2):
  0  Landing & Onboarding
  1  Reported Result Submission
  2  Confidence Snapshot & Next Steps

Evaluation logic is fully local — see evaluator.py.
No API calls. All data stays on device.
"""

import json
import os
import re
import urllib.parse
from datetime import datetime, date

import streamlit as st
import evaluator as _evaluator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVIDENCE_TYPES = [
    "Attendance sheets / participant registers",
    "Raw datasets or survey exports",
    "Partner verification letters",
    "Photos with metadata",
    "Tracer survey results",
    "Financial records",
    "Third-party audits",
    "Other",
]

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

SECTOR_EVIDENCE_PLACEHOLDERS = {
    "WASH": "e.g., Borehole functionality reports from 25 sites + water quality test results from district lab",
    "Health": "e.g., Patient records from 3 health facilities + immunization registers signed by district health officer",
    "Youth Employment": "e.g., Signed employment contracts + 3-month and 6-month tracer surveys",
    "Education": "e.g., Enrollment registers + standardized test results before/after intervention",
    "Agriculture / Livelihoods": "e.g., Distribution lists with farmer signatures + harvest records from cooperative",
    "Climate Resilience": "e.g., Meteorological records + household surveys on adaptive practices adopted",
    "Governance": "e.g., Meeting minutes signed by officials + citizen satisfaction survey data",
}
_DEFAULT_EVIDENCE_PLACEHOLDER = (
    "e.g., Signed attendance sheets from 12 training sessions across 3 districts, "
    "verified by District Agriculture Officer."
)

_DIAGNOSTIC_BADGE = {
    "STRONG":             {"bg": "#1B5E20", "text": "#FFFFFF", "subtitle": "Ready for submission"},
    "MISLEADING":         {"bg": "#B8860B", "text": "#FFFFFF", "subtitle": "Sharpen the definition"},
    "UNDEREVIDENCED":     {"bg": "#B8860B", "text": "#FFFFFF", "subtitle": "Strengthen the evidence"},
    "NEEDS REFINEMENT":   {"bg": "#FFF9C4", "text": "#F57F17", "subtitle": "Specific gaps to address"},
    "FUNDAMENTALLY WEAK": {"bg": "#B71C1C", "text": "#FFFFFF", "subtitle": "Redefine the claim AND gather new evidence"},
    "INCOMPLETE":         {"bg": "#9E9E9E", "text": "#FFFFFF", "subtitle": "Fill remaining fields"},
}

INTERNAL_REVIEW_OPTIONS = [
    "Reviewed by MEL Officer",
    "Collected only (no review)",
    "Not reviewed",
    "Other",
]

EXTERNAL_REVIEW_OPTIONS = [
    "Verified by independent third party",
    "External partner review",
    "No external review",
    "Other",
]

# ---------------------------------------------------------------------------
# CSS — injected once at app load
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=JetBrains+Mono:wght@400&display=swap');

:root {
  --brand-green: #1B5E20;
  --gold:        #B8860B;
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
  border-color: #B8860B !important;
  color: #B8860B !important;
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
  border-bottom: 1px solid #B8860B;
  margin-bottom: 20px;
}
.hero-block h1 {
  font-size: 1.85rem;
  line-height: 1.25;
  margin-bottom: 8px;
}
.hero-tagline {
  font-style: italic;
  color: #B8860B;
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
  background: #B8860B;
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
  color: #B8860B;
  font-size: 0.82rem;
  text-align: center;
  padding: 12px 0 4px 0;
  border-top: 1px solid rgba(184,134,11,0.2);
  margin-top: 24px;
}

/* GTM conversion hook card */
.gtm-card {
  border: 1px solid #B8860B;
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
  border: 2px solid #B8860B;
  color: #B8860B !important;
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
  border-left: 4px solid #B8860B;
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
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


_BASE_FORM_KEYS = [
    "result_statement", "target_group", "timeframe", "geographic_scope",
    "evidence_description", "evidence_type", "evidence_type_other",
    "internal_review", "internal_review_other",
    "external_review", "external_review_other",
    "verifier", "sector",
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
              "evaluation", "submission_snapshot", "error_message", "active_slots_run"]:
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
    os.makedirs("inputs", exist_ok=True)
    with open(_DRAFT_PATH, "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)


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


def _clear_draft():
    if os.path.exists(_DRAFT_PATH):
        os.remove(_DRAFT_PATH)


# ---------------------------------------------------------------------------
# Diagnostic state classifier
# ---------------------------------------------------------------------------

def get_diagnostic_state(confidence: float, clarity: float) -> tuple:
    if confidence >= 4.0 and clarity >= 4.0:
        return "STRONG", "Ready for submission"
    if confidence >= 3.5 and clarity < 3.0:
        return "MISLEADING", "Strong evidence but unclear claim — sharpen the definition"
    if confidence < 3.0 and clarity >= 3.5:
        return "UNDEREVIDENCED", "Clear claim but weak evidence — strengthen the verification chain"
    if confidence < 2.5 and clarity < 2.5:
        return "FUNDAMENTALLY WEAK", "Both axes show major gaps — redefine AND gather new evidence before submission"
    if confidence >= 3.0 and clarity >= 3.0:
        return "NEEDS REFINEMENT", "Acceptable on both axes — specific gaps to address before submission"
    return "INCOMPLETE", "Some inputs missing — fill in remaining fields for a full assessment"


# ---------------------------------------------------------------------------
# Tutorial renderer
# ---------------------------------------------------------------------------

_TUTORIAL_COPY = {
    0: {
        "title": "👋 Welcome to Impact-Receipts.",
        "body": (
            "This tool stress-tests your reported results in 10 minutes.\n\n"
            "Here's how it works:\n"
            "1. Add your result statement\n"
            "2. Describe your supporting evidence\n"
            "3. Get a confidence label + specific fixes"
        ),
    },
    1: {
        "title": "📝 Each field below contributes to your score.",
        "body": (
            "Watch the **Live Score Preview** panel update as you type.\n"
            "We'll show you exactly which inputs boost which scores."
        ),
    },
    2: {
        "title": "🎯 Your result is now scored on two axes:",
        "body": (
            "• **Confidence:** How much we should trust the evidence\n"
            "• **Clarity:** How clearly the result is defined\n\n"
            "Both must be **Strong (≥4.0)** to be ready for submission.\n\n"
            "The **What to Fix** section tells you exactly how to improve."
        ),
    },
}


def _render_tutorial(step: int):
    if st.session_state.get("has_seen_tutorial") or st.session_state.get("tutorial_step", 0) > step:
        return
    copy = _TUTORIAL_COPY.get(step)
    if not copy:
        return
    with st.info(f"**{copy['title']}**\n\n{copy['body']}"):
        pass
    col_got, col_skip = st.columns([1, 1])
    with col_got:
        if st.button("Got it →", key=f"tutorial_got_{step}"):
            if step == 2:
                st.session_state["has_seen_tutorial"] = True
                st.session_state["tutorial_step"] = 3
            else:
                st.session_state["tutorial_step"] = step + 1
            st.rerun()
    with col_skip:
        if st.button("Skip tutorial", key=f"tutorial_skip_{step}"):
            st.session_state["has_seen_tutorial"] = True
            st.session_state["tutorial_step"] = 3
            st.rerun()


# ---------------------------------------------------------------------------
# Live score preview
# ---------------------------------------------------------------------------

def _render_live_score_preview(slot: int = 1):
    sub = _build_submission_from_session(slot)
    try:
        ev = _evaluator.evaluate_submission(sub)
    except Exception:
        st.caption("Fill in the form fields above to see your live score.")
        return

    conf_score = ev.get("confidence_score", 0)
    clar_score = ev.get("clarity_score", 0)
    conf_label = ev.get("confidence_label", "—")
    clar_label = ev.get("clarity_label", "—")
    conf_comp  = ev.get("confidence_components", {})
    clar_comp  = ev.get("clarity_components", {})

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Confidence", f"{conf_score}/5.0", delta=conf_label, delta_color="off")
    with c2:
        st.metric("Clarity", f"{clar_score}/5.0", delta=clar_label, delta_color="off")

    st.markdown("**Score breakdown:**")
    bd1, bd2 = st.columns(2)
    with bd1:
        ds = conf_comp.get("direct_score", 0)
        vs = conf_comp.get("verify_score", 0)
        rs = conf_comp.get("recency_score", 0)
        st.caption(f"Directness:    {ds}/2.0")
        st.caption(f"Verification:  {vs}/2.0")
        st.caption(f"Recency:       {rs}/1.0")
    with bd2:
        def_s  = clar_comp.get("definition_score", 0)
        meas_s = clar_comp.get("measurement_score", 0)
        integ  = clar_comp.get("integrity_score", 0)
        scope  = clar_comp.get("scope_score", 0)
        gov    = clar_comp.get("governance_score", 0)
        st.caption(f"Definition:    {def_s}/1.25")
        st.caption(f"Measurement:   {meas_s}/1.25")
        st.caption(f"Integrity:     {integ}/1.0")
        st.caption(f"Scope:         {scope}/0.75")
        st.caption(f"Governance:    {gov}/0.75")

    state, state_sub = get_diagnostic_state(conf_score, clar_score)
    st.caption(f"Current status: **{state}** — {state_sub}")


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
        raw_files = st.session_state.get(f"uploaded_files_widget{s}") or []
        slot_dict["uploaded_filenames"] = [f.name for f in raw_files if hasattr(f, "name")]
        slots_data.append(slot_dict)

    payload = {
        "timestamp": timestamp,
        "session_id": f"ir-{timestamp}",
        "active_slots": active,
        "slots": slots_data,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _load_from_inputs_json(data: dict):
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
                st.session_state[f"{k}{s}"] = slot_dict[k]
        raw_date = slot_dict.get("evidence_date", "")
        if raw_date:
            try:
                st.session_state[f"evidence_date{s}"] = date.fromisoformat(raw_date)
            except (ValueError, TypeError):
                pass
        st.session_state[f"draft_uploaded_filenames{s}"] = slot_dict.get("uploaded_filenames", [])

    ts = data.get("timestamp", "unknown")
    st.success(f"Loaded inputs from {ts}. Adjust and re-run.")
    st.session_state["screen"] = 1
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

    return {
        "result_statement":   st.session_state.get(f"result_statement{s}", ""),
        "target_group":       st.session_state.get(f"target_group{s}", ""),
        "timeframe":          st.session_state.get(f"timeframe{s}", ""),
        "geographic_scope":   st.session_state.get(f"geographic_scope{s}", ""),
        "additional_context": "",
        "internal_review":    int_rev,
        "external_review":    ext_rev,
        "attached_filenames": st.session_state.get(f"uploaded_files{s}", []),
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
        (f"internal_review{s}", INTERNAL_REVIEW_OPTIONS[0]),
        (f"external_review{s}", EXTERNAL_REVIEW_OPTIONS[0]),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    st.text_area(
        "Result statement",
        key=f"result_statement{s}",
        placeholder=(
            "e.g., Trained 500 smallholder farmers in climate-smart agriculture across 3 "
            "districts in Northern Ghana between January and June 2025"
        ),
        height=100,
        help="What did your project achieve? Include the verb (trained, distributed, reached), the number, the population, and the timeframe.",
    )

    st.text_input(
        "Target group", key=f"target_group{s}",
        placeholder="e.g., Smallholder farmers, 18-60 years old, three districts in Northern Region",
        help="Who specifically? Age, gender, role, geography. Avoid 'beneficiaries' alone.",
    )

    st.text_input(
        "Timeframe", key=f"timeframe{s}",
        placeholder="e.g., January - June 2025",
        help="Specific dates or quarters. 'January–June 2025' is stronger than 'In 2025'.",
    )

    st.text_input(
        "Geographic scope", key=f"geographic_scope{s}",
        placeholder="e.g., Tamale, Yendi, Savelugu districts",
        help="Districts, regions, or specific sites. 'Volta Region' beats 'rural areas'.",
    )

    sector = st.session_state.get("sector", SECTOR_OPTIONS[0])
    ev_placeholder = SECTOR_EVIDENCE_PLACEHOLDERS.get(sector, _DEFAULT_EVIDENCE_PLACEHOLDER)
    st.text_area(
        "Describe your supporting evidence", key=f"evidence_description{s}",
        placeholder=ev_placeholder,
        height=120,
        help="Describe the actual document or data: who collected it, how, and what's in it.",
    )

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

    st.text_input(
        "Who verified this?", key=f"verifier{s}",
        placeholder="e.g., District Agriculture Officer, partner org M&E lead, external evaluator",
        help="The person or organization that confirmed the data is accurate.",
    )

    st.date_input(
        "When was this evidence collected?", key=f"evidence_date{s}",
        help="When was the data collected? Use the most recent date if multiple sources.",
    )
    _ed = st.session_state.get(f"evidence_date{s}")
    _timeframe = st.session_state.get(f"timeframe{s}", "")
    if _ed:
        _rl = _evaluator.get_recency_level(_format_date(_ed), _timeframe)
        _rs = round((_rl / 5) * 1.0, 1)
        st.caption(f"Recency score: **{_rs}/1.0**")

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

def render_screen_0():
    st.markdown(
        """
        <div class="hero-block">
          <h1>Know which reported results are strong, weak, or need fixing — before submission.</h1>
          <p class="hero-tagline">Stress-test a result before you submit it.</p>
          <p class="hero-sub">
            Impact-Receipts helps Monitoring, Evaluation &amp; Learning (MEL) professionals
            and reporting teams of developmental projects check reported results
            before submission, review the evidence behind them, and see what needs fixing
            before the report goes to donors, leadership, or partners.
          </p>
          <p class="brand-promise">We help you submit with confidence. Not by judging your work,
          but by showing you exactly where it&rsquo;s strong and where it needs strengthening &mdash;
          before anyone else sees it.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_tutorial(0)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Review Results Before Submission", type="primary", use_container_width=True):
            if not st.session_state.get("has_seen_tutorial"):
                st.session_state["tutorial_step"] = 1
            _go_to_screen(1, reset=True)
    with col_b:
        if st.button("Run My Confidence Check", use_container_width=True):
            if not st.session_state.get("has_seen_tutorial"):
                st.session_state["tutorial_step"] = 1
            _go_to_screen(1, reset=True)

    with st.expander("📁 Resume a previous session"):
        uploaded_json = st.file_uploader(
            "Upload a previously saved inputs JSON",
            type=["json"],
            key="resume_json_upload",
        )
        if uploaded_json is not None:
            try:
                data = json.loads(uploaded_json.read())
                _load_from_inputs_json(data)
            except Exception as exc:
                st.error(f"Could not read the file: {exc}")

    st.markdown(
        """
        <div class="is-not-grid">
          <div class="is-col" style="color: #1B5E20 !important;">
            <h4>&#10003; What this IS</h4>
            <ul style="color: #1B5E20 !important;">
              <li style="color: #1B5E20 !important;">A quick confidence check for reported results before submission</li>
              <li style="color: #1B5E20 !important;">A transparent guide that shows what to fix and why</li>
              <li style="color: #1B5E20 !important;">Fully local — runs on your device, no data sent anywhere</li>
              <li style="color: #1B5E20 !important;">Free and instant — no login, no API key</li>
            </ul>
          </div>
          <div class="isnot-col" style="color: #C62828 !important;">
            <h4 style="color: #C62828 !important;">&#10007; What this is NOT</h4>
            <ul style="color: #C62828 !important;">
              <li style="color: #C62828 !important;">A full reporting system, database, or tool</li>
              <li style="color: #C62828 !important;">A replacement for your M&amp;E/MEL framework</li>
              <li style="color: #C62828 !important;">An AI that invents or assumes missing data</li>
              <li style="color: #C62828 !important;">A gatekeeper that decides who passes or fails</li>
            </ul>
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
          Built by a MEL practitioner in Accra who got tired of submitting results without a confidence check.
        </p>
        """,
        unsafe_allow_html=True,
    )

    st.caption("Your data stays on your device. Nothing is stored or shared.")

    st.markdown(
        """
        <div class="gtm-card">
          <p><strong>Want a deeper check?</strong></p>
          <p class="gtm-sub">I personally run free pilot verifications on 1&ndash;3 of your results
          before your next submission. WhatsApp me to book a 20-minute session.</p>
          <div class="gtm-btn-gold">
            <a href="https://wa.me/233503648195" target="_blank">Book a Free Pilot Check</a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_tagline_footer()


# ---------------------------------------------------------------------------
# Screen 1 — Submission Form
# ---------------------------------------------------------------------------

def render_screen_1():
    st.markdown(
        """
        <div class="progress-steps">
          <span class="step">1</span><span class="step-label">Result Details</span>
          <span class="connector"></span>
          <span class="step">2</span><span class="step-label">Evidence</span>
          <span class="connector"></span>
          <span class="step">3</span><span class="step-label">Review Status</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_tutorial(1)

    active = st.session_state.get("active_slots", 1)

    # Sector selector (global, above all slots)
    st.selectbox(
        "Sector (optional — helps tailor examples)",
        key="sector",
        options=SECTOR_OPTIONS,
        help="Select your sector to see sector-specific example placeholders in the evidence description field.",
    )

    # Header row with optional "+" button
    col_h, col_add = st.columns([5, 1])
    with col_h:
        label = "Tell us about your result" if active == 1 else f"Tell us about your results ({active} added)"
        st.markdown(f"## {label}")
    with col_add:
        if active < 3:
            st.markdown("<div style='padding-top:22px'></div>", unsafe_allow_html=True)
            if st.button("＋ Add Result", use_container_width=True):
                st.session_state["active_slots"] = active + 1
                st.rerun()

    # Live Score Preview (slot 1)
    with st.expander("📊 Live Score Preview", expanded=False):
        _render_live_score_preview(1)

    # Render each slot
    for slot in range(1, active + 1):
        if active > 1:
            st.markdown(f"---\n#### Result {slot}")
        _render_slot_fields(slot)

    # Auto-save on every rerun
    _save_draft()

    st.divider()

    # Start Fresh with confirmation
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

    st.divider()

    if st.button("Run My Confidence Check", type="primary", use_container_width=True):
        mandatory = [
            st.session_state.get("result_statement", ""),
            st.session_state.get("target_group", ""),
            st.session_state.get("timeframe", ""),
            st.session_state.get("geographic_scope", ""),
            st.session_state.get("evidence_description", ""),
        ]
        # Validate "Other" evidence type has a description
        ev_type = st.session_state.get("evidence_type", "")
        ev_other = st.session_state.get("evidence_type_other", "").strip()
        if ev_type == "Other" and not ev_other:
            st.warning("Please specify your evidence type in the 'Specify evidence type' field.")
        elif not all(mandatory):
            st.warning("Add the missing details for Result 1 to run your confidence check.")
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
            st.session_state["screen"] = 2
            st.rerun()

    st.caption("Your progress is auto-saved.")
    if st.button("Back", use_container_width=False):
        _go_to_screen(0)

    _render_tagline_footer()


# ---------------------------------------------------------------------------
# Screen 2 — Confidence Snapshot & Next Steps
# ---------------------------------------------------------------------------

_BRAND_BADGE = {
    "Strong":     {"bg": "#C8E6C9", "text": "#1B5E20"},
    "Acceptable": {"bg": "#FFF9C4", "text": "#F57F17"},
    "Weak":       {"bg": "#FFE0B2", "text": "#E65100"},
    "High Risk":  {"bg": "#FFCDD2", "text": "#B71C1C"},
}

_VERDICT_CSS = {
    "Strong KPI — ready to submit":                                        "",
    "Misleading KPI — sharpen the definition before submission":           "misleading",
    "Well-defined but weak evidence — strengthen the verification chain":  "weak-conf",
    "High risk — do not submit until both axes are addressed":             "high-risk",
}


_DIRECTNESS_TIPS = {
    5: "Level 5 — Direct measurement: strongest possible evidence, fully traceable to the result.",
    4: "Level 4 — Near-direct evidence with high traceability (e.g. attendance sheets, photos with metadata).",
    3: "Level 3 — Moderately direct evidence; some verification gaps (e.g. partner letters, third-party audits).",
    2: "Level 2 — Indirect evidence; limited ability to trace back to the result.",
    1: "Level 1 — Very indirect evidence; cannot reliably attribute to this result.",
}

_VERIFICATION_TIPS = {
    5: "Level 5 — Verified by an independent third party: highest possible assurance.",
    4: "Level 4 — External partner review conducted: strong external assurance.",
    3: "Level 3 — Reviewed internally by a MEL Officer: adequate internal review.",
    2: "Level 2 — Collected only, no formal review: evidence is unreviewed.",
    1: "Level 1 — No review conducted: evidence is unverified.",
    0: "Level 0 — No review conducted: evidence is unverified.",
}

_RECENCY_TIPS = {
    5: "Level 5 — Evidence collected within the same reporting month: highly current.",
    4: "Level 4 — Evidence collected within 3 months: acceptably recent.",
    3: "Level 3 — Evidence collected within 6 months: moderately recent.",
    2: "Level 2 — Evidence collected within 12 months: aging — consider refreshing.",
    1: "Level 1 — Evidence older than 12 months: recency is a significant concern.",
}

_CLARITY_TIPS = {
    "definition":  "Definition (max 1.25) — how precisely the result states who, what, where, and by when.",
    "measurement": "Measurement (max 1.25) — whether a clear indicator, baseline, and target are stated.",
    "integrity":   "Integrity (max 1.0) — data completeness, audit trail, and absence of unexplained gaps.",
    "scope":       "Scope (max 0.75) — whether geographic and demographic coverage matches the claim.",
    "governance":  "Governance (max 0.75) — whether a named owner and a decision use for the result are stated.",
}


def _axis_badge_html(label: str, score: float, max_score: float) -> str:
    b = _BRAND_BADGE.get(label, {"bg": "#F5F5F5", "text": "#212121"})
    return (
        f"<div class='axis-badge' style='background:{b['bg']};color:{b['text']};'>"
        f"{score}/{max_score} &nbsp; <strong>{label.upper()}</strong>"
        f"</div>"
    )


def _render_result_card(submission: dict, ev: dict, card_idx: int = 0):
    conf_score   = ev.get("confidence_score", 0)
    clar_score   = ev.get("clarity_score", 0)
    conf_label   = ev.get("confidence_label", "High Risk")
    clar_label   = ev.get("clarity_label",   "High Risk")
    conf_meaning = ev.get("confidence_meaning", "")
    clar_meaning = ev.get("clarity_meaning",    "")
    verdict      = ev.get("verdict", "")
    conf_comp    = ev.get("confidence_components", {})
    clar_comp    = ev.get("clarity_components", {})

    snippet = submission.get("result_statement", "")
    if len(snippet) > 120:
        snippet = snippet[:120] + "..."
    st.markdown(f"**{snippet}**")
    st.divider()

    # Diagnostic state badge
    diag_state, diag_sub = get_diagnostic_state(conf_score, clar_score)
    diag_cfg = _DIAGNOSTIC_BADGE.get(diag_state, {"bg": "#9E9E9E", "text": "#FFFFFF", "subtitle": ""})
    _pca = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"
    st.markdown(
        f"<div class='diagnostic-badge' style='background:{diag_cfg['bg']};color:{diag_cfg['text']};{_pca}'>"
        f"{diag_state} &nbsp;·&nbsp; {diag_sub}"
        f"</div>",
        unsafe_allow_html=True,
    )

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
        st.metric("Directness", f"{ds}/2.0", help=_DIRECTNESS_TIPS.get(dl, ""))
        st.progress(min(ds / 2.0, 1.0))
        st.metric("Verification", f"{vs}/2.0", help=_VERIFICATION_TIPS.get(vl, ""))
        st.progress(min(vs / 2.0, 1.0))
        st.metric("Recency", f"{rs}/1.0", help=_RECENCY_TIPS.get(rl, ""))
        st.progress(min(rs / 1.0, 1.0))

    with col_clar:
        st.markdown("#### Clarity Score")
        st.markdown(_axis_badge_html(clar_label, clar_score, 5.0), unsafe_allow_html=True)
        st.caption(clar_meaning)
        def_s  = clar_comp.get("definition_score",  0)
        meas_s = clar_comp.get("measurement_score", 0)
        integ  = clar_comp.get("integrity_score",   0)
        scope  = clar_comp.get("scope_score",       0)
        gov    = clar_comp.get("governance_score",  0)
        st.metric("Definition", f"{def_s}/1.25", help=_CLARITY_TIPS["definition"])
        st.progress(min(def_s / 1.25, 1.0))
        st.metric("Measurement", f"{meas_s}/1.25", help=_CLARITY_TIPS["measurement"])
        st.progress(min(meas_s / 1.25, 1.0))
        st.metric("Integrity", f"{integ}/1.0", help=_CLARITY_TIPS["integrity"])
        st.progress(min(integ / 1.0, 1.0))
        st.metric("Scope", f"{scope}/0.75", help=_CLARITY_TIPS["scope"])
        st.progress(min(scope / 0.75, 1.0))
        st.metric("Governance", f"{gov}/0.75", help=_CLARITY_TIPS["governance"])
        st.progress(min(gov / 0.75, 1.0))

    # Verdict banner
    css_class = _VERDICT_CSS.get(verdict, "")
    st.markdown(
        f"<div class='verdict-banner {css_class}'>{verdict}</div>",
        unsafe_allow_html=True,
    )

    # What To Fix — tailored by diagnostic state
    fixes      = ev.get("fixes", [])
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
        st.success("No fixes needed — your result is ready to submit.")
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

    st.divider()


def render_screen_2():
    # Run evaluations once, cache results
    if not st.session_state.get("evaluations"):
        active = st.session_state.get("active_slots_run", st.session_state.get("active_slots", 1))
        subs, evs = [], []
        try:
            with st.spinner("Running confidence check..."):
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
        if st.button("Go Back and Try Again"):
            st.session_state["screen"] = 1
            st.session_state["evaluations"]  = None
            st.session_state["error_message"] = None
            st.rerun()
        return

    evs  = st.session_state.get("evaluations") or []
    subs = st.session_state.get("submissions_snapshot") or []

    if not evs:
        st.warning("No evaluation results found. Please go back and try again.")
        if st.button("Back"):
            _go_to_screen(1)
        return

    _render_tutorial(2)

    n = len(evs)
    st.markdown(
        "<h2 style='color:#1B5E20;margin-bottom:4px;'>Your Confidence Snapshot</h2>"
        "<p style='color:#B8860B;font-style:italic;font-size:0.95rem;margin-bottom:16px;'>"
        "Here&rsquo;s what would move your result from where it is now to where it needs to be.</p>",
        unsafe_allow_html=True,
    )

    for i, (sub, ev) in enumerate(zip(subs, evs)):
        if n > 1:
            st.markdown(f"### Result {i + 1}")
        _render_result_card(sub, ev, card_idx=i)

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
    app_url = "https://impact-receipts-fnxkamdve55429dk3bxmb9.streamlit.app"
    li_url  = f"https://www.linkedin.com/sharing/share-offsite/?url={urllib.parse.quote(app_url, safe='')}"
    st.markdown(
        f"Found this useful? "
        f"<a href='{li_url}' target='_blank'>Share Impact-Receipts on LinkedIn</a>"
        f" with a MEL colleague.",
        unsafe_allow_html=True,
    )

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_report = _build_html_report(subs[0], evs[0], timestamp) if n == 1 else \
                  _build_combined_html_report(subs, evs, timestamp)

    col_dl, col_json, col_add, col_fresh = st.columns([2, 1.5, 1, 1])
    with col_dl:
        st.download_button(
            label="Download Your Report (.html)",
            data=html_report,
            file_name=f"impact_receipts_{timestamp}.html",
            mime="text/html",
            use_container_width=True,
        )
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
        lines += ["No fixes needed — your result is ready to submit.", ""]

    lines += [
        "---",
        "",
        "*Evaluated using: Impact-Receipts v2 dual-axis scoring "
        "(USAID DQA / OECD-DAC / Bond Evidence Principles)*",
    ]

    return "\n".join(lines)


def _build_html_report(submission: dict, evaluation: dict, timestamp: str) -> str:
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
        pct = min(value / max_v * 100, 100)
        return (f"<div style='background:#E0E0E0;border-radius:4px;height:10px;margin-bottom:10px;{_pca}'>"
                f"<div style='background:#1B5E20;width:{pct:.1f}%;height:10px;border-radius:4px;{_pca}'></div></div>")

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
        "Strong KPI — ready to submit": "#1B5E20",
        "Misleading KPI — sharpen the definition before submission": "#E65100",
        "Well-defined but weak evidence — strengthen the verification chain": "#F57F17",
        "High risk — do not submit until both axes are addressed": "#B71C1C",
    }
    verdict_bg = verdict_colors.get(verdict, "#1B5E20")

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

    fixes_html = ""
    if conf_fixes:
        fixes_html += ("<h3 style='color:#1B5E20;'>Strengthen your evidence (Confidence)</h3>"
                       f"<ul>{fix_items(conf_fixes)}</ul>")
    if clar_fixes:
        fixes_html += ("<h3 style='color:#1B5E20;'>Sharpen your definition (Clarity)</h3>"
                       f"<ul>{fix_items(clar_fixes)}</ul>")
    if not fixes:
        fixes_html = "<p style='color:#1B5E20;font-weight:700;'>No fixes needed — your result is ready to submit.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Impact-Receipts Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"/>
<style>
  body{{font-family:'Inter',sans-serif;color:#212121;max-width:860px;margin:40px auto;padding:0 24px;}}
  h1,h2,h3{{color:#1B5E20;}} h1{{font-size:1.6rem;}} h2{{font-size:1.2rem;border-bottom:1px solid #B8860B;padding-bottom:4px;margin-top:28px;}}
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

<h2>Result Statement</h2>
<p>{submission.get('result_statement', '-')}</p>
<p><strong>Target Group:</strong> {submission.get('target_group', '-')}<br/>
   <strong>Timeframe:</strong> {submission.get('timeframe', '-')}<br/>
   <strong>Geographic Scope:</strong> {submission.get('geographic_scope', '-')}</p>
{files_row}

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
    <p style="color:#616161;font-size:0.85rem;">{evaluation.get('confidence_meaning','')}</p>
    <table>
      <tr><th>Component</th><th>Score</th><th>Bar</th></tr>
      {row(f"Directness (Level {dl}/5)", ds, 2.0, _DIRECTNESS_TIPS.get(dl,''))}
      {row(f"Verification (Level {vl}/5)", vs, 2.0, _VERIFICATION_TIPS.get(vl,''))}
      {row(f"Recency (Level {rl}/5)", rs, 1.0, _RECENCY_TIPS.get(rl,''))}
    </table>
  </div>
  <div>
    <strong>Clarity Score</strong><br/>
    {badge(clar_label, clar_score, 5.0)}
    <p style="color:#616161;font-size:0.85rem;">{evaluation.get('clarity_meaning','')}</p>
    <table>
      <tr><th>Component</th><th>Score</th><th>Bar</th></tr>
      {row("Definition", def_s, 1.25, _CLARITY_TIPS['definition'])}
      {row("Measurement", meas_s, 1.25, _CLARITY_TIPS['measurement'])}
      {row("Integrity", integ, 1.0, _CLARITY_TIPS['integrity'])}
      {row("Scope", scope, 0.75, _CLARITY_TIPS['scope'])}
      {row("Governance", gov, 0.75, _CLARITY_TIPS['governance'])}
    </table>
  </div>
</div>

<h2>What To Fix</h2>
{fixes_html}

<div class="footer">
  Evaluated using Impact-Receipts v2 dual-axis scoring (USAID DQA / OECD-DAC / Bond Evidence Principles).<br/>
  Tip: Print this page (Ctrl+P) and choose &ldquo;Save as PDF&rdquo; to get a PDF copy.
</div>
</body>
</html>"""


def _build_combined_html_report(submissions: list, evaluations: list, timestamp: str) -> str:
    parts = []
    for i, (sub, ev) in enumerate(zip(submissions, evaluations)):
        section = _build_html_report(sub, ev, timestamp)
        # Strip outer HTML wrapper from all but the first, append just the body content
        if i == 0:
            parts.append(section)
        else:
            start = section.find("<h2>Result Statement</h2>")
            if start == -1:
                start = section.find("<h2 ")
            end   = section.rfind("</body>")
            insert_at = parts[0].rfind("</body>")
            divider = f"<hr style='margin:40px 0;border:2px solid #B8860B;'/><h2 style='color:#1B5E20;'>Result {i+1}</h2>"
            parts[0] = parts[0][:insert_at] + divider + section[start:end] + parts[0][insert_at:]
    return parts[0]


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
    _init_session_state()

    screen = st.session_state["screen"]
    if screen == 1:
        st.progress(0.5, text="Submission Form")
    elif screen == 2:
        st.progress(1.0, text="Confidence Check Complete")

    {0: render_screen_0, 1: render_screen_1, 2: render_screen_2}.get(
        screen, render_screen_0
    )()


if __name__ == "__main__":
    main()
