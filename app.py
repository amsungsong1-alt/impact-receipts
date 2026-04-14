"""
app.py — Impact-Receipts: Pre-submission confidence check for MEL teams.

Run with:  streamlit run app.py

Three-screen flow driven by st.session_state["screen"] (0–2):
  0  Landing & Onboarding
  1  Reported Result Submission (1–3 results, combined form)
  2  Confidence Snapshot & Next Steps

Evaluation logic is fully local — see evaluator.py.
No API calls. All data stays on device.
"""

import json
import os
import re
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVIDENCE_TYPES = [
    "Attendance sheet / participant register",
    "Project dataset / survey data",
    "Partner organization report",
    "Survey summary / assessment report",
    "Government / administrative records",
    "Field observation notes",
    "Financial disbursement records",
    "Third-party evaluation report",
    "Photographs / visual documentation",
    "Other",
]

INTERNAL_REVIEW_OPTIONS = [
    "Not reviewed",
    "Reviewed by M&E Officer",
    "Reviewed by Program Manager",
    "Reviewed by senior leadership or board",
    "Reviewed by multiple internal stakeholders",
]

EXTERNAL_REVIEW_OPTIONS = [
    "No external review",
    "Reviewed by partner organisation",
    "Reviewed by independent evaluator",
    "Reviewed by donor representative",
    "Third-party audit completed",
]

# ---------------------------------------------------------------------------
# CSS — injected once at app load
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Inter:wght@400;500&display=swap');

:root {
  --navy:        #1B2A4A;
  --emerald:     #2E7D5B;
  --brand-green: #1B5E20;
  --bg-card:     #F8F9FB;
  --border:      rgba(27,42,74,0.15);
  --text-muted:  #6B7280;
}

html, body, [class*="css"] {
  font-family: 'Inter', sans-serif;
}

h1, h2, h3, h4 {
  font-family: 'DM Sans', sans-serif;
  color: var(--navy);
}

/* Primary button → emerald */
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
  background-color: var(--emerald) !important;
  border-color: var(--emerald) !important;
  color: white !important;
  font-family: 'DM Sans', sans-serif;
  font-weight: 600;
  border-radius: 8px;
}

/* Secondary button → navy outline */
.stButton > button[kind="secondary"],
.stFormSubmitButton > button[kind="secondary"] {
  border-color: var(--navy) !important;
  color: var(--navy) !important;
  font-family: 'DM Sans', sans-serif;
}

/* Card container */
.result-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 20px;
}

/* Confidence badge */
.confidence-badge {
  padding: 16px 24px;
  border-radius: 10px;
  text-align: center;
  color: white;
  font-family: 'DM Sans', sans-serif;
  margin-bottom: 8px;
}

/* Progress steps row */
.progress-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 24px;
  font-family: 'DM Sans', sans-serif;
  font-size: 0.85rem;
  color: var(--navy);
}
.progress-steps .step {
  background: var(--emerald);
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
  background: var(--border);
  max-width: 40px;
}
.progress-steps .step-label {
  font-weight: 500;
}

/* Hero section */
.hero-block {
  padding: 12px 0 28px 0;
}
.hero-block h1 {
  font-size: 1.85rem;
  line-height: 1.25;
  margin-bottom: 14px;
}
.hero-sub {
  font-size: 1rem;
  color: #374151;
  line-height: 1.6;
  margin-bottom: 0;
}

