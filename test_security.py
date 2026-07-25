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


if __name__ == "__main__":
    run_user_email_overwrite_guard()
    run_portfolio_heatmap_sample_gate()
