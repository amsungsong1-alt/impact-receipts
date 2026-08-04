"""
scripts/backfill_encrypt_audits.py

Laudon Ch.8 hardening, C2: one-time, idempotent backfill that encrypts any
pre-existing plaintext audits.submissions_json/evaluations_json and
logframe_library_items free-text indicator columns.

Why this is needed, not just nice-to-have: migration 0011_encrypt_audit_columns.sql
only changed these columns' TYPE from jsonb to text -- it never encrypted the
data already in them. Every row written before utils/crypto.py's Fernet
encryption shipped is still plaintext today. Worse, this is not merely a
security gap: utils/audits.py's own read paths (get_audit, list_audits,
get_library_items) call decrypt_text() unconditionally and treat a failed
decrypt as "wrong/missing key or corrupted ciphertext" -- for get_audit that
means the WHOLE row is silently treated as inaccessible (returns None); for
get_library_items each affected field silently reads back as "" (`decrypt_text(...) or ""`).
In other words: every legacy plaintext row is invisible to its own owner
today, not just under-protected. Running this script restores access to that
data at the same time it encrypts it.

Idempotent and safe to re-run/interrupt: each row's field is inspected
independently -- decrypt_text() succeeding means "already encrypted, skip";
failing means "treat as legacy plaintext, encrypt it now" -- and each row is
committed individually, so an interrupted run has migrated everything up to
that point and simply continues correctly next time. A value that neither
decrypts nor (for audits' JSON columns) parses as valid JSON is left
untouched and reported separately, never guessed at.

Requires SUPABASE_DB_URL (ideally the least-privilege app_audits_rw role,
see 0009_least_privilege_role.sql -- it has update grants on exactly the two
tables this script touches) and AUDIT_ENCRYPTION_KEY. Run:
    python scripts/backfill_encrypt_audits.py
    python scripts/backfill_encrypt_audits.py --dry-run   # report only, no writes
"""
from __future__ import annotations
import argparse
import json
import os
import sys

# Allows `python scripts/backfill_encrypt_audits.py` from any cwd to import
# utils.* -- scripts/ is not a package with its own utils/, the repo root is.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_engine():
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        print("SUPABASE_DB_URL is not set -- point it at a disposable branch database "
              "or the production database directly (this script's writes are additive "
              "re-encryptions, not schema changes).", file=sys.stderr)
        sys.exit(1)
    from sqlalchemy import create_engine
    return create_engine(db_url, pool_pre_ping=True)


def backfill_audits(session, encrypt_text, decrypt_text, dry_run: bool) -> dict:
    from utils.audits import Audit
    scanned = migrated = already_encrypted = corrupted = 0
    for row in session.query(Audit).all():
        scanned += 1
        changed = False
        for field in ("submissions_json", "evaluations_json"):
            value = getattr(row, field)
            if not value:
                continue
            if decrypt_text(value) is not None:
                continue  # already valid ciphertext under the current key
            try:
                json.loads(value)  # confirm it's legacy plaintext JSON, not garbage
            except (json.JSONDecodeError, ValueError):
                corrupted += 1
                print(f"  WARNING: audits.id={row.id}.{field} neither decrypts nor "
                      f"parses as JSON -- left untouched, needs manual review.")
                continue
            if not dry_run:
                setattr(row, field, encrypt_text(value))
            changed = True
        if changed:
            migrated += 1
            if not dry_run:
                session.commit()
        else:
            already_encrypted += 1
    return {"scanned": scanned, "migrated": migrated,
            "already_encrypted": already_encrypted, "corrupted": corrupted}


def backfill_logframe_items(session, encrypt_text, decrypt_text, dry_run: bool) -> dict:
    from utils.audits import LogframeLibraryItem, _LIBRARY_ENCRYPTED_FIELDS
    scanned = migrated = already_encrypted = 0
    for row in session.query(LogframeLibraryItem).all():
        scanned += 1
        changed = False
        for field in _LIBRARY_ENCRYPTED_FIELDS:
            value = getattr(row, field)
            if not value:
                continue
            if decrypt_text(value) is not None:
                continue  # already valid ciphertext under the current key
            if not dry_run:
                setattr(row, field, encrypt_text(value))
            changed = True
        if changed:
            migrated += 1
            if not dry_run:
                session.commit()
        else:
            already_encrypted += 1
    return {"scanned": scanned, "migrated": migrated, "already_encrypted": already_encrypted}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would be migrated without writing anything.")
    args = parser.parse_args()

    from utils.crypto import encrypt_text, decrypt_text, _get_fernet
    if _get_fernet() is None:
        print("AUDIT_ENCRYPTION_KEY is not set or invalid -- cannot encrypt anything. "
              "Set it to the same key utils/crypto.py already uses in production.", file=sys.stderr)
        sys.exit(1)

    from sqlalchemy.orm import Session
    engine = _get_engine()

    print(f"{'DRY RUN -- ' if args.dry_run else ''}Backfilling audits...")
    with Session(engine) as session:
        audits_stats = backfill_audits(session, encrypt_text, decrypt_text, args.dry_run)
    print(f"  audits: {audits_stats['scanned']} scanned, {audits_stats['migrated']} migrated, "
          f"{audits_stats['already_encrypted']} already encrypted, "
          f"{audits_stats['corrupted']} corrupted/unreadable (left untouched)")

    print(f"{'DRY RUN -- ' if args.dry_run else ''}Backfilling logframe_library_items...")
    with Session(engine) as session:
        items_stats = backfill_logframe_items(session, encrypt_text, decrypt_text, args.dry_run)
    print(f"  logframe_library_items: {items_stats['scanned']} scanned, "
          f"{items_stats['migrated']} migrated, {items_stats['already_encrypted']} already encrypted")

    if args.dry_run:
        print("\nDry run complete -- no changes written. Re-run without --dry-run to apply.")
    else:
        print("\nBackfill complete.")
    if audits_stats["corrupted"]:
        print(f"\n{audits_stats['corrupted']} audits row(s) need manual review -- see WARNING lines above.")


if __name__ == "__main__":
    main()