/* IS / IS NOT table */
.is-not-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 20px 0;
}
.is-col, .isnot-col {
  padding: 16px 20px;
  border-radius: 10px;
}
.is-col {
  background: #EDF7F1;
  border: 1px solid #A7D9BC;
}
.isnot-col {
  background: #FEF3F2;
  border: 1px solid #FCA5A5;
}
.is-col h4 { color: var(--brand-green); margin: 0 0 10px 0; }
.isnot-col h4 { color: #991B1B; margin: 0 0 10px 0; }
.is-col li, .isnot-col li { margin-bottom: 6px; font-size: 0.9rem; }

/* CTA call button */
.cta-call-btn a {
  display: inline-block;
  background: var(--emerald);
  color: white !important;
  font-family: 'DM Sans', sans-serif;
  font-weight: 600;
  padding: 10px 20px;
  border-radius: 8px;
  text-decoration: none;
  font-size: 0.95rem;
}
.cta-call-btn a:hover {
  background: #245f46;
}

/* Results summary banner */
.summary-banner {
  background: var(--navy);
  color: white;
  border-radius: 10px;
  padding: 16px 22px;
  font-family: 'DM Sans', sans-serif;
  margin-bottom: 24px;
}
.summary-banner p { margin: 0; font-size: 0.95rem; }
</style>
"""

# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _blank_result_block() -> dict:
    """Return a fresh submission dict with all evaluator-required keys."""
    return {
        "result_statement": "",
        "target_group": "",
        "timeframe": "",
        "geographic_scope": "",
        "additional_context": "",
        "internal_review": INTERNAL_REVIEW_OPTIONS[0],
        "external_review": EXTERNAL_REVIEW_OPTIONS[0],
        "evidence": [
            {
                "type": EVIDENCE_TYPES[0],
                "description": "",
                "recency": "",
                "verified_by": "",
            }
        ],
    }


def _init_session_state():
    defaults = {
        "screen": 0,
        "results_data": [_blank_result_block()],
        "evaluations": [],
        "saved_paths": [],
        "error_message": None,
        "active_result_count": 1,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def _go_to_screen(screen: int, reset: bool = False):
    if reset:
        st.session_state["results_data"] = [_blank_result_block()]
        st.session_state["evaluations"] = []
        st.session_state["saved_paths"] = []
        st.session_state["error_message"] = None
        st.session_state["active_result_count"] = 1
    st.session_state["screen"] = screen
    st.rerun()


# ---------------------------------------------------------------------------
# Screen 0 — Landing & Onboarding
# ---------------------------------------------------------------------------

def render_screen_0():
    st.markdown(
        """
        <div class="hero-block">
          <h1>Know which reported results are strong, weak, or need fixing — before submission.</h1>
          <p class="hero-sub">
            Impact-Receipts helps MEL and reporting teams check up to 3 reported results
            before submission, review the evidence behind them, and see what needs fixing
            before the report goes to donors, leadership, or partners.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button(
            "Review Results Before Submission",
            type="primary",
            use_container_width=True,
        ):
            _go_to_screen(1, reset=True)
    with col_b:
        if st.button(
            "Run My Confidence Check",
            use_container_width=True,
        ):
            _go_to_screen(1, reset=True)

    st.markdown(
        """
        <div class="is-not-grid">
<div class="is-col" style="color: #1B5E20 !important;">            <h4>✓ What this IS</h4>
            <ul style="color: #1B5E20 !important;">
              <li>A quick confidence check for reported results before submission</li>
              <li>A guide that shows what to fix and why</li>
              <li>Fully local — runs on your device, no data sent anywhere</li>
              <li>Free and instant — no login, no API key</li>
            </ul>
          </div>
          <div class="isnot-col">
<div class="isnot-col" style="color: #991B1B !important;"><h4 style="color: #991B1B !important;">✗ What this is NOT</h4>
<ul style="color: #C62828 !important;">
              <li>A full reporting system, database, or audit tool</li>
              <li>A replacement for your M&amp;E framework</li>
              <li>An AI that invents or assumes missing data</li>
              <li>A publishing or submission platform</li>
            </ul>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.info(
        "Questions before you start? Chat with us on WhatsApp: "
        "[+233 50 364 8195](https://wa.me/233503648195)",
        icon="💬",
    )

    st.caption("Your data stays on your device. Nothing is stored or shared.")


# ---------------------------------------------------------------------------
# Screen 1 — Submission Form
# ---------------------------------------------------------------------------

def _render_result_block(i: int):
    """Render all form fields for result block i (must be called inside a st.form)."""
    count = st.session_state["active_result_count"]
    block = st.session_state["results_data"][i]
    label = f"Result {i + 1}" if count > 1 else "Your Result"

    st.markdown(f"<div class='result-card'>", unsafe_allow_html=True)
    st.subheader(label)

    # Result statement
    block["result_statement"] = st.text_area(
        "Result Statement *",
        value=block["result_statement"],
        height=110,
        placeholder=(
            "e.g. 1,240 smallholder farmers in Kwara State, Nigeria adopted "
            "improved seed varieties between January and June 2024."
        ),
        help="What was achieved? Include a number, a group, a place, and a timeframe.",
        key=f"rs_{i}",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        block["target_group"] = st.text_input(
            "Target Group",
            value=block["target_group"],
            placeholder="e.g. Female smallholder farmers",
            key=f"tg_{i}",
        )
    with c2:
        block["timeframe"] = st.text_input(
            "Timeframe",
            value=block["timeframe"],
            placeholder="e.g. January–June 2024",
            key=f"tf_{i}",
        )
    with c3:
        block["geographic_scope"] = st.text_input(
            "Geographic Scope",
            value=block["geographic_scope"],
            placeholder="e.g. Kwara State, Nigeria",
            key=f"gs_{i}",
        )

    block["evidence"][0]["description"] = st.text_area(
        "Supporting Evidence",
        value=block["evidence"][0]["description"],
        height=90,
        placeholder=(
            "Describe your main evidence — what it is, how many people it covers, "
            "when it was collected, and how it was gathered.\n\n"
            "e.g. Attendance sheets, datasets, partner reports, photos, survey summaries."
        ),
        key=f"ev_desc_{i}",
    )

    c4, c5, c6 = st.columns([2, 2, 1])
    with c4:
        ev_type = block["evidence"][0]["type"]
        block["evidence"][0]["type"] = st.selectbox(
            "Evidence Type",
            EVIDENCE_TYPES,
            index=EVIDENCE_TYPES.index(ev_type) if ev_type in EVIDENCE_TYPES else 0,
            key=f"ev_type_{i}",
        )
    with c5:
        block["evidence"][0]["verified_by"] = st.text_input(
            "Who verified / collected this?",
            value=block["evidence"][0]["verified_by"],
            placeholder="e.g. Field M&E Officer",
            key=f"ev_ver_{i}",
        )
    with c6:
        block["evidence"][0]["recency"] = st.text_input(
            "Evidence Date",
            value=block["evidence"][0]["recency"],
            placeholder="e.g. June 2024",
            key=f"ev_rec_{i}",
        )

    with st.expander("Review Status & Context (optional but recommended)"):
        ir_idx = (
            INTERNAL_REVIEW_OPTIONS.index(block["internal_review"])
            if block["internal_review"] in INTERNAL_REVIEW_OPTIONS
            else 0
        )
        er_idx = (
            EXTERNAL_REVIEW_OPTIONS.index(block["external_review"])
            if block["external_review"] in EXTERNAL_REVIEW_OPTIONS
            else 0
        )
        rc1, rc2 = st.columns(2)
        with rc1:
            block["internal_review"] = st.selectbox(
                "Internal Review",
                INTERNAL_REVIEW_OPTIONS,
                index=ir_idx,
                key=f"ir_{i}",
            )
        with rc2:
            block["external_review"] = st.selectbox(
                "External Review",
                EXTERNAL_REVIEW_OPTIONS,
                index=er_idx,
                key=f"er_{i}",
            )
        block["additional_context"] = st.text_area(
            "Additional Context (optional)",
            value=block["additional_context"],
            height=70,
            placeholder=(
                "Any methodology notes, caveats, or context the evaluator should know."
            ),
            key=f"ctx_{i}",
        )

    st.markdown("</div>", unsafe_allow_html=True)


def _handle_submission_submit():
    count = st.session_state["active_result_count"]
    errors = []
    for i in range(count):
        block = st.session_state["results_data"][i]
        if not block["result_statement"].strip():
            errors.append(f"Result {i + 1}: Result Statement is required.")

    if errors:
        for e in errors:
            st.error(e)
        return

    # Normalise empty optional fields
    for block in st.session_state["results_data"][:count]:
        block["target_group"] = block["target_group"].strip() or "Not specified"
        block["timeframe"] = block["timeframe"].strip() or "Not specified"
        block["geographic_scope"] = block["geographic_scope"].strip() or "Not specified"
        block["additional_context"] = block["additional_context"].strip() or None

    st.session_state["evaluations"] = []
    st.session_state["saved_paths"] = []
    _go_to_screen(2)


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

    count = st.session_state["active_result_count"]

    # Ensure results_data has enough blank blocks
    while len(st.session_state["results_data"]) < count:
        st.session_state["results_data"].append(_blank_result_block())

    # Add/remove buttons sit outside the form so they trigger immediately
    col_add, _ = st.columns([2, 5])
    with col_add:
        if count < 3:
            if st.button("+ Add Another Result", use_container_width=True):
                st.session_state["active_result_count"] += 1
                if len(st.session_state["results_data"]) < st.session_state["active_result_count"]:
                    st.session_state["results_data"].append(_blank_result_block())
                st.rerun()

    with st.form("submission_form"):
        for i in range(count):
            _render_result_block(i)
            if i < count - 1:
                st.divider()

        col_back, col_submit = st.columns([1, 3])
        with col_back:
            back = st.form_submit_button("← Back", use_container_width=True)
        with col_submit:
            submit = st.form_submit_button(
                "Run My Confidence Check",
                type="primary",
                use_container_width=True,
            )

    if back:
        _go_to_screen(0)

    if submit:
        _handle_submission_submit()


# ---------------------------------------------------------------------------
# Screen 2 — Confidence Snapshot & Next Steps
# ---------------------------------------------------------------------------

def _render_result_card(i: int, block: dict, ev: dict):
    from evaluator import compute_confidence_label

    scores = ev.get("scores", {})
    label, color = compute_confidence_label(scores)
    count = st.session_state["active_result_count"]

    # Header: result snippet + confidence badge
    col_txt, col_badge = st.columns([3, 1])
    with col_txt:
        prefix = f"**Result {i + 1}:**  " if count > 1 else ""
        snippet = block["result_statement"]
        if len(snippet) > 90:
            snippet = snippet[:90] + "…"
        st.markdown(f"{prefix}{snippet}")
    with col_badge:
        st.markdown(
            f"<div class='confidence-badge' style='background:{color};'>"
            f"<strong>{label}</strong></div>",
            unsafe_allow_html=True,
        )

    # Plain-language WHY
    st.caption(ev.get("label_rationale", ""))

    # Dimension bars
    dim_config = [
        ("clarity_of_claim",     "Clarity",  "Is the unit, timeframe, and target group explicit?"),
        ("strength_of_evidence", "Evidence", "Is the evidence direct, recent, and verified?"),
        ("independent_review",   "Review",   "Has it been peer-reviewed?"),
    ]
    cols = st.columns(3)
    for col, (dim_key, dim_label, dim_desc) in zip(cols, dim_config):
        dim = scores.get(dim_key, {})
        score = dim.get("score", 0)
        with col:
            st.metric(label=dim_label, value=f"{score} / 5")
            st.progress(score / 5)
            st.caption(dim_desc)
            rationale = dim.get("rationale", "")
            if rationale:
                with st.expander("Why"):
                    st.write(rationale)
                    missing = dim.get("missing_elements", [])
                    if missing:
                        for m in missing:
                            st.markdown(f"- {m}")

    # What to Fix checklist
    fixes = ev.get("fixes", [])
    if fixes:
        st.markdown("**What to Fix Before Submission:**")
        for j, fix in enumerate(fixes):
            st.checkbox(fix, value=False, key=f"fix_{i}_{j}")
    else:
        st.success("No specific fixes required — this result is ready to submit.")

    st.divider()


def render_screen_2():
    count = st.session_state["active_result_count"]
    results_data = st.session_state["results_data"][:count]

    # Run evaluations if not yet done
    if not st.session_state.get("evaluations"):
        from evaluator import evaluate_submission

        evaluations = []
        saved_paths_list = []
        error_occurred = False

        with st.spinner("Running confidence check…"):
            for i, submission in enumerate(results_data):
                try:
                    ev = evaluate_submission(submission)
                    evaluations.append(ev)
                    paths = save_all_files(submission, ev, result_index=i)
                    saved_paths_list.append(paths)
                except Exception as exc:
                    st.session_state["error_message"] = (
                        f"Error evaluating Result {i + 1}:\n\n{exc}\n\n"
                        "Please go back and try again."
                    )
                    error_occurred = True
                    break

        if not error_occurred:
            st.session_state["evaluations"] = evaluations
            st.session_state["saved_paths"] = saved_paths_list
            st.rerun()

    # Error state
    if st.session_state.get("error_message"):
        st.error(st.session_state["error_message"])
        if st.button("← Go Back and Try Again"):
            st.session_state["screen"] = 1
            st.session_state["evaluations"] = []
            st.session_state["error_message"] = None
            st.rerun()
        return

    evaluations = st.session_state["evaluations"]
    if not evaluations:
        st.warning("No evaluation results found. Please go back and try again.")
        if st.button("← Back"):
            _go_to_screen(1)
        return

    # Summary header
    st.markdown(
        "<h2 style='color:var(--navy);margin-bottom:4px;'>Your Confidence Check Results</h2>",
        unsafe_allow_html=True,
    )

    if count > 1:
        from evaluator import compute_confidence_label
        labels = [compute_confidence_label(ev.get("scores", {}))[0] for ev in evaluations]
        from collections import Counter
        label_counts = Counter(labels)
        summary_parts = " · ".join(f"{v}× {k}" for k, v in label_counts.items())
        st.markdown(
            f"<div class='summary-banner'><p>{count} results evaluated: {summary_parts}</p></div>",
            unsafe_allow_html=True,
        )

    # Per-result cards
    for i, ev in enumerate(evaluations):
        _render_result_card(i, results_data[i], ev)

    # Action CTAs
    st.markdown("### Next Steps")
    col_wa, col_dl, col_restart = st.columns(3)

    with col_wa:
        st.markdown(
            "<div class='cta-call-btn'>"
            "<a href='https://wa.me/233503648195' target='_blank'>"
            "Book a 20-Minute Review Call"
            "</a></div>",
            unsafe_allow_html=True,
        )

    with col_dl:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_report = _build_combined_markdown_report(
            results_data, evaluations, timestamp
        )
        st.download_button(
            label="Download Summary (.md)",
            data=combined_report,
            file_name=f"impact_receipts_{timestamp}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with col_restart:
        if st.button("Check Another Result", use_container_width=True):
            _go_to_screen(0, reset=True)


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------

def save_all_files(
    submission: dict, evaluation: dict, result_index: int = 0
) -> dict:
    """Save input JSON, evaluation JSON, and markdown report to disk."""
    os.makedirs("inputs", exist_ok=True)
    os.makedirs("evaluations", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _make_slug(submission.get("result_statement", "result"))
    suffix = f"_r{result_index + 1}" if result_index > 0 else ""
    base = f"{timestamp}{suffix}_{slug}"

    paths = {
        "input":      os.path.join("inputs",      f"{base}_input.json"),
        "evaluation": os.path.join("evaluations", f"{base}_evaluation.json"),
        "output":     os.path.join("outputs",     f"{base}_report.md"),
    }

    with open(paths["input"], "w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2, ensure_ascii=False)

    save_eval = {k: v for k, v in evaluation.items() if not k.startswith("_")}
    with open(paths["evaluation"], "w", encoding="utf-8") as f:
        json.dump(save_eval, f, indent=2, ensure_ascii=False)

    report = _build_markdown_report(submission, evaluation, timestamp)
    with open(paths["output"], "w", encoding="utf-8") as f:
        f.write(report)

    return paths


def _make_slug(text: str, max_len: int = 45) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len]


def _build_markdown_report(
    submission: dict, evaluation: dict, timestamp: str
) -> str:
    scores = evaluation.get("scores", {})

    from evaluator import compute_confidence_label
    py_label, _ = compute_confidence_label(scores)

    lines = [
        "# Impact-Receipts Evaluation Report",
        f"**Generated:** {timestamp}",
        f"**Confidence Label:** {py_label}",
        "",
        "---",
        "",
        "## Result Statement",
        f"{submission.get('result_statement', '—')}",
        "",
        f"- **Target Group:** {submission.get('target_group', '—')}",
        f"- **Timeframe:** {submission.get('timeframe', '—')}",
        f"- **Geographic Scope:** {submission.get('geographic_scope', '—')}",
        "",
        "---",
        "",
        "## Dimension Scores",
    ]

    dim_map = {
        "clarity_of_claim":     "Clarity of Claim",
        "strength_of_evidence": "Strength of Evidence",
        "independent_review":   "Independent Review",
    }
    for key, name in dim_map.items():
        dim = scores.get(key, {})
        lines += [
            f"### {name}: {dim.get('score', '?')} / 5",
            "",
            dim.get("rationale", ""),
            "",
        ]
        missing = dim.get("missing_elements", [])
        if missing:
            lines += ["**Missing:**"] + [f"- {m}" for m in missing] + [""]

    lines += ["---", "", "## Key Issues", ""]
    for issue in evaluation.get("key_issues", []):
        lines.append(f"- {issue}")

    lines += ["", "---", "", "## What to Fix Before Submission", ""]
    for fix in evaluation.get("fixes", []):
        lines.append(f"- [ ] {fix}")

    lines += [
        "",
        "---",
        "",
        "## Label Rationale",
        "",
        evaluation.get("label_rationale", ""),
        "",
        "---",
        "",
        "*Evaluated using: rule-based scoring (local, no API)*",
    ]

    return "\n".join(lines)


def _build_combined_markdown_report(
    submissions: list, evaluations: list, timestamp: str
) -> str:
    """Build a combined markdown report for 1–3 results."""
    lines = [
        "# Impact-Receipts Evaluation Report",
        f"**Generated:** {timestamp}",
        f"**Results evaluated:** {len(submissions)}",
        "",
        "---",
        "",
    ]
    for i, (sub, ev) in enumerate(zip(submissions, evaluations)):
        if len(submissions) > 1:
            lines.append(f"## Result {i + 1}")
            lines.append("")
        single = _build_markdown_report(sub, ev, timestamp)
        # Skip the shared header lines (title, generated, label, blank, ---, blank)
        body_lines = single.split("\n")[6:]
        lines.extend(body_lines)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Impact-Receipts",
        page_icon="✓",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    # Inject global CSS
    st.markdown(CSS, unsafe_allow_html=True)

    # Initialise session state
    _init_session_state()

    # Top progress bar
    screen = st.session_state["screen"]
    if screen == 1:
        st.progress(0.5, text="Submission Form")
    elif screen == 2:
        st.progress(1.0, text="Confidence Check Complete")

    # Screen dispatcher
    screen_renderers = {
        0: render_screen_0,
        1: render_screen_1,
        2: render_screen_2,
    }
    renderer = screen_renderers.get(screen, render_screen_0)
    renderer()


if __name__ == "__main__":
    main()
