"""
app.py — Impact-Receipts: Pre-submission confidence check for MEL Managers.

Run with:  streamlit run app.py

Five-step wizard driven by st.session_state["step"] (0–4):
  0  Onboarding
  1  Result Claim
  2  Evidence
  3  Review & Context
  4  Evaluation Results

The Claude API is called exactly once, on first entry to step 4.
All submission data and outputs are saved locally to inputs/, evaluations/, outputs/.
"""

import json
import os
import re
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------------------------
# Evidence type options shown in the Step 2 selectbox
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

# ---------------------------------------------------------------------------
# Step 0 — Onboarding
# ---------------------------------------------------------------------------

def render_step_0():
    st.title("Impact-Receipts")
    st.markdown("#### Stress-test a result before you submit it.")

    st.markdown("""
This tool evaluates one reported result across three dimensions:

- **Clarity of Claim** — Does it specify a measurable unit, timeframe, and target group?
- **Strength of Evidence** — Is the evidence direct, recent, and verifiable?
- **Independent Review** — Has it been peer-reviewed internally or externally?

You receive a confidence label (**Strong / Moderate / Weak / Incomplete**) plus a
specific checklist of what to fix before submission.
""")

    st.info(
        "**What this is NOT:** a full reporting system, a database, or a publishing tool.  \n"
        "All data stays on your machine. Nothing is stored online."
    )

    st.warning(
        "This tool evaluates **only** what you provide. "
        "It never invents or assumes missing data."
    )

    st.divider()
    if st.button("Start Evaluation", type="primary", use_container_width=True):
        st.session_state["step"] = 1
        st.session_state["submission"] = {}
        st.session_state["evidence_items"] = []
        st.session_state["evaluation"] = None
        st.session_state["saved_paths"] = {}
        st.session_state["error_message"] = None
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Result Claim
# ---------------------------------------------------------------------------

def render_step_1():
    st.header("Step 1 of 3 — The Result Claim")
    st.caption(
        "Be as specific as possible. "
        "Vague claims score lower even if the underlying work was strong."
    )

    with st.form("claim_form"):
        result_statement = st.text_area(
            "Result Statement *",
            height=110,
            value=st.session_state["submission"].get("result_statement", ""),
            placeholder=(
                "e.g.  1,240 smallholder farmers in Kwara State, Nigeria adopted "
                "improved seed varieties between January and June 2024."
            ),
            help="What was achieved? Include a number, a group, a place, and a timeframe.",
        )

        col1, col2 = st.columns(2)
        with col1:
            target_group = st.text_input(
                "Target Group",
                value=st.session_state["submission"].get("target_group", ""),
                placeholder="e.g.  Female smallholder farmers (< 2 ha)",
                help="Who benefited or was directly reached?",
            )
            timeframe = st.text_input(
                "Timeframe",
                value=st.session_state["submission"].get("timeframe", ""),
                placeholder="e.g.  January–June 2024",
                help="What calendar period does this result cover?",
            )
        with col2:
            geographic_scope = st.text_input(
                "Geographic Scope",
                value=st.session_state["submission"].get("geographic_scope", ""),
                placeholder="e.g.  Kwara State, Nigeria",
                help="Where did this take place?",
            )

        submitted = st.form_submit_button(
            "Next: Add Evidence →", type="primary", use_container_width=True
        )

        if submitted:
            if not result_statement.strip():
                st.error("Result Statement is required. Please describe what was achieved.")
            else:
                st.session_state["submission"].update(
                    {
                        "result_statement": result_statement.strip(),
                        "target_group": target_group.strip() or "Not specified",
                        "timeframe": timeframe.strip() or "Not specified",
                        "geographic_scope": geographic_scope.strip() or "Not specified",
                    }
                )
                st.session_state["step"] = 2
                st.rerun()


# ---------------------------------------------------------------------------
# Step 2 — Evidence
# ---------------------------------------------------------------------------

