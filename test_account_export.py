"""
test_account_export.py — golden tests for utils/account_export.py (Laudon
Ch.10, C5). In-memory SQLite engine, same convention as test_audits.py --
swaps utils.audits._get_engine (and utils.db._get_client, for
payment_history) for fakes. Run with: python test_account_export.py
"""

import os
import uuid

from cryptography.fernet import Fernet
os.environ.setdefault("AUDIT_ENCRYPTION_KEY", Fernet.generate_key().decode())

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import utils.audits as audits
import utils.account_export as account_export
from utils.crypto import encrypt_text


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    audits.Base.metadata.create_all(engine)
    return engine


def _seed_audit(engine, email: str, donor: str = "USAID"):
    with Session(engine) as session:
        row = audits.Audit(
            email=email, ref_id=str(uuid.uuid4()), active_slots=1,
            donor=donor, sector="Health", org_type="International NGO (INGO)",
            primary_confidence_score=4.2, primary_clarity_score=3.8,
            submissions_json=encrypt_text('{"result_statement": "test"}'),
            evaluations_json=encrypt_text('{"confidence_score": 4.2}'),
        )
        session.add(row)
        session.commit()
        return row.id


def _seed_library(engine, email: str, name: str = "My Library"):
    original_engine = audits._get_engine
    audits._get_engine = lambda: engine
    try:
        lib_id = audits.create_logframe_library(email, name)
        audits.add_library_items(lib_id, email, [{
            "indicator_name": "% trained", "logframe_target": "450",
            "logframe_baseline": "0", "logframe_achievement": "487", "sector": "Health",
        }])
    finally:
        audits._get_engine = original_engine
    return lib_id


def _seed_client(engine, email: str, name: str = "Northern Ghana WASH Alliance"):
    with Session(engine) as session:
        c = audits.Client(email=email, name=name)
        session.add(c)
        session.commit()
        return c.id


def run_full_bundle_composed_correctly():
    failures = []
    engine = _fresh_engine()
    original_engine = audits._get_engine
    audits._get_engine = lambda: engine
    original_db_client = None
    try:
        _seed_audit(engine, "a@example.com")
        _seed_library(engine, "a@example.com")
        _seed_client(engine, "a@example.com")

        # get_payment_history() goes through utils.db, not utils.audits --
        # swap it to a fake returning a known row rather than pulling in the
        # full utils.db fixture machinery test_billing.py uses.
        import utils.db as db
        original_get_payment_history = db.get_payment_history
        db.get_payment_history = lambda email, limit=50: [
            {"paystack_reference": "ref1", "amount_pesewas": 5000, "plan": "monthly", "status": "success"}
        ]
        try:
            bundle = account_export.build_account_export("a@example.com")
        finally:
            db.get_payment_history = original_get_payment_history

        for key in ("email", "exported_at", "audits", "logframe_libraries", "clients", "payment_history"):
            if key not in bundle:
                failures.append(f"expected key {key!r} present in the export bundle")

        if bundle["email"] != "a@example.com":
            failures.append(f"expected email echoed back, got {bundle['email']!r}")
        if len(bundle["audits"]) != 1 or bundle["audits"][0].get("donor") != "USAID":
            failures.append(f"expected 1 audit with donor USAID, got {bundle['audits']}")
        if "submissions" not in bundle["audits"][0] or "evaluations" not in bundle["audits"][0]:
            failures.append("expected the FULL decrypted audit record (submissions/evaluations), not just a summary")
        if len(bundle["logframe_libraries"]) != 1 or len(bundle["logframe_libraries"][0].get("items", [])) != 1:
            failures.append(f"expected 1 library with 1 item, got {bundle['logframe_libraries']}")
        if len(bundle["clients"]) != 1:
            failures.append(f"expected 1 client, got {bundle['clients']}")
        if len(bundle["payment_history"]) != 1:
            failures.append(f"expected 1 payment history row, got {bundle['payment_history']}")
    finally:
        audits._get_engine = original_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: build_account_export() composes a complete bundle -- full decrypted audits, "
          "logframe libraries with items, clients, and payment history -- from existing read functions.")


def run_empty_account_degrades_to_empty_lists():
    failures = []
    engine = _fresh_engine()
    original_engine = audits._get_engine
    audits._get_engine = lambda: engine
    try:
        bundle = account_export.build_account_export("nobody@example.com")
        for key in ("audits", "logframe_libraries", "clients", "payment_history"):
            if bundle[key] != []:
                failures.append(f"expected an empty list for {key!r} on a brand-new account, got {bundle[key]}")
    finally:
        audits._get_engine = original_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a brand-new/no-data account gets a complete, valid, empty-but-present bundle, not an error.")


def run_cross_account_isolation():
    failures = []
    engine = _fresh_engine()
    original_engine = audits._get_engine
    audits._get_engine = lambda: engine
    try:
        _seed_audit(engine, "owner@example.com")
        _seed_library(engine, "owner@example.com")
        _seed_client(engine, "owner@example.com")

        import utils.db as db
        original_get_payment_history = db.get_payment_history
        db.get_payment_history = lambda email, limit=50: []
        try:
            other_bundle = account_export.build_account_export("other@example.com")
        finally:
            db.get_payment_history = original_get_payment_history

        for key in ("audits", "logframe_libraries", "clients"):
            if other_bundle[key] != []:
                failures.append(f"a different account must never see owner@example.com's {key!r}, got {other_bundle[key]}")
    finally:
        audits._get_engine = original_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: one account's export never leaks another account's audits/libraries/clients.")


def run_no_email_never_raises():
    failures = []
    try:
        bundle = account_export.build_account_export("")
        bundle_none = account_export.build_account_export(None)
    except Exception as e:
        failures.append(f"build_account_export must never raise on empty/None email, got {e!r}")
    else:
        if bundle["audits"] != [] or bundle_none["audits"] != []:
            failures.append("expected empty audits for empty/None email")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: never raises on empty/None email, degrades to an empty bundle.")


def run_no_engine_degrades_gracefully():
    failures = []
    original_engine = audits._get_engine
    audits._get_engine = lambda: None
    try:
        bundle = account_export.build_account_export("a@example.com")
        for key in ("audits", "logframe_libraries", "clients"):
            if bundle[key] != []:
                failures.append(f"expected empty {key!r} with no engine configured, got {bundle[key]}")
    finally:
        audits._get_engine = original_engine

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: no-engine-configured degrades to an empty-but-valid bundle, never raises.")


if __name__ == "__main__":
    run_full_bundle_composed_correctly()
    run_empty_account_degrades_to_empty_lists()
    run_cross_account_isolation()
    run_no_email_never_raises()
    run_no_engine_degrades_gracefully()
