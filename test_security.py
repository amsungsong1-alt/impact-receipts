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
import utils.assessment_links as assessment_links
from datetime import datetime, timedelta
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


def _synthetic_full_audits(n=15):
    """Synthetic _agency_full_audits()-shaped rows for exercising D4's three
    Agency Dashboard views without a real DB -- covers full/small-N/empty
    inputs across MIS/DSS/ESS render paths."""
    clients = ["Acme NGO", "Beta Trust", "— Unassigned —"]
    donors = ["USAID", "FCDO", "GIZ"]
    org_types = ["National NGO", "International NGO (INGO)"]
    ev_types = ["Attendance sheets / participant registers", "Tracer survey results"]
    rows = []
    for i in range(n):
        rows.append({
            "id": i, "ref_id": f"IMP-{i}", "created_at": datetime.now() - timedelta(days=30 * i),
            "donor": donors[i % 3], "sector": "Health", "org_type": org_types[i % 2],
            "client_id": i % 3, "client_name": clients[i % 3],
            "evidence_type": ev_types[i % 2],
            "confidence_score": 3.0 + (i % 5) * 0.3, "clarity_score": 3.0 + (i % 4) * 0.4,
            "confidence_components": {"direct_score": 1.2, "verify_score": 1.8, "recency_score": 0.8},
            "clarity_components": {"definition_score": 1.0, "measurement_score": 1.0, "integrity_score": 0.8,
                                    "scope_score": 0.5, "governance_score": 0.5},
            "beneficiary_voice_bonus": 0.3 if i % 2 == 0 else 0.0,
            "disaggregation_bonus": 0.15 if i % 3 == 0 else 0.0,
        })
    return rows


def run_agency_d4_views():
    """D4a/D4b/D4c -- the three new Agency Dashboard views (MIS/DSS/ESS)
    must render without raising across full data, below-MIN_PORTFOLIO_SAMPLE
    data, and empty input. ESS additionally needs a real utils.assessment_links
    engine swapped in for its Process/Learning panels."""
    failures = []
    original_get_engine = assessment_links._get_engine
    engine = create_engine("sqlite:///:memory:")
    assessment_links.Base.metadata.create_all(engine)
    assessment_links._get_engine = lambda: engine
    email = "agency@example.com"
    try:
        assessment_links.record_assessment(
            "ASM-1", email, confidence_score=2.5, clarity_score=3.0, weakest_dimension="Directness")
        assessment_links.record_assessment(
            "ASM-2", email, confidence_score=3.9, clarity_score=3.4, weakest_dimension="Recency",
            parent_assessment_id="ASM-1")

        full = _synthetic_full_audits(15)
        small = _synthetic_full_audits(3)

        for label, fn, args in [
            ("MIS/full", app._render_agency_mis_view, (full,)),
            ("MIS/small-N", app._render_agency_mis_view, (small,)),
            ("MIS/empty", app._render_agency_mis_view, ([],)),
            ("DSS/full", app._render_agency_dss_view, (full,)),
            ("DSS/small-N", app._render_agency_dss_view, (small,)),
            ("DSS/empty", app._render_agency_dss_view, ([],)),
            ("ESS/full", app._render_agency_ess_view, (full, email)),
            ("ESS/small-N", app._render_agency_ess_view, (small, email)),
            ("ESS/empty", app._render_agency_ess_view, ([], email)),
        ]:
            try:
                fn(*args)
            except Exception as exc:
                failures.append(f"{label} raised: {exc}")
    finally:
        assessment_links._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: Agency Dashboard D4 views (MIS/DSS/ESS) -- render without raising across full/small-N/empty input.")


class _FakeAdminUsersResult:
    def __init__(self, data):
        self.data = data


class _FakeAdminUsersQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}

    def select(self, *_a, **_kw):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters.items())]
        return _FakeAdminUsersResult(matched)


class _FakeAdminUsersClient:
    """Just enough of the supabase-py client shape for utils.db.get_user():
    c.table("users").select(...).eq("email", ...).execute().data."""
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "users"
        return _FakeAdminUsersQuery(self._rows)


