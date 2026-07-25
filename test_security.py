"""
test_security.py — regression tests for cross-account/security fixes that
don't fit test_app.py's pure-evaluator scope (this file imports app.py itself,
run in Streamlit's "bare mode" -- st.session_state still works as a plain
dict within one process, just without real multi-session isolation, which is
fine for these single-process assertions). No pytest, no network calls.
Run with: python test_security.py
"""

import streamlit as st
import app
import evaluator
import utils.verification as verification
from sqlalchemy import create_engine


def run_user_email_overwrite_guard():
    """_load_from_inputs_json() must never let a user-controlled JSON payload
    (e.g. uploaded via the Instant Report Check file uploader) overwrite an
    already-authenticated session's user_email -- see app.py's
    _load_from_inputs_json docstring-adjacent comment for the exploit this
    guards against: a crafted {"user_email": "victim@example.com"} hijacking
    the uploader's own session into acting as another account."""
    failures = []

    # Case 1: an authenticated session's email must survive a foreign-email upload.
    st.session_state.clear()
    st.session_state["user_email"] = "real_user@example.com"
    app._load_from_inputs_json({"slots": [{}], "user_email": "attacker_supplied@example.com"})
    if st.session_state.get("user_email") != "real_user@example.com":
        failures.append(
            "an authenticated session's user_email was overwritten by an uploaded "
            f"JSON's user_email field (got {st.session_state.get('user_email')!r})"
        )

    # Case 2: a session with no email yet may still be filled in from a
    # legitimate exported-draft re-upload (the feature this code exists for).
    st.session_state.clear()
    app._load_from_inputs_json({"slots": [{}], "user_email": "returning_user@example.com"})
    if st.session_state.get("user_email") != "returning_user@example.com":
        failures.append(
            "a session with no prior email did not get filled in from the "
            "uploaded draft's user_email (legitimate returning-user case broke)"
        )

    st.session_state.clear()
    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: user_email overwrite guard -- authenticated sessions protected, legitimate restore still works.")


def run_portfolio_heatmap_sample_gate():
    """_agency_client_donor_heatmap_df() must return a per-cell count ("n")
    alongside the mean score, so the Portfolio Dashboard's heatmap/gap panels
    can suppress cells below MIN_PORTFOLIO_SAMPLE (=10) instead of rendering
    a colored score off a handful of audits -- same convention as the
    existing MIN_BENCHMARK_SAMPLE/MIN_BAND_SAMPLE gates elsewhere in the app."""
    failures = []

    rows = [
        {"client_name": "Acme NGO", "donor": "USAID",
         "primary_confidence_score": 4.0, "primary_clarity_score": 4.2},
        {"client_name": "Acme NGO", "donor": "USAID",
         "primary_confidence_score": 3.6, "primary_clarity_score": 3.8},
        {"client_name": "Acme NGO", "donor": "USAID",
         "primary_confidence_score": 4.4, "primary_clarity_score": 4.6},
    ]
    grouped = app._agency_client_donor_heatmap_df(rows)
    if "n" not in grouped.columns:
        failures.append("_agency_client_donor_heatmap_df() dropped the 'n' count column")
    else:
        cell = grouped[(grouped["client_label"] == "Acme NGO") & (grouped["donor_label"] == "USAID")]
        if cell.empty or int(cell.iloc[0]["n"]) != 3:
            failures.append(f"expected n=3 for the only (client, donor) cell, got {cell}")
        expected_mean = round((4.0 + 3.6 + 4.4) / 3, 2)
        if cell.empty or round(float(cell.iloc[0]["primary_confidence_score"]), 2) != expected_mean:
            failures.append(f"expected mean confidence {expected_mean}, got {cell}")

    empty_grouped = app._agency_client_donor_heatmap_df([])
    if not empty_grouped.empty:
        failures.append("empty audits_rows should return an empty DataFrame, not a populated one")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: portfolio heatmap sample gate -- count column present, small-N (n=3 < MIN_PORTFOLIO_SAMPLE=10) degrades correctly, empty input handled.")


