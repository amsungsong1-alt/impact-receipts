"""
test_customer_profiles.py — golden tests for utils/customer_profiles.py
(Laudon Ch.9 CRM, C1): read-only access to the customer_profiles table.

This module never assembles a profile itself (that's refresh_customer_profiles(),
a Postgres-only SQL function this offline suite can't exercise against
SQLite) -- these tests only cover the read path: get_customer_profile()/
list_customer_profiles() reading correctly, and degrading safely with no
engine configured. No pytest, no network calls. Run with:
python test_customer_profiles.py
"""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.customer_profiles as customer_profiles


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    customer_profiles.Base.metadata.create_all(engine)
    return engine


def run_get_and_list_customer_profile():
    failures = []
    original_get_engine = customer_profiles._get_engine
    engine = _fresh_engine()
    customer_profiles._get_engine = lambda: engine
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    try:
        with Session(engine) as session:
            session.add(customer_profiles.CustomerProfile(
                email="a@example.com", plan="professional", subscription_status="active",
                signup_at=now, last_active_at=now, total_assessments=10,
                assessments_last_30d=3, revision_count_last_30d=1,
                lifetime_payment_count=6, lifetime_revenue_pesewas=300000,
                last_payment_status="success", last_payment_at=now,
                wa_conversation_count=2, last_wa_at=now, email_domain="example.com",
                domain_user_count=1, distinct_donor_count_30d=1,
                active_in_equivalent_window_last_cycle=False, computed_at=now,
            ))
            session.add(customer_profiles.CustomerProfile(email="b@example.com", plan="free", computed_at=now))
            session.commit()

        row = customer_profiles.get_customer_profile("a@example.com")
        if row is None:
            failures.append("get_customer_profile returned None for an account that exists")
        else:
            if row["plan"] != "professional" or row["total_assessments"] != 10:
                failures.append(f"get_customer_profile returned wrong data: {row}")

        if customer_profiles.get_customer_profile("nobody@example.com") is not None:
            failures.append("get_customer_profile should return None for an unknown account")
        if customer_profiles.get_customer_profile("") is not None:
            failures.append("get_customer_profile should return None for an empty email")

        rows = customer_profiles.list_customer_profiles()
        if len(rows) != 2:
            failures.append(f"expected 2 profiles, got {len(rows)}")

        # A row with only defaulted fields must still read back with the
        # int/bool coalescing this module promises (never None where a
        # count/flag is expected).
        b_row = next((r for r in rows if r["email"] == "b@example.com"), None)
        if b_row is None or b_row["total_assessments"] != 0 or b_row["domain_user_count"] != 1:
            failures.append(f"defaulted-field coalescing broke for a sparsely-populated row: {b_row}")
    finally:
        customer_profiles._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: get_customer_profile/list_customer_profiles — correct reads, unknown/empty "
          "email handling, and defaulted-field coalescing verified.")


def run_no_engine_degradation():
    failures = []
    original_get_engine = customer_profiles._get_engine
    customer_profiles._get_engine = lambda: None
    try:
        if customer_profiles.get_customer_profile("a@example.com") is not None:
            failures.append("get_customer_profile should return None with no engine configured")
        if customer_profiles.list_customer_profiles() != []:
            failures.append("list_customer_profiles should return [] with no engine configured")
    except Exception as exc:
        failures.append(f"customer_profiles read functions raised with no engine available: {exc!r}")
    finally:
        customer_profiles._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-engine degradation — get_customer_profile/list_customer_profiles never raise.")


if __name__ == "__main__":
    run_get_and_list_customer_profile()
    run_no_engine_degradation()
