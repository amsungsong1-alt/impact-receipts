"""
scripts/verify_audit_chain.py

Laudon Ch.8 hardening, C4: independently re-verify access_log's hash chain
(see supabase/migrations/0051_access_log_hash_chain.sql). The chain is
computed by a Postgres BEFORE INSERT trigger at write time; this script
recomputes it at read time and flags any row where they disagree -- that
disagreement is exactly what a silent edit/delete by a privileged
credential (bypassing the app_audits_rw role's append-only grant scope)
would produce. A row that verifies is a row that hasn't been tampered with
since it was written; run this periodically (see scripts/security_audit.py)
or immediately after any suspected incident.

The recompute logic in verify_chain() below must exactly match the SQL
trigger's hash formula (pipe-joined fields, sha256, hex) -- see that
migration's comment for why created_at is fetched pre-cast to text (::text)
in the query rather than reformatted from a parsed Python datetime, to
avoid a spurious mismatch from a formatting difference that isn't actually
tampering.

Run with: python scripts/verify_audit_chain.py
"""
from __future__ import annotations
import hashlib
import os
import sys


def _row_hash(prev_hash: str, email: str, action: str, resource_type, resource_id,
              ip_address, created_at_text: str) -> str:
    payload = "|".join([
        prev_hash or "",
        email or "",
        action or "",
        resource_type or "",
        str(resource_id) if resource_id is not None else "",
        ip_address or "",
        created_at_text or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_chain(rows: list[dict]) -> list[str]:
    """rows must be ordered by id ascending, each a dict with keys: id,
    prev_hash, row_hash, email, action, resource_type, resource_id,
    ip_address, created_at_text. Returns a list of human-readable problem
    descriptions -- empty means the whole chain verified cleanly."""
    problems = []
    expected_prev_hash = ""
    for row in rows:
        if (row.get("prev_hash") or "") != expected_prev_hash:
            problems.append(
                f"id={row['id']}: prev_hash does not match the previous row's row_hash -- "
                f"the chain is broken here (a row may have been inserted, deleted, or reordered "
                f"out-of-band, or this is the very first row after this trigger was installed, "
                f"which is expected exactly once)."
            )
        recomputed = _row_hash(
            row.get("prev_hash") or "", row.get("email"), row.get("action"),
            row.get("resource_type"), row.get("resource_id"), row.get("ip_address"),
            row.get("created_at_text"),
        )
        if recomputed != row.get("row_hash"):
            problems.append(
                f"id={row['id']}: stored row_hash does not match the recomputed hash of this "
                f"row's own fields -- this row's content was very likely edited after it was "
                f"written."
            )
        expected_prev_hash = row.get("row_hash") or ""
    return problems


def _fetch_rows_from_db() -> list[dict]:
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        print("SUPABASE_DB_URL is not set.", file=sys.stderr)
        sys.exit(1)
    from sqlalchemy import create_engine, text
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        result = conn.execute(text(
            "select id, prev_hash, row_hash, email, action, resource_type, resource_id, "
            "ip_address, created_at::text as created_at_text "
            "from access_log order by id asc"
        ))
        return [dict(row._mapping) for row in result]


def main() -> None:
    rows = _fetch_rows_from_db()
    if not rows:
        print("access_log is empty -- nothing to verify.")
        return
    problems = verify_chain(rows)
    print(f"Verified {len(rows)} access_log row(s).")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S) FOUND -- possible tampering or a chain-trigger bug:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("Chain intact -- no tampering detected.")


if __name__ == "__main__":
    main()