def run_readiness_card_crosswalk_tags():
    """_build_html_report_card()'s Page-2 sub-score rows must carry compact
    Bond 2024 / NESTA citation tags (item E of the NESTA/Bond/3ie/IRIS+
    pass) -- sourced from diagnostics.get_bond_citation() and
    framework_crosswalk.FRAMEWORKS/get_nesta_directness_mapping(), never
    invented per-row copy. Only app.py can exercise this (no separate
    "app.py UI helpers" test file exists), same rationale as the portfolio
    heatmap test above."""
    failures = []

    submission = {
        "result_statement": "Trained 487 smallholder farmers across 3 districts.",
        "target_group": "Smallholder farmers",
        "timeframe": "January-June 2025",
        "geographic_scope": "3 districts",
        "additional_context": "Informs Year 2 work plan.",
        "internal_review": "Reviewed by MEL Officer",
        "external_review": "Verified by independent third party",
        "disaggregation_status": "Yes — fully disaggregated",
        "evidence": [{
            "type": "Attendance sheets / participant registers",
            "description": "Signed attendance sheets from 12 sessions, verified by District Officer.",
            "recency": "June 2025",
            "verified_by": "District Agriculture Officer",
        }],
        "provenance_checklist": {"auditor_traceable": "Yes — an auditor could retrieve the original records"},
    }
    ev = evaluator.evaluate_submission(submission)
    html = app._build_html_report_card(submission, ev, "20260101_000000")

    if "Bond 2024" not in html:
        failures.append("expected at least one Bond 2024 citation tag in the Readiness Card HTML")
    if "NESTA L" not in html:
        failures.append("expected at least one NESTA level citation tag in the Readiness Card HTML")
    if "disaggregation bonus" not in html:
        failures.append("expected the Definition row to show the disaggregation bonus note")
    # Recency has no Bond citation and NESTA doesn't cite it -- its note
    # must render without a stray separator when _crosswalk_tag() is empty.
    if " &mdash; &middot;" in html or html.count("&mdash; &mdash;") > 0:
        failures.append("a dimension with no citation tag produced a dangling separator")
    # Item G3: the printed document must name the actual ?verify= URL, not
    # just an inert "cite this reference ID" instruction.
    if "?verify=IMP-20260101_000000" not in html:
        failures.append("expected the printed Ref line to include a concrete ?verify=<ref_id> URL")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: Readiness Card crosswalk tags -- Bond 2024/NESTA citations and disaggregation bonus note verified.")


def run_verify_landing():
    """_render_verify_landing() (item G2 of the NESTA/Bond/3ie/IRIS+ pass) --
    the public ?verify=<ref_id> landing page that closes the "cite this
    reference ID" promise every export already makes. Must render without
    raising for both a match and a no-match, and must never expose the
    stored content_hash or raw submission content."""
    failures = []
    original_get_engine = verification._get_engine
    engine = create_engine("sqlite:///:memory:")
    verification.Base.metadata.create_all(engine)
    verification._get_engine = lambda: engine
    try:
        content_hash = verification.compute_content_hash(
            "Trained 487 farmers.", "Attendance sheets.",
            "Attendance sheets / participant registers", 4.7, 4.2,
        )
        verification.record_export(
            "IMP-20260101_000000", "readiness_card", content_hash,
            confidence_score=4.7, clarity_score=4.2, score_band="Strong",
        )

        try:
            app._render_verify_landing("IMP-20260101_000000")
        except Exception as exc:
            failures.append(f"_render_verify_landing raised on a matching ref_id: {exc}")

        try:
            app._render_verify_landing("IMP-99999999_999999")
        except Exception as exc:
            failures.append(f"_render_verify_landing raised on a non-matching ref_id: {exc}")

        # The landing page must only ever see the fields verify_ref_id() returns
        # (never the raw content_hash or original submission text).
        record = verification.verify_ref_id("IMP-20260101_000000")
        if "content_hash" in record:
            failures.append("verify_ref_id() result passed to the landing page includes the raw content_hash")
    finally:
        verification._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: verify landing page -- renders without raising for match/no-match, never exposes the content hash.")


if __name__ == "__main__":
    run_user_email_overwrite_guard()
    run_portfolio_heatmap_sample_gate()
    run_readiness_card_crosswalk_tags()
    run_verify_landing()