def render_step_2():
    st.header("Step 2 of 3 — Supporting Evidence")
    st.caption(
        "Add the evidence you have. Be specific about what it is, "
        "when it was collected, and who verified it. Up to 5 items."
    )

    # Add-item button is outside any form so it triggers immediately
    if len(st.session_state["evidence_items"]) < 5:
        if st.button("+ Add Evidence Item", use_container_width=False):
            st.session_state["evidence_items"].append(
                {"type": EVIDENCE_TYPES[0], "description": "", "recency": "", "verified_by": ""}
            )
            st.rerun()

    if not st.session_state["evidence_items"]:
        st.warning(
            "No evidence added yet.  \n"
            "You can proceed without evidence — but the result will very likely "
            "score **Incomplete** on Strength of Evidence."
        )

    # Render each evidence item in an expander
    indices_to_remove = []
    for i, item in enumerate(st.session_state["evidence_items"]):
        with st.expander(f"Evidence Item {i + 1}  —  {item['type']}", expanded=True):
            col_type, col_remove = st.columns([5, 1])
            with col_type:
                item["type"] = st.selectbox(
                    "Evidence Type",
                    EVIDENCE_TYPES,
                    index=EVIDENCE_TYPES.index(item["type"]),
                    key=f"ev_type_{i}",
                )
            with col_remove:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Remove", key=f"ev_remove_{i}"):
                    indices_to_remove.append(i)

            item["description"] = st.text_area(
                "Description",
                value=item["description"],
                height=80,
                placeholder=(
                    "e.g.  Paper attendance registers collected at 12 training sessions, "
                    "listing all 1,240 participants by name, village, and phone number."
                ),
                key=f"ev_desc_{i}",
            )

            col_rec, col_ver = st.columns(2)
            with col_rec:
                item["recency"] = st.text_input(
                    "Date / Recency",
                    value=item["recency"],
                    placeholder="e.g.  June 2024",
                    key=f"ev_rec_{i}",
                )
            with col_ver:
                item["verified_by"] = st.text_input(
                    "Verified / Collected by",
                    value=item["verified_by"],
                    placeholder="e.g.  Field M&E Officer",
                    key=f"ev_ver_{i}",
                )

    # Process removals after the render loop
    if indices_to_remove:
        for idx in sorted(indices_to_remove, reverse=True):
            st.session_state["evidence_items"].pop(idx)
        st.rerun()

    st.divider()
    col_back, col_next = st.columns([1, 3])
    with col_back:
        if st.button("← Back", use_container_width=True):
            st.session_state["step"] = 1
            st.rerun()
    with col_next:
        if st.button("Next: Review & Submit →", type="primary", use_container_width=True):
            st.session_state["submission"]["evidence"] = list(
                st.session_state["evidence_items"]
            )
            st.session_state["step"] = 3
            st.rerun()


# ---------------------------------------------------------------------------
# Step 3 — Review & Context
# ---------------------------------------------------------------------------

def render_step_3():
    st.header("Step 3 of 3 — Review Status & Context")

    with st.form("review_form"):
        internal_review = st.selectbox(
            "Internal Review Status",
            [
                "Not reviewed",
                "Reviewed by M&E Officer",
                "Reviewed by Program Manager",
                "Reviewed by senior leadership or board",
                "Reviewed by multiple internal stakeholders",
            ],
            index=0,
            help="Who inside your organisation has checked this result?",
        )

        external_review = st.selectbox(
            "External / Independent Review",
            [
                "No external review",
                "Reviewed by partner organisation",
                "Reviewed by independent evaluator",
                "Reviewed by donor representative",
                "Third-party audit completed",
            ],
            index=0,
            help="Has anyone outside your organisation reviewed this result?",
        )

        additional_context = st.text_area(
            "Additional Context (optional)",
            height=80,
            placeholder=(
                "Any caveats, limitations, methodology notes, or context "
                "the evaluator should know."
            ),
        )

        # Preview of what will be submitted
        st.divider()
        st.subheader("Your Submission Summary")
        sub = st.session_state["submission"]
        st.markdown(f"**Result:** {sub.get('result_statement', '—')}")
        st.markdown(
            f"**Target Group:** {sub.get('target_group', '—')}  |  "
            f"**Timeframe:** {sub.get('timeframe', '—')}  |  "
            f"**Location:** {sub.get('geographic_scope', '—')}"
        )
        n_ev = len(st.session_state.get("evidence_items", []))
        st.markdown(
            f"**Evidence items:** {n_ev}"
            + ("  — *(none added)*" if n_ev == 0 else "")
        )

        st.divider()
        col_back, col_submit = st.columns([1, 3])
        with col_back:
            back = st.form_submit_button("← Back", use_container_width=True)
        with col_submit:
            submit = st.form_submit_button(
                "Evaluate This Result", type="primary", use_container_width=True
            )

        if back:
            st.session_state["step"] = 2
            st.rerun()

        if submit:
            st.session_state["submission"].update(
                {
                    "internal_review": internal_review,
                    "external_review": external_review,
                    "additional_context": additional_context.strip() or None,
                }
            )
            st.session_state["evaluation"] = None  # clear any prior result
            st.session_state["step"] = 4
            st.rerun()


# ---------------------------------------------------------------------------
# Step 4 — Evaluation Results
# ---------------------------------------------------------------------------

