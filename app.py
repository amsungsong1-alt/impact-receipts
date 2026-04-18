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
</style>
"""

# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _init_session_state():
    defaults = {
        "screen":               0,
        "error_message":        None,
        "evaluation":           None,
        "submission_snapshot":  None,
        # Form widget keys — match key= params in render_screen_1
        "result_statement":     "",
        "target_group":         "",
        "timeframe":            "",
        "geographic_scope":     "",
        "evidence_description": "",
        "evidence_type":        EVIDENCE_TYPES[0],
        "evidence_type_other":  "",
        "internal_review":      INTERNAL_REVIEW_OPTIONS[0],
        "internal_review_other": "",
        "external_review":      EXTERNAL_REVIEW_OPTIONS[0],
        "external_review_other": "",
        "verifier":             "",
        "evidence_date":        None,
        "uploaded_files":       [],
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def _go_to_screen(screen: int, reset: bool = False):
    if reset:
        for k in [
            "result_statement", "target_group", "timeframe", "geographic_scope",
            "evidence_description", "evidence_type", "evidence_type_other",
            "internal_review", "internal_review_other",
            "external_review", "external_review_other",
            "verifier", "evidence_date", "uploaded_files",
            "evaluation", "submission_snapshot", "error_message",
        ]:
            st.session_state.pop(k, None)
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

_DRAFT_TEXT_KEYS = [
    "result_statement", "target_group", "timeframe", "geographic_scope",
    "evidence_description", "evidence_type", "evidence_type_other",
    "internal_review", "internal_review_other",
    "external_review", "external_review_other",
    "verifier",
]


def _save_draft():
    draft = {k: st.session_state.get(k, "") for k in _DRAFT_TEXT_KEYS}
    ed = st.session_state.get("evidence_date")
    draft["evidence_date"] = ed.isoformat() if hasattr(ed, "isoformat") else ""
    raw_files = st.session_state.get("uploaded_files_widget") or []
    draft["uploaded_filenames"] = [f.name for f in raw_files if hasattr(f, "name")]
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
    for k in _DRAFT_TEXT_KEYS:
        if k in draft:
            st.session_state[k] = draft[k]
    raw_date = draft.get("evidence_date", "")
    if raw_date:
        try:
            st.session_state["evidence_date"] = date.fromisoformat(raw_date)
        except (ValueError, TypeError):
            pass
    st.session_state["draft_uploaded_filenames"] = draft.get("uploaded_filenames", [])


def _build_submission_from_session() -> dict:
    """Assemble evaluator-compatible submission dict from flat session_state."""
    ev_type = st.session_state.get("evidence_type", "")
    if ev_type == "Other":
        ev_type = st.session_state.get("evidence_type_other", "") or "Other"

    int_rev = st.session_state.get("internal_review", "Not reviewed")
    if int_rev == "Other":
        int_rev = st.session_state.get("internal_review_other", "") or "Other"

    ext_rev = st.session_state.get("external_review", "No external review")
    if ext_rev == "Other":
        ext_rev = st.session_state.get("external_review_other", "") or "Other"

    return {
        "result_statement":  st.session_state.get("result_statement", ""),
        "target_group":      st.session_state.get("target_group", ""),
        "timeframe":         st.session_state.get("timeframe", ""),
        "geographic_scope":  st.session_state.get("geographic_scope", ""),
        "additional_context": "",
        "internal_review":   int_rev,
        "external_review":   ext_rev,
        "attached_filenames": st.session_state.get("uploaded_files", []),
        "evidence": [
            {
                "type":        ev_type,
                "description": st.session_state.get("evidence_description", ""),
                "recency":     _format_date(st.session_state.get("evidence_date")),
                "verified_by": st.session_state.get("verifier", ""),
            }
        ],
    }


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

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Review Results Before Submission", type="primary", use_container_width=True):
            _go_to_screen(1, reset=True)
    with col_b:
        if st.button("Run My Confidence Check", use_container_width=True):
            _go_to_screen(1, reset=True)

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
          <span class="step">1</span>
          <span class="step-label">Result Details</span>
          <span class="connector"></span>
          <span class="step">2</span>
          <span class="step-label">Evidence</span>
          <span class="connector"></span>
          <span class="step">3</span>
          <span class="step-label">Review Status</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("## Tell us about your result")

    # No st.form — plain widgets so selectbox changes rerun immediately,
    # enabling the "Other → Specify" fields to appear without a submit first.

    st.text_area(
        "Result statement",
        key="result_statement",
        placeholder=(
            "e.g., Trained 500 smallholder farmers in climate-smart agriculture across "
            "3 districts in Northern Ghana between January and June 2025"
        ),
        height=100,
        help="What is the specific result you're reporting?",
    )

    st.text_input(
        "Target group",
        key="target_group",
        placeholder="e.g., Smallholder farmers, 18-60 years old, three districts in Northern Region",
    )

    st.text_input(
        "Timeframe",
        key="timeframe",
        placeholder="e.g., January - June 2025",
    )

    st.text_input(
        "Geographic scope",
        key="geographic_scope",
        placeholder="e.g., Tamale, Yendi, Savelugu districts",
    )

    st.text_area(
        "Describe your supporting evidence",
        key="evidence_description",
        placeholder=(
            "e.g., Signed attendance sheets from 12 training sessions across 3 districts, "
            "verified by District Agriculture Officer."
        ),
        height=120,
    )

    # Evidence Type — "Other" reveal works because selectbox change triggers rerun
    st.selectbox("Evidence type", key="evidence_type", options=EVIDENCE_TYPES)
    if st.session_state.get("evidence_type") == "Other":
        st.text_input("Specify evidence type", key="evidence_type_other")

    # Internal Review
    st.selectbox("Internal review", key="internal_review", options=INTERNAL_REVIEW_OPTIONS)
    if st.session_state.get("internal_review") == "Other":
        st.text_input("Specify internal reviewer", key="internal_review_other")

    # External Review
    st.selectbox("External review", key="external_review", options=EXTERNAL_REVIEW_OPTIONS)
    if st.session_state.get("external_review") == "Other":
        st.text_input("Specify external reviewer", key="external_review_other")

    st.text_input(
        "Who verified this?",
        key="verifier",
        placeholder="e.g., District Agriculture Officer, partner org M&E lead, external evaluator",
    )

    st.date_input("When was this evidence collected?", key="evidence_date")

    prev_files = st.session_state.get("draft_uploaded_filenames", [])
    if prev_files:
        st.caption(f"Previously attached: {', '.join(prev_files)} — please re-attach below.")

    st.file_uploader(
        "Attach supporting documents (optional)",
        key="uploaded_files_widget",
        accept_multiple_files=True,
        type=["pdf", "docx", "xlsx", "csv", "jpg", "jpeg", "png", "txt"],
        help="Attach raw evidence files — datasets, signed sheets, photos with metadata, partner letters.",
    )

    # Auto-save on every rerun (every widget interaction)
    _save_draft()

    st.divider()

    if st.button(
        "Run My Confidence Check",
        type="primary",
        use_container_width=True,
    ):
        mandatory = [
            st.session_state.get("result_statement", ""),
            st.session_state.get("target_group", ""),
            st.session_state.get("timeframe", ""),
            st.session_state.get("geographic_scope", ""),
            st.session_state.get("evidence_description", ""),
        ]
        if not all(mandatory):
            st.warning("Add the missing details above to run your confidence check.")
        else:
            raw_files = st.session_state.get("uploaded_files_widget") or []
            st.session_state["uploaded_files"]       = [f.name for f in raw_files]
            st.session_state["evaluation"]           = None
            st.session_state["submission_snapshot"]  = None
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


def _render_result_card(submission: dict, ev: dict):
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

    # What To Fix
    fixes      = ev.get("fixes", [])
    conf_fixes = [f for f in fixes if f.get("dimension") == "confidence"]
    clar_fixes = [f for f in fixes if f.get("dimension") == "clarity"]

    if conf_label == "Strong" and clar_label == "Strong":
        st.success("No fixes needed — your result is ready to submit.")
        if fixes:
            smallest = fixes[0]
            st.caption(f"Optional refinement: {smallest['message']} ({smallest['score_impact']})")
    else:
        if conf_fixes:
            st.markdown("##### Strengthen your evidence (Confidence)")
            for j, fix in enumerate(conf_fixes):
                st.checkbox(
                    f"{fix['message']}  _({fix['score_impact']})_",
                    value=False,
                    key=f"fix_conf_{j}",
                )
        if clar_fixes:
            st.markdown("##### Sharpen your definition (Clarity)")
            for j, fix in enumerate(clar_fixes):
                st.checkbox(
                    f"{fix['message']}  _({fix['score_impact']})_",
                    value=False,
                    key=f"fix_clar_{j}",
                )

    filenames = submission.get("attached_filenames", [])
    if filenames:
        st.caption(f"Attached documents: {', '.join(filenames)}")

    st.divider()


def render_screen_2():
    # Run evaluation once and cache in session_state
    if not st.session_state.get("evaluation"):
        from evaluator import evaluate_submission

        submission = _build_submission_from_session()
        try:
            with st.spinner("Running confidence check..."):
                ev = evaluate_submission(submission)
            save_all_files(submission, ev)
            st.session_state["evaluation"]        = ev
            st.session_state["submission_snapshot"] = submission
            st.rerun()
        except Exception as exc:
            st.session_state["error_message"] = (
                f"Something went wrong during evaluation:\n\n{exc}\n\n"
                "Please go back and try again."
            )

    if st.session_state.get("error_message"):
        st.error(st.session_state["error_message"])
        if st.button("Go Back and Try Again"):
            st.session_state["screen"] = 1
            st.session_state["evaluation"] = None
            st.session_state["error_message"] = None
            st.rerun()
        return

    ev         = st.session_state.get("evaluation")
    submission = st.session_state.get("submission_snapshot")

    if not ev or not submission:
        st.warning("No evaluation results found. Please go back and try again.")
        if st.button("Back"):
            _go_to_screen(1)
        return

    st.markdown(
        "<h2 style='color:#1B5E20;margin-bottom:4px;'>Your Confidence Snapshot</h2>"
        "<p style='color:#B8860B;font-style:italic;font-size:0.95rem;margin-bottom:16px;'>"
        "Here&rsquo;s what would move your result from where it is now to where it needs to be.</p>",
        unsafe_allow_html=True,
    )

    _render_result_card(submission, ev)

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

    snippet = submission.get("result_statement", "")[:120]
    li_text = urllib.parse.quote(
        f"I just stress-tested a result using Impact-Receipts before submitting. "
        f"Here's what it caught: {snippet}. "
        f"Try it: https://impact-receipts-fnxkamdve55429dk3bxmb9.streamlit.app"
    )
    li_url = (
        "https://www.linkedin.com/shareArticle?mini=true"
        "&url=https%3A%2F%2Fimpact-receipts-fnxkamdve55429dk3bxmb9.streamlit.app"
        f"&summary={li_text}"
    )
    st.markdown(
        f"Found this useful? "
        f"<a href='{li_url}' target='_blank'>Share Impact-Receipts on LinkedIn</a>"
        f" with a MEL colleague.",
        unsafe_allow_html=True,
    )

    col_dl, col_restart = st.columns([2, 1])
    with col_dl:
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_report = _build_html_report(submission, ev, timestamp)
        st.download_button(
            label="Download Your Report (.html)",
            data=html_report,
            file_name=f"impact_receipts_{timestamp}.html",
            mime="text/html",
            use_container_width=True,
        )
    with col_restart:
        if st.button("Check Another Result", use_container_width=True):
            _go_to_screen(0, reset=True)

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
