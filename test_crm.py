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


if __name__ == "__main__":
    run_log_event()
    run_agency_ready()
    run_build_segments()
    run_purge()