def render_step_4():
    st.header("Evaluation Results")

    # ---- Run evaluation exactly once ----------------------------------------
    if not st.session_state.get("evaluation"):
        with st.spinner("Running evaluation…"):
            try:
                from evaluator import evaluate_submission, compute_confidence_label

                evaluation = evaluate_submission(st.session_state["submission"])
                st.session_state["evaluation"] = evaluation
                st.session_state["saved_paths"] = save_all_files(
                    st.session_state["submission"], evaluation
                )
            except Exception as exc:
                st.session_state["error_message"] = (
                    f"An unexpected error occurred:\n\n{exc}\n\nPlease try again."
                )
                st.session_state["evaluation"] = {}

    # ---- Error state --------------------------------------------------------
    if st.session_state.get("error_message"):
        st.error(st.session_state["error_message"])
        if st.button("← Go Back and Try Again"):
            st.session_state["step"] = 3
            st.session_state["evaluation"] = None
            st.session_state["error_message"] = None
            st.rerun()
        return

    ev = st.session_state["evaluation"]
    scores = ev.get("scores", {})

    from evaluator import compute_confidence_label

    label, color = compute_confidence_label(scores)

    # ---- Section 1: Confidence Snapshot ------------------------------------
    st.markdown("---")
    st.markdown(
        f"<div style='background:{color};padding:20px 24px;border-radius:10px;"
        f"text-align:center;'>"
        f"<h2 style='color:white;margin:0 0 6px 0;letter-spacing:1px;'>{label}</h2>"
        f"<p style='color:rgba(255,255,255,0.92);margin:0;font-size:0.95rem;'>"
        f"{ev.get('label_rationale', '')}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )


    # ---- Section 2: Dimension Scores ----------------------------------------
    st.markdown("---")
    st.subheader("Dimension Breakdown")

    dim_config = [
        ("clarity_of_claim", "Clarity of Claim", "Is the unit, timeframe, and target group explicit?"),
        ("strength_of_evidence", "Strength of Evidence", "Is the evidence direct, recent, and verified?"),
        ("independent_review", "Independent Review", "Has it been peer-reviewed?"),
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
                with st.expander("Rationale"):
                    st.write(rationale)
            missing = dim.get("missing_elements", [])
            if missing:
                for m in missing:
                    st.markdown(f"- {m}")

    # ---- Section 3: Key Issues ----------------------------------------------
    st.markdown("---")
    st.subheader("Key Issues Identified")
    key_issues = ev.get("key_issues", [])
    if key_issues:
        for issue in key_issues:
            st.markdown(f"- {issue}")
    else:
        st.success("No major issues identified.")

    # ---- Section 4: What To Fix ---------------------------------------------
    st.markdown("---")
    st.subheader("What to Fix Before Submission")
    fixes = ev.get("fixes", [])
    if fixes:
        st.caption("Check each item off as you address it.")
        for i, fix in enumerate(fixes):
            st.checkbox(fix, value=False, key=f"fix_{i}_{fix[:20]}")
    else:
        st.success("No specific fixes required.")

    # ---- Section 5: Actions -------------------------------------------------
    st.markdown("---")
    col_new, col_dl = st.columns(2)

    with col_new:
        if st.button("Start a New Evaluation", type="primary", use_container_width=True):
            for key in ["evaluation", "submission", "evidence_items",
                        "saved_paths", "error_message"]:
                st.session_state.pop(key, None)
            st.session_state["step"] = 0
            st.rerun()

    with col_dl:
        output_path = st.session_state.get("saved_paths", {}).get("output")
        if output_path and os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            st.download_button(
                label="Download Report (.md)",
                data=report_text,
                file_name=os.path.basename(output_path),
                mime="text/markdown",
                use_container_width=True,
            )



# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------

def save_all_files(submission: dict, evaluation: dict) -> dict:
    """
    Save input JSON, full evaluation JSON, and a markdown report to disk.
    Creates directories if they don't exist.
    Returns dict of file paths: {"input": ..., "evaluation": ..., "output": ...}.
    """
    os.makedirs("inputs", exist_ok=True)
    os.makedirs("evaluations", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _make_slug(submission.get("result_statement", "result"))
    base = f"{timestamp}_{slug}"

    paths = {
        "input":      os.path.join("inputs",      f"{base}_input.json"),
        "evaluation": os.path.join("evaluations", f"{base}_evaluation.json"),
        "output":     os.path.join("outputs",     f"{base}_report.md"),
    }

    with open(paths["input"], "w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2, ensure_ascii=False)

    # Strip internal debug keys before saving
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
    label = evaluation.get("overall_label", "Unknown")

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
        "clarity_of_claim": "Clarity of Claim",
        "strength_of_evidence": "Strength of Evidence",
        "independent_review": "Independent Review",
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

    lines += [
        "---",
        "",
        "## Key Issues",
        "",
    ]
    for issue in evaluation.get("key_issues", []):
        lines.append(f"- {issue}")

    lines += [
        "",
        "---",
        "",
        "## What to Fix",
        "",
    ]
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
        f"*Evaluated using: rule-based scoring (local, no API)*",
    ]

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

    # Initialise session state keys on first load
    defaults = {
        "step": 0,
        "submission": {},
        "evidence_items": [],
        "evaluation": None,
        "saved_paths": {},
        "error_message": None,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # Progress bar (visible during steps 1–4)
    step = st.session_state["step"]
    if step > 0:
        progress_map = {1: 0.25, 2: 0.5, 3: 0.75, 4: 1.0}
        label_map = {1: "Step 1 of 3", 2: "Step 2 of 3", 3: "Step 3 of 3", 4: "Complete"}
        st.progress(progress_map.get(step, 0), text=label_map.get(step, ""))

    step_renderers = {
        0: render_step_0,
        1: render_step_1,
        2: render_step_2,
        3: render_step_3,
        4: render_step_4,
    }
    renderer = step_renderers.get(step, render_step_0)
    renderer()


if __name__ == "__main__":
    main()