def run_admin_rbac_gate():
    """Laudon Ch.9, C5: app._is_authorized_admin() -- the DB-backed second
    factor layered on top of the unchanged ADMIN_PASSPHRASE gate. Before
    this, the passphrase alone was sufficient for anyone who had it."""
    failures = []
    import utils.db as db
    original_get_client = db._get_client
    rows = [
        {"email": "admin@example.com", "is_admin": True},
        {"email": "regular@example.com", "is_admin": False},
        {"email": "legacy@example.com"},  # pre-migration-shaped row, no is_admin key at all
    ]
    db._get_client = lambda: _FakeAdminUsersClient(rows)
    try:
        if not app._is_authorized_admin("admin@example.com"):
            failures.append("expected an is_admin=true account to be authorized")
        if app._is_authorized_admin("regular@example.com"):
            failures.append("expected an is_admin=false account to be rejected")
        if app._is_authorized_admin("legacy@example.com"):
            failures.append("expected an account with no is_admin field to be rejected, not treated as admin")
        if app._is_authorized_admin("nobody@example.com"):
            failures.append("expected an unknown account to be rejected")
        if app._is_authorized_admin(""):
            failures.append("expected an empty email to be rejected, never raise")
    finally:
        db._get_client = original_get_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: admin RBAC gate -- is_admin=true required; false/missing/unknown/empty accounts all rejected.")


def run_admin_rbac_gate_role_tier():
    """Laudon Ch.8, C3: the role column (0050_users_role_and_totp.sql) is
    additive to is_admin, not a replacement -- either signal must grant
    access, so a legacy is_admin=true row with no role set (pre-migration
    shape) is never locked out, and a new role='admin'/'owner' row is
    authorized even if is_admin is false/missing (the post-migration
    shape, since the migration's own backfill sets both together in
    practice, but the check must not assume that)."""
    failures = []
    import utils.db as db
    original_get_client = db._get_client
    rows = [
        {"email": "role-admin@example.com", "role": "admin", "is_admin": False},
        {"email": "role-owner@example.com", "role": "owner", "is_admin": False},
        {"email": "role-user@example.com", "role": "user", "is_admin": False},
        {"email": "role-analyst@example.com", "role": "analyst", "is_admin": False},
    ]
    db._get_client = lambda: _FakeAdminUsersClient(rows)
    try:
        if not app._is_authorized_admin("role-admin@example.com"):
            failures.append("expected role='admin' to be authorized even with is_admin=false")
        if not app._is_authorized_admin("role-owner@example.com"):
            failures.append("expected role='owner' to be authorized even with is_admin=false")
        if app._is_authorized_admin("role-user@example.com"):
            failures.append("expected role='user' (default) to be rejected")
        if app._is_authorized_admin("role-analyst@example.com"):
            failures.append("expected role='analyst' (read-only tier, not yet wired to any admin "
                             "surface) to be rejected from the full admin dashboard")
    finally:
        db._get_client = original_get_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: admin RBAC gate role tier -- role IN ('admin','owner') authorizes "
          "independently of is_admin; 'user'/'analyst' do not.")


def run_admin_crm_behavioral_dashboard():
    """Laudon Ch.9, C5: the new behavioural CRM dashboard section must
    render without raising across seeded data and completely empty data."""
    failures = []
    import utils.crm as crm
    import utils.customer_profiles as customer_profiles
    import utils.api_pricing as api_pricing

    original_crm_engine = crm._get_engine
    original_cp_engine = customer_profiles._get_engine
    original_ap_engine = api_pricing._get_engine

    engine = create_engine("sqlite:///:memory:")
    crm.Base.metadata.create_all(engine)
    customer_profiles.Base.metadata.create_all(engine)
    api_pricing.Base.metadata.create_all(engine)
    crm._get_engine = lambda: engine
    customer_profiles._get_engine = lambda: engine
    api_pricing._get_engine = lambda: engine

    try:
        from sqlalchemy.orm import Session
        now = datetime.now()
        with Session(engine) as session:
            session.add(customer_profiles.CustomerProfile(
                email="a@example.com", plan="professional", subscription_status="active",
                signup_at=now - timedelta(days=100), last_active_at=now - timedelta(days=2),
                total_assessments=6, assessments_last_30d=5, revision_count_last_30d=1,
                lifetime_payment_count=3, lifetime_revenue_pesewas=15000,
                domain_user_count=1, distinct_donor_count_30d=1, computed_at=now,
            ))
            session.add(crm._PaymentRow(email="a@example.com", plan="monthly", status="success", created_at=now))
            session.add(api_pricing.ApiUsageLog(
                email="a@example.com", model="claude-sonnet-4-6", call_site="irc_extraction",
                input_tokens=1000, output_tokens=500, estimated_cost_pesewas=5.0,
            ))
            session.add(crm.CustomerSegmentHistory(email="a@example.com", segment="embedded"))
            session.commit()

        try:
            app._render_admin_crm_behavioral_dashboard()
        except Exception as exc:
            failures.append(f"full/seeded data raised: {exc}")

        # Empty-data pass -- fresh empty tables.
        empty_engine = create_engine("sqlite:///:memory:")
        crm.Base.metadata.create_all(empty_engine)
        customer_profiles.Base.metadata.create_all(empty_engine)
        api_pricing.Base.metadata.create_all(empty_engine)
        crm._get_engine = lambda: empty_engine
        customer_profiles._get_engine = lambda: empty_engine
        api_pricing._get_engine = lambda: empty_engine
        try:
            app._render_admin_crm_behavioral_dashboard()
        except Exception as exc:
            failures.append(f"empty data raised: {exc}")
    finally:
        crm._get_engine = original_crm_engine
        customer_profiles._get_engine = original_cp_engine
        api_pricing._get_engine = original_ap_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: behavioural CRM dashboard (C5) -- renders without raising across seeded and empty data.")


