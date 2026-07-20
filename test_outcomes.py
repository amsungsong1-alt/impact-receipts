"""
test_outcomes.py — golden tests for utils/outcomes.py (outcome feedback loop: scheduling a
donor-acceptance follow-up at download time, answering/skipping it on a later visit, and the
admin acceptance-rate-by-band report).

No pytest, no real network calls: utils.outcomes's own SQLAlchemy engine abstraction is the
seam to swap -- an in-memory SQLite engine stands in for the real Supabase Postgres
connection, same approach as test_audits.py/test_crm.py, since the same SQLAlchemy models
work unchanged against either dialect. Run with: python test_outcomes.py
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.outcomes as outcomes


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    outcomes.Base.metadata.create_all(engine)
    return engine


def run_schedule_and_fetch():
    failures = []
    original_get_engine = outcomes._get_engine
    engine = _fresh_engine()
    outcomes._get_engine = lambda: engine
    email = "mel@example.com"
    try:
        outcomes.schedule_followup("IMP-1", email, "readiness_card",
                                    confidence_score=2.4, clarity_score=3.1, score_band="Weak")
        if outcomes.schedule_followup("IMP-2", email, "not_a_real_export_type") is not None:
            pass  # schedule_followup returns None always; verify via row count instead
        with Session(engine) as session:
            count = session.query(outcomes.OutcomeFeedback).count()
        if count != 1:
            failures.append(f"schedule_followup should reject an unrecognized export_type "
                             f"(expected 1 row total, got {count})")

        pending = outcomes.get_pending_followup(email)
        if not pending or pending["ref_id"] != "IMP-1" or pending["export_type"] != "readiness_card":
            failures.append(f"get_pending_followup did not return the scheduled row: {pending}")

        # A different email (different hash) must not see this pending item.
        if outcomes.get_pending_followup("someone_else@example.com") is not None:
            failures.append("get_pending_followup leaked a row across different email hashes")

        # Oldest-pending-first: schedule a second item, confirm the first is still returned.
        outcomes.schedule_followup("IMP-3", email, "audit_excel", score_band="Strong")
        still_first = outcomes.get_pending_followup(email)
        if still_first["ref_id"] != "IMP-1":
            failures.append(f"get_pending_followup should return the oldest pending item, got {still_first}")
    finally:
        outcomes._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: schedule_followup/get_pending_followup — allowlist enforcement, hash "
          "isolation, and oldest-first ordering verified.")


def run_record_and_skip():
    failures = []
    original_get_engine = outcomes._get_engine
    engine = _fresh_engine()
    outcomes._get_engine = lambda: engine
    email = "mel@example.com"
    try:
        outcomes.schedule_followup("IMP-A", email, "readiness_card", score_band="Strong")
        pending = outcomes.get_pending_followup(email)
        fb_id = pending["id"]

        # A different email's hash must not be able to answer this row.
        if outcomes.record_response(fb_id, "attacker@example.com", "Accepted"):
            failures.append("record_response succeeded with the wrong email's hash")
        if outcomes.get_pending_followup(email) is None:
            failures.append("a failed cross-hash record_response should not have consumed the row")

        # An invalid response value must be rejected.
        if outcomes.record_response(fb_id, email, "Definitely maybe"):
            failures.append("record_response accepted a response outside RESPONSE_OPTIONS")

        # The real owner answering correctly should succeed and clear it from pending.
        if not outcomes.record_response(fb_id, email, "Accepted"):
            failures.append("record_response failed for the correct email hash and a valid response")
        if outcomes.get_pending_followup(email) is not None:
            failures.append("an answered row should no longer be returned by get_pending_followup")

        # Answering the same row twice must not succeed (already 'answered', not 'pending').
        if outcomes.record_response(fb_id, email, "Rejected"):
            failures.append("record_response allowed answering an already-answered row a second time")

        # skip_followup: a second item, skipped rather than answered, must also disappear.
        outcomes.schedule_followup("IMP-B", email, "audit_excel", score_band="Weak")
        pending_b = outcomes.get_pending_followup(email)
        if not outcomes.skip_followup(pending_b["id"], email):
            failures.append("skip_followup failed for a valid pending row and matching hash")
        if outcomes.get_pending_followup(email) is not None:
            failures.append("a skipped row should no longer be returned by get_pending_followup")
    finally:
        outcomes._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: record_response/skip_followup — hash-based ownership check, response "
          "validation, and permanent dismissal verified.")


def run_acceptance_stats():
    failures = []
    original_get_engine = outcomes._get_engine
    engine = _fresh_engine()
    outcomes._get_engine = lambda: engine
    try:
        # Strong band: 12 decided (9 accepted, 2 revisions, 1 rejected) + 3 not-yet-submitted
        # -- at/above MIN_BAND_SAMPLE, so a rate should be shown.
        for i in range(9):
            outcomes.schedule_followup(f"S-{i}", f"strong{i}@example.com", "readiness_card", score_band="Strong")
        for i in range(2):
            outcomes.schedule_followup(f"S-r{i}", f"strongr{i}@example.com", "readiness_card", score_band="Strong")
        outcomes.schedule_followup("S-rej", "strongrej@example.com", "readiness_card", score_band="Strong")
        for i in range(3):
            outcomes.schedule_followup(f"S-ny{i}", f"strongny{i}@example.com", "readiness_card", score_band="Strong")

        # Weak band: only 3 decided -- below MIN_BAND_SAMPLE, rate must be withheld (None).
        for i in range(2):
            outcomes.schedule_followup(f"W-{i}", f"weak{i}@example.com", "readiness_card", score_band="Weak")
        outcomes.schedule_followup("W-rej", "weakrej@example.com", "readiness_card", score_band="Weak")

        with Session(engine) as session:
            rows = session.query(outcomes.OutcomeFeedback).all()
            for r in rows:
                if r.ref_id.startswith("S-ny"):
                    r.status, r.response = "answered", "Not yet submitted"
                elif r.ref_id.startswith("S-r") and not r.ref_id.startswith("S-rej"):
                    r.status, r.response = "answered", "Revisions requested"
                elif r.ref_id == "S-rej" or r.ref_id == "W-rej":
                    r.status, r.response = "answered", "Rejected"
                elif r.ref_id.startswith("S-"):
                    r.status, r.response = "answered", "Accepted"
                elif r.ref_id.startswith("W-"):
                    r.status, r.response = "answered", "Accepted"
            session.commit()

        stats = outcomes.compute_acceptance_stats()
        by_band = {s["score_band"]: s for s in stats}

        strong = by_band.get("Strong")
        if not strong:
            failures.append("compute_acceptance_stats missing the 'Strong' band")
        else:
            if strong["n_decided"] != 12:
                failures.append(f"Strong band n_decided expected 12 (9+2+1), got {strong['n_decided']}")
            if strong["n_accepted"] != 9:
                failures.append(f"Strong band n_accepted expected 9, got {strong['n_accepted']}")
            if strong["n_not_yet_submitted"] != 3:
                failures.append(f"Strong band n_not_yet_submitted expected 3, got {strong['n_not_yet_submitted']}")
            if strong["acceptance_rate"] != 75.0:
                failures.append(f"Strong band acceptance_rate expected 75.0 (9/12), got {strong['acceptance_rate']}")

        weak = by_band.get("Weak")
        if not weak:
            failures.append("compute_acceptance_stats missing the 'Weak' band")
        elif weak["acceptance_rate"] is not None:
            failures.append(f"Weak band has only {weak['n_decided']} decided responses "
                             f"(< MIN_BAND_SAMPLE={outcomes.MIN_BAND_SAMPLE}) -- rate should be "
                             f"withheld (None), got {weak['acceptance_rate']}")

        # A still-pending row (never answered/skipped) must not count toward any band's stats.
        outcomes.schedule_followup("S-pending", "strongpending@example.com", "readiness_card", score_band="Strong")
        stats2 = outcomes.compute_acceptance_stats()
        strong2 = next(s for s in stats2 if s["score_band"] == "Strong")
        if strong2["n_decided"] != 12:
            failures.append("a still-pending row was incorrectly counted in compute_acceptance_stats")
    finally:
        outcomes._get_engine = original_get_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: compute_acceptance_stats — decided-only denominator, MIN_BAND_SAMPLE "
          "withholding, and pending-row exclusion verified.")


if __name__ == "__main__":
    run_schedule_and_fetch()
    run_record_and_skip()
    run_acceptance_stats()
