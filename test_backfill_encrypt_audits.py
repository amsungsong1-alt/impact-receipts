"""
test_backfill_encrypt_audits.py — golden tests for
scripts/backfill_encrypt_audits.py (Laudon Ch.8 hardening, C2: the one-time
backfill that encrypts pre-existing plaintext audits/logframe_library_items
rows written before utils/crypto.py's Fernet encryption shipped).

No pytest, no real network calls: same in-memory SQLite seam as
test_audits.py (utils.audits.Base.metadata.create_all against
sqlite:///:memory:). Run with: python test_backfill_encrypt_audits.py
"""
import json
import os

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("AUDIT_ENCRYPTION_KEY", Fernet.generate_key().decode())

import utils.audits as audits
import utils.crypto as crypto
from scripts.backfill_encrypt_audits import backfill_audits, backfill_logframe_items


def _fresh_engine():
    engine = create_engine("sqlite:///:memory:")
    audits.Base.metadata.create_all(engine)
    return engine


def run_backfill_audits_migrates_plaintext_leaves_encrypted_alone():
    failures = []
    engine = _fresh_engine()
    with Session(engine) as session:
        # Legacy plaintext row (written before encryption shipped -- exactly
        # what 0011_encrypt_audit_columns.sql's own comment warns was never
        # retroactively encrypted).
        plaintext_row = audits.Audit(
            email="legacy@example.com", ref_id="IMP-legacy-1", active_slots=1,
            submissions_json=json.dumps([{"donor": "USAID"}]),
            evaluations_json=json.dumps([{"confidence_score": 3.5}]),
            donor="USAID", sector="WASH", org_type="International NGO (INGO)",
        )
        # Already-encrypted row (written after encryption shipped) -- must
        # be left completely untouched, including not re-encrypted.
        already_ct_submissions = crypto.encrypt_text(json.dumps([{"donor": "GIZ"}]))
        already_ct_evaluations = crypto.encrypt_text(json.dumps([{"confidence_score": 4.0}]))
        encrypted_row = audits.Audit(
            email="modern@example.com", ref_id="IMP-modern-1", active_slots=1,
            submissions_json=already_ct_submissions,
            evaluations_json=already_ct_evaluations,
            donor="GIZ", sector="Education & Skills", org_type="National NGO",
        )
        # Corrupted row -- neither valid ciphertext nor valid JSON -- must be
        # reported, never guessed at or silently dropped.
        corrupted_row = audits.Audit(
            email="corrupted@example.com", ref_id="IMP-corrupted-1", active_slots=1,
            submissions_json="{not valid json and not ciphertext",
            evaluations_json=json.dumps([{"confidence_score": 2.0}]),
            donor="GIZ", sector="Education & Skills", org_type="National NGO",
        )
        session.add_all([plaintext_row, encrypted_row, corrupted_row])
        session.commit()

        stats = backfill_audits(session, crypto.encrypt_text, crypto.decrypt_text, dry_run=False)

        if stats["scanned"] != 3:
            failures.append(f"expected 3 rows scanned, got {stats['scanned']}")
        # 2, not 1: the plaintext row (both fields migrated) AND the
        # corrupted row (its evaluations_json field IS valid plaintext JSON
        # and gets migrated even though its submissions_json field doesn't) --
        # a row with one bad field and one good field is correctly a partial
        # migration, not skipped entirely.
        if stats["migrated"] != 2:
            failures.append(f"expected 2 rows migrated, got {stats['migrated']}")
        if stats["corrupted"] != 1:
            failures.append(f"expected 1 corrupted field, got {stats['corrupted']}")

        session.expire_all()
        migrated = session.get(audits.Audit, plaintext_row.id)
        dec_subs = crypto.decrypt_text(migrated.submissions_json)
        dec_evals = crypto.decrypt_text(migrated.evaluations_json)
        if dec_subs is None or json.loads(dec_subs) != [{"donor": "USAID"}]:
            failures.append("plaintext row's submissions_json was not correctly encrypted+recoverable")
        if dec_evals is None or json.loads(dec_evals) != [{"confidence_score": 3.5}]:
            failures.append("plaintext row's evaluations_json was not correctly encrypted+recoverable")

        untouched = session.get(audits.Audit, encrypted_row.id)
        if untouched.submissions_json != already_ct_submissions:
            failures.append("already-encrypted row's submissions_json was modified -- must be left alone")
        if untouched.evaluations_json != already_ct_evaluations:
            failures.append("already-encrypted row's evaluations_json was modified -- must be left alone")

        still_corrupted = session.get(audits.Audit, corrupted_row.id)
        if still_corrupted.submissions_json != "{not valid json and not ciphertext":
            failures.append("corrupted field was modified instead of left untouched for manual review")
        dec_partial = crypto.decrypt_text(still_corrupted.evaluations_json)
        if dec_partial is None or json.loads(dec_partial) != [{"confidence_score": 2.0}]:
            failures.append("corrupted row's OTHER (valid) field should still have been migrated")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: backfill_audits — plaintext migrated+recoverable, already-encrypted untouched, "
          "corrupted rows reported and left alone.")


