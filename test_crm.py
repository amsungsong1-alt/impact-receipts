"""
test_crm.py — golden tests for utils/crm.py (CRM events, Agency-ready
detection, account segmentation, and purge).

No pytest, no real network calls. Two different fakes are needed since
utils.crm.build_segments() spans two different DB-access paths:
  - crm_events itself is SQLAlchemy/direct-Postgres (utils.crm._get_engine())
    -- swapped for an in-memory SQLite engine, same approach as
    test_audits.py, since the same SQLAlchemy models work unchanged against
    either dialect.
  - utils.db.list_all_users() goes through the Supabase REST client
    (utils.db._get_client()) -- swapped for a minimal hand-rolled fake, same
    idea as test_billing.py's fake but pared down to just the one query
    shape list_all_users() actually issues (a plain .select().execute(),
    no filters).
Run with: python test_crm.py
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.crm as crm
from utils.metering import FREE_CHECKS_LIMIT


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    crm.Base.metadata.create_all(engine)
    return engine


class _FakeUsersResult:
    def __init__(self, data):
        self.data = data


class _FakeUsersQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_a, **_kw):
        return self

    def execute(self):
        return _FakeUsersResult(self._data)


class _FakeUsersClient:
    """Just enough of the supabase-py client shape for
    utils.db.list_all_users(): c.table("users").select(...).execute().data."""
    def __init__(self, users: list[dict]):
        self._users = users

    def table(self, name):
        assert name == "users"
        return _FakeUsersQuery(self._users)


def run_log_event():
    failures = []
    original_get_engine = crm._get_engine
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    try:
        crm.log_event("a@example.com", "bogus_event_type")
        with Session(engine) as session:
            count = session.query(crm.CrmEvent).count()
        if count != 0:
            failures.append("log_event inserted a row for an unrecognized event_type")

        crm.log_event("a@example.com", "signup")
        with Session(engine) as session:
            rows = session.query(crm.CrmEvent).filter(crm.CrmEvent.email == "a@example.com").all()
        if len(rows) != 1 or rows[0].event_type != "signup":
            failures.append(f"log_event did not insert a recognized event correctly: {rows}")

        # A missing engine must degrade silently, never raise.
        crm._get_engine = lambda: None
        try:
            crm.log_event("a@example.com", "signup")
            crm.log_audit_run("a@example.com", "USAID")
        except Exception as exc:
            failures.append(f"log_event/log_audit_run raised with no engine available: {exc}")
    finally:
        crm._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: log_event — allowlist enforcement, insert, and no-engine degradation verified.")


def run_agency_ready():
    failures = []
    original_get_engine = crm._get_engine
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    try:
        # 3+ audit_run events -> agency-ready via volume
        for _ in range(3):
            crm.log_event("heavy@example.com", "audit_run")

        # 2+ distinct donor frameworks -> agency-ready via breadth
        crm.log_event("multi@example.com", "framework_used", metadata={"donor": "USAID"})
        crm.log_event("multi@example.com", "framework_used", metadata={"donor": "FCDO"})

        # Only 1 of each -- must NOT qualify
        crm.log_event("neither@example.com", "audit_run")
        crm.log_event("neither@example.com", "framework_used", metadata={"donor": "GIZ"})

        ready = crm.agency_ready_emails()
        if "heavy@example.com" not in ready:
            failures.append("agency_ready_emails missed an account with 3+ audit_run events")
        if "multi@example.com" not in ready:
            failures.append("agency_ready_emails missed an account with 2+ distinct donor frameworks")
        if "neither@example.com" in ready:
            failures.append("agency_ready_emails flagged an account with only 1 audit_run and 1 framework")
    finally:
        crm._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: agency-ready — 3+ audit runs OR 2+ distinct donor frameworks correctly flag, neither alone does not.")


def run_build_segments():
    failures = []
    original_get_engine = crm._get_engine
    original_get_client = None
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as session:
            # churned@example.com: zero crm_events at all -> Churn-risk
            # professional@example.com: old activity AND recent activity ->
            # must land Professional (recent activity wins), not Churn-risk.
            session.add(crm.CrmEvent(email="professional@example.com", event_type="signup",
                                      created_at=now - timedelta(days=200)))
            session.add(crm.CrmEvent(email="professional@example.com", event_type="audit_run",
                                      created_at=now - timedelta(days=1)))
            # trial@example.com: recent activity, free_checks_used < limit
            session.add(crm.CrmEvent(email="trial@example.com", event_type="audit_run",
                                      created_at=now - timedelta(days=1)))
            # activefree@example.com: recent activity, free_checks_used >= limit,
            # AND 3+ audit_run events -> also agency_ready=True
            for _ in range(3):
                session.add(crm.CrmEvent(email="activefree@example.com", event_type="audit_run",
                                          created_at=now - timedelta(hours=1)))
            # stale@example.com: last activity 40 days ago -> Churn-risk despite plan
            session.add(crm.CrmEvent(email="stale@example.com", event_type="signup",
                                      created_at=now - timedelta(days=40)))
            session.commit()

        users = [
            {"email": "churned@example.com", "plan": "free", "free_checks_used": 0,
             "created_at": "2020-01-01", "subscription_status": None, "marketing_opt_out": False},
            {"email": "professional@example.com", "plan": "professional", "free_checks_used": 0,
             "created_at": "2020-01-01", "subscription_status": "active", "marketing_opt_out": False},
            {"email": "trial@example.com", "plan": "free", "free_checks_used": 1,
             "created_at": "2020-01-01", "subscription_status": None, "marketing_opt_out": False},
            {"email": "activefree@example.com", "plan": "free", "free_checks_used": FREE_CHECKS_LIMIT,
             "created_at": "2020-01-01", "subscription_status": None, "marketing_opt_out": False},
            {"email": "stale@example.com", "plan": "agency", "free_checks_used": 0,
             "created_at": "2020-01-01", "subscription_status": "active", "marketing_opt_out": False},
        ]

        import utils.db as db
        original_get_client = db._get_client
        db._get_client = lambda: _FakeUsersClient(users)

        segments = crm.build_segments()

        def _emails(seg):
            return {r["email"] for r in segments[seg]}

        if "churned@example.com" not in _emails("Churn-risk"):
            failures.append("build_segments: account with zero crm_events should be Churn-risk")
        if "stale@example.com" not in _emails("Churn-risk"):
            failures.append("build_segments: account inactive 40 days should be Churn-risk regardless of plan")
        if "professional@example.com" not in _emails("Professional"):
            failures.append("build_segments: recently-active professional account should be Professional, "
                             "not miscategorized due to old prior activity")
        if "trial@example.com" not in _emails("Trial"):
            failures.append("build_segments: free account under FREE_CHECKS_LIMIT should be Trial")
        if "activefree@example.com" not in _emails("Active-Free"):
            failures.append("build_segments: free account at/over FREE_CHECKS_LIMIT should be Active-Free")

        active_free_row = next((r for r in segments["Active-Free"] if r["email"] == "activefree@example.com"), None)
        if not active_free_row or not active_free_row["agency_ready"]:
            failures.append("build_segments: activefree@example.com has 3+ audit_run events "
                             "and should be flagged agency_ready across its own segment")
    finally:
        crm._get_engine = original_get_engine
        if original_get_client is not None:
            import utils.db as db
            db._get_client = original_get_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: build_segments — churn-risk priority, tier bucketing, Trial/Active-Free split, "
          "and cross-cutting agency_ready flag verified.")


def run_purge():
    failures = []
    original_get_engine = crm._get_engine
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    A, B = "purge_me@example.com", "keep_me@example.com"
    try:
        crm.log_event(A, "signup")
        crm.log_event(A, "audit_run")
        crm.log_event(B, "signup")

        deleted = crm.purge_account_crm_events(A)
        if deleted != 2:
            failures.append(f"purge_account_crm_events should report 2 deleted rows for A, got {deleted}")

        with Session(engine) as session:
            remaining_a = session.query(crm.CrmEvent).filter(crm.CrmEvent.email == A).count()
            remaining_b = session.query(crm.CrmEvent).filter(crm.CrmEvent.email == B).count()
        if remaining_a != 0:
            failures.append("purge_account_crm_events left rows behind for the purged account")
        if remaining_b != 1:
            failures.append("purge_account_crm_events affected a different account's rows")

        # An already-empty account must be a safe no-op, not an error.
        second = crm.purge_account_crm_events(A)
        if second != 0:
            failures.append(f"purging an already-empty account should report 0 deletions, got {second}")
    finally:
        crm._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: purge_account_crm_events — deletes only the target account's rows, safe to repeat.")


# ---------------------------------------------------------------------------
# Laudon Ch.9, C2/C3 -- behavioural segmentation and churn
# ---------------------------------------------------------------------------

_UTC_NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)
_TEST_CALENDAR = {"reporting_months": [6]}  # only June counts as a reporting window


def _profile(**overrides) -> dict:
    base = {
        "email": "x@example.com",
        "plan": "free",
        "subscription_status": None,
        "signup_at": _UTC_NOW - timedelta(days=200),
        "last_active_at": _UTC_NOW - timedelta(days=2),
        "total_assessments": 1,
        "assessments_last_30d": 1,
        "revision_count_last_30d": 0,
        "lifetime_payment_count": 0,
        "lifetime_revenue_pesewas": 0,
        "last_payment_status": None,
        "last_payment_at": None,
        "wa_conversation_count": 0,
        "last_wa_at": None,
        "email_domain": "example.com",
        "domain_user_count": 1,
        "distinct_donor_count_30d": 0,
        "active_in_equivalent_window_last_cycle": False,
        "computed_at": _UTC_NOW,
    }
    base.update(overrides)
    return base


def run_compute_behavioral_segment():
    failures = []

    def _check(name, profile, expected, now=_UTC_NOW):
        got = crm.compute_behavioral_segment(profile, _TEST_CALENDAR, now)
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    _check("lapsed (>=365 days, trumps everything)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=400), total_assessments=5), "lapsed")

    _check("at_risk (reporting month, quiet 45d, has history)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=45), total_assessments=5), "at_risk")

    # currently_reporting is judged by `now`'s month, not the touch date's --
    # use a March "now" (not in _TEST_CALENDAR's reporting_months=[6]).
    _march_now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _check("dormant_seasonal (off-season, quiet 45d, active same slot last cycle)", _profile(
        last_active_at=_march_now - timedelta(days=45),
        total_assessments=5, active_in_equivalent_window_last_cycle=True),
        "dormant_seasonal", now=_march_now)

    _check("org_emergent (2+ domain users)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=5), total_assessments=1, domain_user_count=3),
        "org_emergent")

    _check("org_emergent (3+ distinct donors in 30d)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=5), total_assessments=1, distinct_donor_count_30d=3),
        "org_emergent")

    _check("embedded (4+ assessments in 30d)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=5), total_assessments=6, assessments_last_30d=5),
        "embedded")

    _check("embedded (a single revision is the strongest signal on its own)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=5), total_assessments=3, revision_count_last_30d=1),
        "embedded")

    _check("episodic (2+ assessments, active recently, no other signal)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=10), total_assessments=3, assessments_last_30d=1),
        "episodic")

    _check("trial (fewer than 2 assessments)", _profile(
        last_active_at=_UTC_NOW - timedelta(days=2), total_assessments=1), "trial")

    _check("trial (no touch data at all degrades safely)", _profile(
        last_active_at=None, signup_at=None), "trial")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_behavioral_segment — all 7 segments plus the dormant_seasonal/at_risk "
          "boundary and no-touch-data degradation verified.")


def run_build_behavioral_segments():
    failures = []
    import utils.customer_profiles as customer_profiles
    original_list = customer_profiles.list_customer_profiles
    profiles = [
        _profile(email="lapsed@example.com", last_active_at=_UTC_NOW - timedelta(days=400), total_assessments=5),
        _profile(email="trial@example.com", last_active_at=_UTC_NOW - timedelta(days=1), total_assessments=1),
        _profile(email="embedded@example.com", last_active_at=_UTC_NOW - timedelta(days=1),
                 total_assessments=6, revision_count_last_30d=1),
    ]
    customer_profiles.list_customer_profiles = lambda: profiles
    try:
        segments = crm.build_behavioral_segments()
        emails = {seg: {p["email"] for p in rows} for seg, rows in segments.items()}
        if "lapsed@example.com" not in emails.get("lapsed", set()):
            failures.append("build_behavioral_segments: lapsed account missing from 'lapsed' bucket")
        if "trial@example.com" not in emails.get("trial", set()):
            failures.append("build_behavioral_segments: trial account missing from 'trial' bucket")
        if "embedded@example.com" not in emails.get("embedded", set()):
            failures.append("build_behavioral_segments: embedded account missing from 'embedded' bucket")
    finally:
        customer_profiles.list_customer_profiles = original_list

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: build_behavioral_segments — buckets every materialized profile correctly.")


def run_record_segment_transition():
    failures = []
    original_get_engine = crm._get_engine
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    email = "transitions@example.com"
    try:
        crm.record_segment_transition(email, "trial")
        crm.record_segment_transition(email, "trial")  # same segment -- must NOT insert a second row
        crm.record_segment_transition(email, "embedded")  # real transition -- must insert

        history = crm.list_segment_history(email)
        if len(history) != 2:
            failures.append(f"expected exactly 2 history rows (1 dedup skip), got {len(history)}: {history}")
        else:
            if history[0]["segment"] != "embedded" or history[1]["segment"] != "trial":
                failures.append(f"expected newest-first [embedded, trial], got {[h['segment'] for h in history]}")

        # Never raises without an engine.
        crm._get_engine = lambda: None
        crm.record_segment_transition(email, "lapsed")
        if crm.list_segment_history(email) != []:
            failures.append("list_segment_history should degrade to [] with no engine configured")
    finally:
        crm._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_segment_transition/list_segment_history — dedup on repeat segment, "
          "newest-first ordering, no-engine degradation verified.")


def run_compute_behavioral_churn_rate():
    failures = []
    import utils.customer_profiles as customer_profiles
    original_list = customer_profiles.list_customer_profiles
    # 3 lapsed (churned) + 7 healthy/recent (not churned) = 10, clears MIN_CHURN_SAMPLE.
    profiles = [
        _profile(email=f"lapsed{i}@example.com", last_active_at=_UTC_NOW - timedelta(days=400),
                 total_assessments=5)
        for i in range(3)
    ] + [
        _profile(email=f"healthy{i}@example.com", last_active_at=_UTC_NOW - timedelta(days=5),
                 total_assessments=5, assessments_last_30d=1)
        for i in range(7)
    ]
    customer_profiles.list_customer_profiles = lambda: profiles
    try:
        rate = crm.compute_behavioral_churn_rate()
        if rate != 0.3:
            failures.append(f"expected a 3/10 = 0.3 churn rate, got {rate}")

        # Below MIN_CHURN_SAMPLE -> None, not a rate from a near-empty cohort.
        customer_profiles.list_customer_profiles = lambda: profiles[:5]
        if crm.compute_behavioral_churn_rate() is not None:
            failures.append("expected None below MIN_CHURN_SAMPLE, got a rate")
    finally:
        customer_profiles.list_customer_profiles = original_list

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_behavioral_churn_rate — correct rate at full sample, "
          "None below MIN_CHURN_SAMPLE.")


def run_compute_revenue_churn_rate():
    failures = []
    original_get_engine = crm._get_engine
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    try:
        with Session(engine) as session:
            # 4 downgraded: subscribed once, most recent successful payment is per_use.
            for i in range(4):
                email = f"downgraded{i}@example.com"
                session.add(crm._PaymentRow(email=email, plan="monthly", status="success",
                                             created_at=_UTC_NOW - timedelta(days=100)))
                session.add(crm._PaymentRow(email=email, plan="per_use", status="success",
                                             created_at=_UTC_NOW - timedelta(days=5)))
            # 6 still subscribed: most recent successful payment is a subscription tier.
            for i in range(6):
                email = f"retained{i}@example.com"
                session.add(crm._PaymentRow(email=email, plan="monthly", status="success",
                                             created_at=_UTC_NOW - timedelta(days=100)))
                session.add(crm._PaymentRow(email=email, plan="monthly", status="success",
                                             created_at=_UTC_NOW - timedelta(days=5)))
            # A failed payment must not count as "most recent successful."
            session.add(crm._PaymentRow(email="retained0@example.com", plan="per_use", status="failed",
                                         created_at=_UTC_NOW - timedelta(days=1)))
            session.commit()

        rate = crm.compute_revenue_churn_rate()
        if rate != 0.4:
            failures.append(f"expected 4/10 = 0.4 revenue churn rate, got {rate}")

        # Never-subscribed accounts (pay-per-use only) must not enter the denominator.
        with Session(engine) as session:
            session.add(crm._PaymentRow(email="peruseonly@example.com", plan="per_use", status="success",
                                         created_at=_UTC_NOW))
            session.commit()
        rate2 = crm.compute_revenue_churn_rate()
        if rate2 != 0.4:
            failures.append(f"a pay-per-use-only account should not affect the rate, got {rate2}")
    finally:
        crm._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_revenue_churn_rate — derived entirely from payments history, "
          "correct rate, pay-per-use-only accounts excluded from the denominator.")


def run_time_to_second_assessment():
    failures = []
    original_get_engine = crm._get_engine
    engine = _fresh_engine()
    crm._get_engine = lambda: engine
    try:
        with Session(engine) as session:
            session.add(crm.CrmEvent(email="a@example.com", event_type="audit_run",
                                      created_at=_UTC_NOW - timedelta(days=10)))
            session.add(crm.CrmEvent(email="a@example.com", event_type="audit_run",
                                      created_at=_UTC_NOW - timedelta(days=4)))
            session.add(crm.CrmEvent(email="a@example.com", event_type="audit_run",
                                      created_at=_UTC_NOW))  # a 3rd run must not affect the result
            session.add(crm.CrmEvent(email="onerun@example.com", event_type="audit_run",
                                      created_at=_UTC_NOW))
            session.commit()

        days = crm.time_to_second_assessment("a@example.com")
        if days != 6:
            failures.append(f"expected 6 days between 1st and 2nd audit_run, got {days}")
        if crm.time_to_second_assessment("onerun@example.com") is not None:
            failures.append("expected None for an account with only 1 audit_run")
        if crm.time_to_second_assessment("nobody@example.com") is not None:
            failures.append("expected None for an account with 0 audit_run events")

        dist = crm.time_to_second_assessment_distribution()
        if dist != [6]:
            failures.append(f"expected the bulk distribution to be [6] (only 'a' qualifies), got {dist}")
    finally:
        crm._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: time_to_second_assessment/_distribution — correct day counts, ignores runs "
          "beyond the 2nd, None for accounts with fewer than 2 runs.")


if __name__ == "__main__":
    run_log_event()
    run_agency_ready()
    run_build_segments()
    run_purge()
    run_compute_behavioral_segment()
    run_build_behavioral_segments()
    run_record_segment_transition()
    run_compute_behavioral_churn_rate()
    run_compute_revenue_churn_rate()
    run_time_to_second_assessment()