def run_concessional_checkout_params():
    """app._professional_checkout_params() -- the branch point deciding
    whether a Subscribe click gets the standard or concessional (CBO/
    Government, admin-approved-only) Professional plan/price. The db-layer
    request/approve/deny round-trip is tested in test_billing.py; this
    covers just the branching logic itself, reusing _FakeAdminUsersClient
    from the admin RBAC tests above since both only need get_user()."""
    failures = []
    import utils.db as db
    original_get_client = db._get_client
    original_plan_code = app._plan_code

    rows = [
        {"email": "approved@example.com", "concessional_status": "approved"},
        {"email": "requested@example.com", "concessional_status": "requested"},
        {"email": "standard@example.com", "concessional_status": "none"},
        {"email": "legacy@example.com"},  # pre-migration row, no concessional_status key at all
    ]
    db._get_client = lambda: _FakeAdminUsersClient(rows)
    # Fake plan codes for both tiers so the test doesn't depend on real
    # PAYSTACK_PLAN_* secrets being configured in this environment.
    app._plan_code = lambda secret_name: (
        "PLN_concessional_fake" if "CONCESSIONAL" in secret_name else "PLN_standard_fake"
    )
    try:
        _code, _price, _label = app._professional_checkout_params("approved@example.com")
        if _label != "concessional" or _code != "PLN_concessional_fake":
            failures.append(f"approved account should get concessional plan/label, got {(_code, _price, _label)!r}")
        if _price != int(app.PRICE_MONTHLY_GHS * 0.4):
            failures.append(f"concessional price should be 40% of PRICE_MONTHLY_GHS, got {_price!r}")

        for _email in ("requested@example.com", "standard@example.com", "legacy@example.com", "unknown@example.com", ""):
            _code, _price, _label = app._professional_checkout_params(_email)
            if _label != "monthly" or _code != "PLN_standard_fake" or _price != app.PRICE_MONTHLY_GHS:
                failures.append(f"{_email!r} (not approved) should get standard plan/price, got {(_code, _price, _label)!r}")

        # If the concessional Plan hasn't been provisioned in Paystack yet
        # (empty secret), an approved account must fall back to standard
        # pricing, never silently charge the standard price under the
        # "concessional" label.
        app._plan_code = lambda secret_name: "" if "CONCESSIONAL" in secret_name else "PLN_standard_fake"
        _code, _price, _label = app._professional_checkout_params("approved@example.com")
        if _label != "monthly" or _price != app.PRICE_MONTHLY_GHS:
            failures.append("an approved account should fall back to standard pricing when the concessional Plan isn't provisioned yet")
    finally:
        db._get_client = original_get_client
        app._plan_code = original_plan_code

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: concessional checkout params -- approved accounts get the discounted plan, everyone else gets standard, unprovisioned Plan degrades safely.")


if __name__ == "__main__":
    run_user_email_overwrite_guard()
    run_portfolio_heatmap_sample_gate()
    run_readiness_card_crosswalk_tags()
    run_verify_landing()
    run_agency_d4_views()
    run_admin_rbac_gate()
    run_admin_rbac_gate_role_tier()
    run_admin_crm_behavioral_dashboard()
    run_concessional_checkout_params()
