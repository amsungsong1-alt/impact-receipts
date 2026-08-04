"""
utils/account_export.py — Laudon Ch.10, C5: "switching costs, built
honestly." A user's accumulated history (saved audits, Logframe Library,
clients, payment history) is real product value -- and per Act 843/NDPA
data-portability, that value must be exportable, not just visible while
you keep paying. Composed entirely from existing, already-ownership-
checked read functions in utils/audits.py and utils/db.py -- no new DB
queries of its own.

Deliberately mirrors purge_account_audit_content()'s scope (audits +
logframe_libraries/items + clients) plus payment_history (kept out of
*deletion* scope for accounting reasons, but included here for
transparency -- an export is read-only, so including it carries none of
deletion's retention-conflict risk). Does not include wa_conversations
(no read-equivalent of delete_wa_conversations() exists yet -- see
docs/unit_economics.md's sibling gaps list) or access_log (a permanent
security trail, never user-facing).
"""
from __future__ import annotations
from datetime import datetime, timezone

# High enough that a real account's full history is never silently
# truncated -- list_audits()'s own default (50) is a UI-page-size limit,
# not appropriate for a "give me everything" export.
_EXPORT_AUDIT_LIMIT = 5000


def build_account_export(email: str) -> dict:
    """Returns {"email", "exported_at", "audits": [...],
    "logframe_libraries": [...], "clients": [...], "payment_history": [...]}.
    Every list defaults to [] (never raises, never omits a key) so an empty
    or brand-new account still gets a complete, valid, empty-but-present
    bundle rather than an error."""
    bundle = {
        "email": email or "",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "audits": [],
        "logframe_libraries": [],
        "clients": [],
        "payment_history": [],
    }
    if not email:
        return bundle

    try:
        from utils.audits import list_audits, get_audit, list_logframe_libraries, get_library_items, list_clients
    except Exception:
        return bundle

    try:
        for summary in list_audits(email, limit=_EXPORT_AUDIT_LIMIT):
            full = get_audit(email, summary.get("id"))
            if full:
                bundle["audits"].append(full)
    except Exception:
        pass

    try:
        for lib in list_logframe_libraries(email):
            lib_export = dict(lib)
            lib_export["items"] = get_library_items(lib.get("id"), email)
            bundle["logframe_libraries"].append(lib_export)
    except Exception:
        pass

    try:
        bundle["clients"] = list_clients(email)
    except Exception:
        pass

    try:
        from utils.db import get_payment_history
        bundle["payment_history"] = get_payment_history(email)
    except Exception:
        pass

    return bundle
