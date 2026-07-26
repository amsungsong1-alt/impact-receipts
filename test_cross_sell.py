"""
test_cross_sell.py — golden tests for utils/cross_sell.py (Laudon Ch.9 CRM,
C7): behaviour-only recommendation selection, dedup, and outcome tracking.

No pytest, no network calls. Run with: python test_cross_sell.py
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.cross_sell as cross_sell

_NOW = datetime.now(timezone.utc)


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    cross_sell.Base.metadata.create_all(engine)
    return engine


def _profile(**overrides) -> dict:
    base = {
        "email": "x@example.com",
        "last_active_at": _NOW - timedelta(days=2),  # recent, so segment computation isn't "trial via no touch data"
        "signup_at": _NOW - timedelta(days=100),
        "total_assessments": 5,
        "assessments_last_30d": 5,
        "revision_count_last_30d": 1,
        "domain_user_count": 1,
        "distinct_donor_count_30d": 0,
        "active_in_equivalent_window_last_cycle": False,
    }
    base.update(overrides)
    return base


def run_recommend_behavior_only():
    failures = []

    # embedded segment (4+ assessments/30d) + real revision activity -> upgrade_to_subscription
    rec1 = cross_sell.recommend(_profile(email="heavy@example.com", assessments_last_30d=6, revision_count_last_30d=1))
    if rec1 != "upgrade_to_subscription":
        failures.append(f"expected upgrade_to_subscription for a heavy embedded user, got {rec1}")

    # org_emergent segment (2+ domain users) -> upgrade_to_org_plan
    rec2 = cross_sell.recommend(_profile(email="org@example.com", assessments_last_30d=1,
                                          revision_count_last_30d=0, domain_user_count=3))
    if rec2 != "upgrade_to_org_plan":
        failures.append(f"expected upgrade_to_org_plan for an org_emergent user, got {rec2}")

    # A light user with no distinguishing signal -> no recommendation invented.
    rec3 = cross_sell.recommend(_profile(email="light@example.com", total_assessments=1,
                                          assessments_last_30d=1, revision_count_last_30d=0))
    if rec3 is not None:
        failures.append(f"expected no recommendation for a plain light user, got {rec3!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: recommend() — behaviour-only recommendations, no invented recommendation "
          "for an undistinguished profile.")


def run_record_and_dedup():
    failures = []
    original_get_engine = cross_sell._get_engine
    engine = _fresh_engine()
    cross_sell._get_engine = lambda: engine
    email = "dedup@example.com"
    try:
        cross_sell.record_recommendation(email, "upgrade_to_subscription")
        cross_sell.record_recommendation(email, "upgrade_to_subscription")  # duplicate, must no-op

        with Session(engine) as session:
            count = session.query(cross_sell.CrossSellRecommendation).filter(
                cross_sell.CrossSellRecommendation.email == email).count()
        if count != 1:
            failures.append(f"expected exactly 1 row after a duplicate recommend, got {count}")

        pending = cross_sell.list_pending_recommendations()
        if not any(r["email"] == email for r in pending):
            failures.append("expected the recommendation to appear in list_pending_recommendations()")
    finally:
        cross_sell._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_recommendation — deduped against an unresolved duplicate, "
          "appears in list_pending_recommendations().")


def run_outcome_tracking():
    failures = []
    original_get_engine = cross_sell._get_engine
    engine = _fresh_engine()
    cross_sell._get_engine = lambda: engine
    email = "convert@example.com"
    try:
        cross_sell.record_recommendation(email, "upgrade_to_subscription")
        cross_sell.record_outcome_for_plan_label(email, "monthly")  # real conversion

        with Session(engine) as session:
            row = session.query(cross_sell.CrossSellRecommendation).filter(
                cross_sell.CrossSellRecommendation.email == email).first()
        if row.outcome != "converted":
            failures.append(f"expected outcome='converted' after a matching plan label, got {row.outcome!r}")
        if row.resolved_at is None:
            failures.append("expected resolved_at to be set once an outcome is recorded")

        # Resolved recommendations no longer appear in the pending list.
        pending = cross_sell.list_pending_recommendations()
        if any(r["email"] == email for r in pending):
            failures.append("a resolved recommendation should not appear in list_pending_recommendations()")

        # A non-matching plan label must not resolve a different recommendation type.
        cross_sell.record_recommendation(email, "upgrade_to_org_plan")
        cross_sell.record_outcome_for_plan_label(email, "monthly")  # doesn't match org plan's labels
        with Session(engine) as session:
            org_row = session.query(cross_sell.CrossSellRecommendation).filter(
                cross_sell.CrossSellRecommendation.email == email,
                cross_sell.CrossSellRecommendation.recommendation_type == "upgrade_to_org_plan").first()
        if org_row.outcome is not None:
            failures.append("a non-matching plan label should not resolve an unrelated recommendation type")
    finally:
        cross_sell._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_outcome_for_plan_label — correct conversion matching, "
          "resolved recommendations leave the pending list, non-matching labels don't cross-resolve.")


def run_no_engine_degradation():
    failures = []
    original_get_engine = cross_sell._get_engine
    cross_sell._get_engine = lambda: None
    try:
        cross_sell.record_recommendation("a@example.com", "upgrade_to_subscription")
        cross_sell.record_recommendation_outcome("a@example.com", "upgrade_to_subscription", "converted")
        cross_sell.record_outcome_for_plan_label("a@example.com", "monthly")
        if cross_sell.list_pending_recommendations() != []:
            failures.append("expected [] for list_pending_recommendations() with no engine configured")
    except Exception as exc:
        failures.append(f"cross_sell functions raised with no engine available: {exc!r}")
    finally:
        cross_sell._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-engine degradation — every write/read function degrades safely, never raises.")


if __name__ == "__main__":
    run_recommend_behavior_only()
    run_record_and_dedup()
    run_outcome_tracking()
    run_no_engine_degradation()
