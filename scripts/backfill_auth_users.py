"""
scripts/backfill_auth_users.py

One-time backfill: mints a Supabase Auth identity (auth.users row +
public.users.auth_user_id link) for every EXISTING account, so
0046_rls_users.sql / 0047_rls_payments.sql can be applied without waiting
for each user to naturally log in again first.

Why this exists: auth_email() (0039_auth_email_function.sql) resolves
auth.uid() -> email via users.auth_user_id, but that column is only ever
populated when someone actually completes a login through the app's own
_complete_email_login/_restore_session_from_query_param code paths (see
utils/auth.py::ensure_auth_session). Applying 0046/0047 before every
existing account has gone through that at least once means auth_email()
returns NULL for them, and the SELECT/UPDATE policies on users/payments
silently deny every request -- get_user(), get_payment_history(), and
login itself would appear broken for anyone who hasn't re-authenticated
since this feature shipped. This script closes that gap up front instead
of waiting.

Reuses utils.supabase_auth.mint_auth_session() (the same generate_link +
verify_otp flow login uses) and utils.db.link_auth_user_id() (the same
write _complete_email_login makes) -- not a separate, untested code path.
Idempotent: link_auth_user_id() is an unconditional UPDATE, safe to re-run;
mint_auth_session() against an email that already has an auth.users row
just mints another session for it (harmless -- GoTrue supports multiple
concurrent sessions per user) rather than erroring.

Requires SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY.
Run:
    python scripts/backfill_auth_users.py
    python scripts/backfill_auth_users.py --dry-run
"""
from __future__ import annotations
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_all_emails() -> list[str]:
    from utils.db import _get_service_client
    c = _get_service_client()
    if not c:
        print("SUPABASE_SERVICE_ROLE_KEY is not set -- cannot proceed.", file=sys.stderr)
        sys.exit(1)
    res = c.table("users").select("email, auth_user_id").execute()
    return res.data or []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would be backfilled without minting anything.")
    args = parser.parse_args()

    from utils.supabase_auth import mint_auth_session
    from utils.db import link_auth_user_id

    rows = _get_all_emails()
    already_linked = [r for r in rows if r.get("auth_user_id")]
    to_backfill = [r for r in rows if not r.get("auth_user_id")]

    print(f"{len(rows)} total account(s): {len(already_linked)} already linked, "
          f"{len(to_backfill)} need backfilling.")
    if args.dry_run:
        for r in to_backfill:
            print(f"  would backfill: {r['email']}")
        print("\nDry run complete -- no changes made.")
        return

    succeeded, failed = 0, []
    for r in to_backfill:
        email = r["email"]
        session = mint_auth_session(email)
        if not session:
            failed.append(email)
            print(f"  FAILED: {email} (mint_auth_session returned None -- see "
                  f"utils/supabase_auth.py for possible causes: service-role key, "
                  f"network, or SDK response-shape mismatch)")
            continue
        link_auth_user_id(email, session["auth_user_id"])
        succeeded += 1
        print(f"  OK: {email} -> auth_user_id={session['auth_user_id']}")
        time.sleep(0.2)  # gentle throttling against GoTrue admin rate limits

    print(f"\nBackfilled {succeeded}/{len(to_backfill)} account(s).")
    if failed:
        print(f"{len(failed)} failed and need manual investigation: {failed}")
        sys.exit(1)
    print("All accounts now have auth_user_id set. Safe to verify with:\n"
          "  select count(*) from public.users where auth_user_id is null;\n"
          "(should be 0) before applying 0046_rls_users.sql / 0047_rls_payments.sql.")


if __name__ == "__main__":
    main()
