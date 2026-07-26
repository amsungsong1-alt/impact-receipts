"""
test_lifecycle_triggers.py — golden tests for utils/lifecycle_triggers.py
(Laudon Ch.9 CRM, C6): trigger eligibility, cooldown/dedup, and enable/disable.

No pytest, no network calls. Run with: python test_lifecycle_triggers.py
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.lifecycle_triggers as lifecycle_triggers


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    lifecycle_triggers.Base.metadata.create_all(engine)
    return engine


def _profile(**overrides) -> dict:
    base = {
        "total_assessments": 1,
        "revision_count_last_30d": 0,
        "subscription_status": None,
    }
    base.update(overrides)
    return base


def run_eligible_triggers_conditions():
    failures = []
    original_get_engine = lifecycle_triggers._get_engine
    lifecycle_triggers._get_engine = lambda: None  # has_fired_recently fails open to True... but
    # that would make everything ineligible -- use a real in-memory engine instead so
    # has_fired_recently correctly returns False for a fresh account.
    engine = _fresh_engine()
    lifecycle_triggers._get_engine = lambda: engine
    try:
        got = lifecycle_triggers.eligible_triggers(
            "a@example.com", _profile(total_assessments=1, revision_count_last_30d=0), "trial")
        if "first_assessment_no_engagement" not in got:
            failures.append("expected first_assessment_no_engagement for a 1-assessment, no-revision profile")

        got2 = lifecycle_triggers.eligible_triggers(
            "b@example.com", _profile(total_assessments=1, revision_count_last_30d=1), "embedded")
        if "first_assessment_no_engagement" in got2:
            failures.append("a profile that has already revised should NOT trigger first_assessment_no_engagement")

        got3 = lifecycle_triggers.eligible_triggers("c@example.com", _profile(), "org_emergent")
        if "org_emergent_detected" not in got3:
            failures.append("expected org_emergent_detected for an org_emergent segment")

        got4 = lifecycle_triggers.eligible_triggers(
            "d@example.com", _profile(subscription_status="attention"), "trial")
        if "payment_recovery" not in got4:
            failures.append("expected payment_recovery for subscription_status='attention'")

        got5 = lifecycle_triggers.eligible_triggers(
            "e@example.com", _profile(), "trial", delta_confidence=1.0, delta_clarity=1.0)
        if "testimonial_ask" not in got5:
            failures.append("expected testimonial_ask when combined delta clears the threshold")

        got6 = lifecycle_triggers.eligible_triggers(
            "f@example.com", _profile(), "trial", delta_confidence=0.2, delta_clarity=0.2)
        if "testimonial_ask" in got6:
            failures.append("testimonial_ask should not fire below the combined delta threshold")
    finally:
        lifecycle_triggers._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: eligible_triggers — all 4 Python-fired trigger conditions verified.")


def run_cooldown_and_dedup():
    failures = []
    original_get_engine = lifecycle_triggers._get_engine
    engine = _fresh_engine()
    lifecycle_triggers._get_engine = lambda: engine
    email = "cooldown@example.com"
    try:
        got_before = lifecycle_triggers.eligible_triggers(email, _profile(), "org_emergent")
        if "org_emergent_detected" not in got_before:
            failures.append("expected org_emergent_detected to be eligible before it's ever fired")

        lifecycle_triggers.record_trigger_fired(email, "org_emergent_detected")

        got_after = lifecycle_triggers.eligible_triggers(email, _profile(), "org_emergent")
        if "org_emergent_detected" in got_after:
            failures.append("org_emergent_detected should not re-fire within its cooldown window")

        # Simulate a fire outside the cooldown window by inserting an old row directly.
        with Session(engine) as session:
            old = lifecycle_triggers.LifecycleTriggerLog(
                email="old@example.com", trigger_name="org_emergent_detected",
                fired_at=datetime.now(timezone.utc) - timedelta(days=999),
            )
            session.add(old)
            session.commit()
        got_old = lifecycle_triggers.eligible_triggers("old@example.com", _profile(), "org_emergent")
        if "org_emergent_detected" not in got_old:
            failures.append("expected org_emergent_detected to be eligible again once the cooldown has passed")
    finally:
        lifecycle_triggers._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: cooldown/dedup — a trigger doesn't refire within its cooldown, "
          "does refire once the cooldown has passed.")


def run_disabled_trigger_never_fires():
    failures = []
    original_get_engine = lifecycle_triggers._get_engine
    engine = _fresh_engine()
    lifecycle_triggers._get_engine = lambda: engine
    original_enabled = lifecycle_triggers.TRIGGERS["org_emergent_detected"]["enabled"]
    lifecycle_triggers.TRIGGERS["org_emergent_detected"]["enabled"] = False
    try:
        got = lifecycle_triggers.eligible_triggers("g@example.com", _profile(), "org_emergent")
        if "org_emergent_detected" in got:
            failures.append("a disabled trigger must never appear in eligible_triggers()")
    finally:
        lifecycle_triggers.TRIGGERS["org_emergent_detected"]["enabled"] = original_enabled
        lifecycle_triggers._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a disabled trigger (Section D's individually-disableable acceptance criterion) "
          "never fires.")


def run_fail_open_and_no_engine_degradation():
    failures = []
    original_get_engine = lifecycle_triggers._get_engine
    lifecycle_triggers._get_engine = lambda: None
    try:
        # has_fired_recently fails open to True with no engine -- nothing should fire.
        got = lifecycle_triggers.eligible_triggers("h@example.com", _profile(), "org_emergent")
        if got != []:
            failures.append(f"expected no eligible triggers with no engine configured, got {got}")
        lifecycle_triggers.record_trigger_fired("h@example.com", "org_emergent_detected")  # must not raise
    except Exception as exc:
        failures.append(f"lifecycle_triggers functions raised with no engine available: {exc!r}")
    finally:
        lifecycle_triggers._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-engine degradation — has_fired_recently fails open (nothing fires), "
          "record_trigger_fired never raises.")


if __name__ == "__main__":
    run_eligible_triggers_conditions()
    run_cooldown_and_dedup()
    run_disabled_trigger_never_fires()
    run_fail_open_and_no_engine_degradation()