def run_backfill_audits_dry_run_writes_nothing():
    engine = _fresh_engine()
    with Session(engine) as session:
        original_plaintext = json.dumps([{"donor": "USAID"}])
        row = audits.Audit(
            email="dryrun@example.com", ref_id="IMP-dryrun-1", active_slots=1,
            submissions_json=original_plaintext,
            evaluations_json=json.dumps([{"confidence_score": 3.0}]),
            donor="USAID", sector="WASH", org_type="International NGO (INGO)",
        )
        session.add(row)
        session.commit()

        stats = backfill_audits(session, crypto.encrypt_text, crypto.decrypt_text, dry_run=True)
        assert stats["migrated"] == 1, "dry run should still report what WOULD be migrated"

        session.expire_all()
        unchanged = session.get(audits.Audit, row.id)
        assert unchanged.submissions_json == original_plaintext, "dry run must not write any changes"
    print("PASS: run_backfill_audits_dry_run_writes_nothing")


def run_backfill_logframe_items_migrates_plaintext_leaves_encrypted_alone():
    failures = []
    engine = _fresh_engine()
    with Session(engine) as session:
        library = audits.LogframeLibrary(email="a@example.com", name="Test Library")
        session.add(library)
        session.commit()

        plaintext_item = audits.LogframeLibraryItem(
            library_id=library.id, sector="Health",
            indicator_name="Number trained", logframe_indicator="# trained",
            logframe_baseline="0", logframe_target="500", logframe_achievement="487",
        )
        already_ct_name = crypto.encrypt_text("Number trained")
        encrypted_item = audits.LogframeLibraryItem(
            library_id=library.id, sector="Health",
            indicator_name=already_ct_name, logframe_indicator=crypto.encrypt_text("# trained"),
            logframe_baseline=crypto.encrypt_text("0"), logframe_target=crypto.encrypt_text("500"),
            logframe_achievement=crypto.encrypt_text("487"),
        )
        session.add_all([plaintext_item, encrypted_item])
        session.commit()

        stats = backfill_logframe_items(session, crypto.encrypt_text, crypto.decrypt_text, dry_run=False)
        if stats["scanned"] != 2:
            failures.append(f"expected 2 rows scanned, got {stats['scanned']}")
        if stats["migrated"] != 1:
            failures.append(f"expected 1 row migrated (the plaintext one), got {stats['migrated']}")

        session.expire_all()
        migrated = session.get(audits.LogframeLibraryItem, plaintext_item.id)
        if crypto.decrypt_text(migrated.indicator_name) != "Number trained":
            failures.append("plaintext logframe item's indicator_name was not correctly encrypted+recoverable")

        untouched = session.get(audits.LogframeLibraryItem, encrypted_item.id)
        if untouched.indicator_name != already_ct_name:
            failures.append("already-encrypted logframe item was modified -- must be left alone")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: backfill_logframe_items — plaintext migrated+recoverable, already-encrypted untouched.")


if __name__ == "__main__":
    run_backfill_audits_migrates_plaintext_leaves_encrypted_alone()
    run_backfill_audits_dry_run_writes_nothing()
    run_backfill_logframe_items_migrates_plaintext_leaves_encrypted_alone()
    print("\nAll test_backfill_encrypt_audits.py tests passed.")
