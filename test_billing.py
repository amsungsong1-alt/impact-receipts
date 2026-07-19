"""
test_billing.py — golden tests for utils/auth.py, utils/metering.py, and the
new parts of utils/paystack.py (subscriptions + webhook signature).

No pytest, no real network calls, no real Supabase project: a small in-memory
fake Supabase client stands in for utils.db._get_client()/utils.auth._get_client()
(same swap-the-network-seam approach as test_council.py's fake for
council._call_haiku, just applied to a chainier query-builder API), and
utils.paystack's `requests` module reference is swapped for a fake with
canned responses. Run with: python test_billing.py
"""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import utils.auth as auth
import utils.db as db
import utils.metering as metering
import utils.paystack as paystack


# ---------------------------------------------------------------------------
# In-memory fake Supabase client — supports exactly the chained calls
# utils/db.py and utils/auth.py actually use: .table(name).select/insert/
# upsert/update, .eq/.is_/.order/.limit, .execute() -> .data, and .rpc().
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self):
        self.rows = []


class _FakeQuery:
    def __init__(self, table):
        self._table = table
        self._op = None
        self._payload = None
        self._filters = []  # list of ("eq"|"is", col, val)
        self._order = None
        self._limit = None

    def select(self, *_a, **_kw):
        self._op = self._op or "select"
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self._op = "insert"
        self._payload = dict(row)
        return self

    def upsert(self, row, on_conflict=None):
        self._op = "upsert"
        self._payload = dict(row)
        return self

    def update(self, fields):
        self._op = "update"
        self._payload = dict(fields)
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _matches(self, row):
        for kind, col, val in self._filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "is":
                is_null = row.get(col) is None
                if is_null != (val == "null"):
                    return False
        return True

    def execute(self):
        rows = self._table.rows
        if self._op == "insert":
            rows.append(dict(self._payload))
            return _FakeResult([dict(self._payload)])
        if self._op == "upsert":
            key_col = "email" if "email" in self._payload else "token_hash"
            existing = next((r for r in rows if r.get(key_col) == self._payload.get(key_col)), None)
            if existing is not None:
                existing.update(self._payload)
                return _FakeResult([dict(existing)])
            rows.append(dict(self._payload))
            return _FakeResult([dict(self._payload)])
        if self._op == "update":
            matched = [r for r in rows if self._matches(r)]
            for r in matched:
                r.update(self._payload)
            return _FakeResult([dict(r) for r in matched])
        if self._op == "delete":
            matched = [r for r in rows if self._matches(r)]
            for r in matched:
                rows.remove(r)
            return _FakeResult([dict(r) for r in matched])
        # select
        matched = [r for r in rows if self._matches(r)]
        if self._order:
            col, desc = self._order
            matched.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return _FakeResult([dict(r) for r in matched])


class _FakeRpcCall:
    """rpc() in real supabase-py returns a builder -- the call only actually
    happens on .execute(), same as every other query. Deferring the mutation
    to .execute() here (rather than performing it inside rpc() itself) is
    what makes the "RPC unavailable -> exception -> fallback" simulation in
    run_metering() work correctly."""
    def __init__(self, client, name, params):
        self._client = client
        self._name = name
        self._params = params

    def execute(self):
        if not self._client.rpc_available:
            raise Exception("could not find function in schema cache")
        if self._name == "increment_free_checks":
            email = self._params["p_email"]
            users = self._client.tables.get("users")
            if users:
                for r in users.rows:
                    if r.get("email") == email:
                        r["free_checks_used"] = r.get("free_checks_used", 0) + 1
                        return _FakeResult(r["free_checks_used"])
            return _FakeResult(None)
        raise Exception(f"unknown rpc {self._name}")


class _FakeClient:
    def __init__(self):
        self.tables = {}
        self.rpc_available = True

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = _FakeTable()
        return _FakeQuery(self.tables[name])

    def rpc(self, name, params):
        return _FakeRpcCall(self, name, params)


def _row(fake_client, table_name, email):
    return next((r for r in fake_client.tables[table_name].rows if r.get("email") == email), None)


# ---------------------------------------------------------------------------
# utils.metering — check_access/record_check, and the increment_checks
# atomicity fix (RPC path + fallback path)
# ---------------------------------------------------------------------------

def run_metering():
    failures = []
    original_get_client = db._get_client
    fake_client = _FakeClient()
    db._get_client = lambda: fake_client
    try:
        db.upsert_user("free@example.com")
        db.upsert_user("paid@example.com")
        db.mark_paid("paid@example.com", days=30)
        _row(fake_client, "users", "free@example.com")["free_checks_used"] = 2

        # 1. Free user under the limit is allowed, with the right remaining count.
        access = metering.check_access("free@example.com")
        if not access["allowed"] or access["checks_remaining"] != 1:
            failures.append(f"free user under limit: unexpected access {access!r}")

        # 2. Paid user is always allowed regardless of checks_used.
        access_paid = metering.check_access("paid@example.com")
        if not access_paid["allowed"] or not access_paid["is_paid"]:
            failures.append(f"paid user: unexpected access {access_paid!r}")

        # 3. No email -> not allowed, no crash.
        if metering.check_access("")["allowed"]:
            failures.append("check_access('') must not be allowed")

        # 4. Free user AT the limit is blocked.
        _row(fake_client, "users", "free@example.com")["free_checks_used"] = metering.FREE_CHECKS_LIMIT
        if metering.check_access("free@example.com")["allowed"]:
            failures.append("free user at the limit should not be allowed")

        # 5. record_check increments once per call (base -> +1 -> +2) -- the
        #    concrete regression test for the increment_checks atomicity fix.
        _row(fake_client, "users", "free@example.com")["free_checks_used"] = 0
        metering.record_check("free@example.com")
        metering.record_check("free@example.com")
        if db.get_user("free@example.com").get("free_checks_used") != 2:
            failures.append("record_check x2 should land at 2, got "
                             f"{db.get_user('free@example.com').get('free_checks_used')}")

        # 6. record_check no-ops for a paid account (never increments).
        _before = db.get_user("paid@example.com").get("free_checks_used", 0)
        metering.record_check("paid@example.com")
        _after = db.get_user("paid@example.com").get("free_checks_used", 0)
        if _after != _before:
            failures.append("record_check should no-op for a paid account")

        # 7. increment_checks falls back to read-then-upsert if the RPC is
        #    unavailable (e.g. the migration hasn't been applied yet) --
        #    never raises, still increments correctly.
        fake_client.rpc_available = False
        _row(fake_client, "users", "free@example.com")["free_checks_used"] = 5
        db.increment_checks("free@example.com")
        if db.get_user("free@example.com").get("free_checks_used") != 6:
            failures.append("increment_checks fallback path did not increment correctly")
        fake_client.rpc_available = True
    finally:
        db._get_client = original_get_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: metering — check_access/record_check gating, atomic increment + fallback verified.")


# ---------------------------------------------------------------------------
# utils.db.set_user_plan — the gating-reliability fix for the Agency Dashboard
# ---------------------------------------------------------------------------

def run_set_user_plan():
    failures = []
    original_get_client = db._get_client
    fake_client = _FakeClient()
    db._get_client = lambda: fake_client
    try:
        db.upsert_user("agency@example.com")

        db.set_user_plan("agency@example.com", "agency")
        if db.get_user("agency@example.com").get("plan") != "agency":
            failures.append("set_user_plan did not persist a valid plan value")

        # Invalid plan values ("per_use", a typo, etc.) must no-op, not
        # silently overwrite with garbage -- a caller mistake should be
        # visible (plan stays at its last valid value), not swallowed.
        db.set_user_plan("agency@example.com", "per_use")
        if db.get_user("agency@example.com").get("plan") != "agency":
            failures.append("set_user_plan should no-op for an invalid plan value, not overwrite")

        # No email -> no-op, no crash.
        try:
            db.set_user_plan("", "agency")
        except Exception as exc:
            failures.append(f"set_user_plan raised with no email: {exc}")
    finally:
        db._get_client = original_get_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: set_user_plan — valid plan values persist, invalid values no-op, missing email is safe.")


# ---------------------------------------------------------------------------
# utils.auth — magic-link token lifecycle
# ---------------------------------------------------------------------------

def run_magic_link():
    failures = []
    original_db_client = db._get_client
    original_auth_client = auth._get_client
    fake_client = _FakeClient()
    db._get_client = lambda: fake_client
    auth._get_client = lambda: fake_client
    try:
        db.upsert_user("user@example.com")

        # 1. generate -> verify is non-mutating and repeatable -> redeem consumes it.
        raw = auth.generate_magic_link_token("user@example.com")
        if not raw:
            failures.append("generate_magic_link_token should return a non-empty token")
        if auth.verify_magic_link_token(raw) != "user@example.com":
            failures.append("verify_magic_link_token should return the issuing email")
        if auth.verify_magic_link_token(raw) != "user@example.com":
            failures.append("verify_magic_link_token should be repeatable (non-mutating)")
        if auth.redeem_magic_link_token(raw) != "user@example.com":
            failures.append("redeem_magic_link_token should return the email on first use")

        # 2. Second redeem of the same token fails (single-use).
        if auth.redeem_magic_link_token(raw) is not None:
            failures.append("a magic link token must not be redeemable twice")

        # 3. verify also fails once the token is redeemed.
        if auth.verify_magic_link_token(raw) is not None:
            failures.append("verify_magic_link_token should fail once a token is redeemed")

        # 4. Expired token fails both verify and redeem.
        raw2 = auth.generate_magic_link_token("user@example.com")
        row2 = next(r for r in fake_client.tables["login_tokens"].rows
                    if r["token_hash"] == auth._hash_token(raw2))
        row2["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        if auth.verify_magic_link_token(raw2) is not None:
            failures.append("an expired magic link token should fail verify")
        if auth.redeem_magic_link_token(raw2) is not None:
            failures.append("an expired magic link token should fail redeem")

        # 5. Unknown/tampered token fails.
        if auth.verify_magic_link_token("not-a-real-token") is not None:
            failures.append("an unknown token should fail verify")
    finally:
        db._get_client = original_db_client
        auth._get_client = original_auth_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: magic-link tokens — generate/verify/redeem lifecycle, single-use and expiry enforced.")


# ---------------------------------------------------------------------------
# utils.auth — durable session token lifecycle
# ---------------------------------------------------------------------------

def run_sessions():
    failures = []
    original_db_client = db._get_client
    original_auth_client = auth._get_client
    fake_client = _FakeClient()
    db._get_client = lambda: fake_client
    auth._get_client = lambda: fake_client
    try:
        db.upsert_user("user@example.com")

        # 1. issue -> verify returns the issuing email.
        raw = auth.issue_session_token("user@example.com", user_agent="pytest")
        if not raw:
            failures.append("issue_session_token should return a non-empty token")
        if auth.verify_session_token(raw) != "user@example.com":
            failures.append("verify_session_token should return the issuing email")

        # 2. list_sessions includes the new session.
        if len(auth.list_sessions("user@example.com")) != 1:
            failures.append("expected exactly 1 active session after issuing one")

        # 3. revoke -> verify-after-revoke returns None, and it drops from the list.
        auth.revoke_session(auth._hash_token(raw), "user@example.com")
        if auth.verify_session_token(raw) is not None:
            failures.append("verify_session_token should fail after the session is revoked")
        if auth.list_sessions("user@example.com"):
            failures.append("list_sessions should not include a revoked session")

        # 4. Expired session returns None.
        raw2 = auth.issue_session_token("user@example.com")
        row2 = next(r for r in fake_client.tables["sessions"].rows
                    if r["token_hash"] == auth._hash_token(raw2))
        row2["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        if auth.verify_session_token(raw2) is not None:
            failures.append("an expired session token should fail verify")

        # 5. revoke_all_sessions revokes every session for the account.
        raw3 = auth.issue_session_token("user@example.com")
        raw4 = auth.issue_session_token("user@example.com")
        auth.revoke_all_sessions("user@example.com")
        if auth.verify_session_token(raw3) is not None or auth.verify_session_token(raw4) is not None:
            failures.append("revoke_all_sessions should revoke every session for the account")
    finally:
        db._get_client = original_db_client
        auth._get_client = original_auth_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: session tokens — issue/verify/list/revoke lifecycle, expiry enforced.")


# ---------------------------------------------------------------------------
# utils.paystack — subscription helpers + webhook signature verification
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = str(json_data)

    def json(self):
        return self._json


class _FakeRequests:
    def __init__(self):
        self.post_response = None
        self.raise_on_post = False

    def post(self, url, json=None, headers=None, timeout=None):
        if self.raise_on_post:
            raise ConnectionError("network down")
        return self.post_response

    def get(self, url, headers=None, params=None, timeout=None):
        return self.post_response


def run_paystack_subscriptions():
    failures = []
    original_requests = paystack.requests
    original_secret_key = paystack._secret_key
    original_base_url = paystack._base_url
    fake_requests = _FakeRequests()
    paystack.requests = fake_requests
    paystack._secret_key = lambda: "sk_test_fake"
    paystack._base_url = lambda: "https://test.example.com"
    try:
        # 1. initialize_subscription_payment success.
        fake_requests.post_response = _FakeResponse(
            200, {"status": True, "data": {"authorization_url": "https://paystack.test/pay/abc"}})
        url = paystack.initialize_subscription_payment("user@example.com", 5000, "PLN_test123", "monthly")
        if url != "https://paystack.test/pay/abc":
            failures.append(f"initialize_subscription_payment success: unexpected url {url!r}")

        # 2. Missing plan_code -> "" without a network call.
        if paystack.initialize_subscription_payment("user@example.com", 5000, "", "monthly") != "":
            failures.append("initialize_subscription_payment with empty plan_code should return ''")

        # 3. Paystack-reported error surfaces via last_payment_error().
        fake_requests.post_response = _FakeResponse(200, {"status": False, "message": "Invalid plan"})
        url3 = paystack.initialize_subscription_payment("user@example.com", 5000, "PLN_bad", "monthly")
        if url3 != "" or paystack.last_payment_error() != "Invalid plan":
            failures.append(f"initialize_subscription_payment error path: url={url3!r} "
                             f"err={paystack.last_payment_error()!r}")

        # 4. disable_subscription success.
        fake_requests.post_response = _FakeResponse(200, {"status": True, "message": "Subscription disabled"})
        ok, msg = paystack.disable_subscription("SUB_123", "tok_abc")
        if not ok or "disabled" not in msg.lower():
            failures.append(f"disable_subscription success: unexpected ({ok!r}, {msg!r})")

        # 5. Missing subscription details fails closed, no network call needed.
        ok2, _msg2 = paystack.disable_subscription("", "")
        if ok2:
            failures.append("disable_subscription with missing code/token should fail")

        # 6. Network failure degrades gracefully (never raises out of the function).
        fake_requests.raise_on_post = True
        ok3, _msg3 = paystack.disable_subscription("SUB_123", "tok_abc")
        if ok3:
            failures.append("disable_subscription should return False on a network exception")
        fake_requests.raise_on_post = False

        # 7. verify_webhook_signature: correct HMAC passes.
        body = b'{"event":"charge.success"}'
        good_sig = hmac.new(b"sk_test_fake", body, hashlib.sha512).hexdigest()
        if not paystack.verify_webhook_signature(body, good_sig):
            failures.append("verify_webhook_signature should accept a correctly computed signature")

        # 8. Tampered body fails.
        if paystack.verify_webhook_signature(b'{"event":"charge.success","tampered":true}', good_sig):
            failures.append("verify_webhook_signature should reject a tampered body")

        # 9. Missing signature header fails closed.
        if paystack.verify_webhook_signature(body, ""):
            failures.append("verify_webhook_signature should fail closed with no signature header")

        # 10. Missing secret key fails closed.
        paystack._secret_key = lambda: ""
        if paystack.verify_webhook_signature(body, good_sig):
            failures.append("verify_webhook_signature should fail closed with no secret key configured")
    finally:
        paystack.requests = original_requests
        paystack._secret_key = original_secret_key
        paystack._base_url = original_base_url

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: paystack subscriptions — plan-tied init, disable, and webhook signature verification.")


def run_data_deletion():
    """clear_user_draft()/delete_wa_conversations() -- the utils/db.py half
    of the "erase my history" feature (the utils/audits.py half,
    purge_account_audit_content, is tested in test_audits.py). wa_conversations
    has no foreign key to users at all, so delete_wa_conversations is the
    only thing that ever removes those rows -- this is the regression test
    for that."""
    failures = []
    original_get_client = db._get_client
    fake_client = _FakeClient()
    db._get_client = lambda: fake_client
    try:
        fake_client.table("users").insert({"email": "a@example.com", "draft_json": "{\"result_statement\": \"secret\"}"}).execute()
        fake_client.table("wa_conversations").insert({"user_email": "a@example.com", "body": "a's message"}).execute()
        fake_client.table("wa_conversations").insert({"user_email": "a@example.com", "body": "a's second message"}).execute()
        fake_client.table("wa_conversations").insert({"user_email": "b@example.com", "body": "b's message"}).execute()

        db.clear_user_draft("a@example.com")
        if _row(fake_client, "users", "a@example.com").get("draft_json") is not None:
            failures.append("clear_user_draft did not clear draft_json")

        db.delete_wa_conversations("a@example.com")
        remaining = fake_client.tables["wa_conversations"].rows
        if any(r.get("user_email") == "a@example.com" for r in remaining):
            failures.append("delete_wa_conversations left rows behind for the target email")
        if not any(r.get("user_email") == "b@example.com" for r in remaining):
            failures.append("delete_wa_conversations deleted another account's rows")
    finally:
        db._get_client = original_get_client

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: data deletion — clear_user_draft/delete_wa_conversations scoped correctly to the target email.")


if __name__ == "__main__":
    run_metering()
    run_set_user_plan()
    run_magic_link()
    run_sessions()
    run_paystack_subscriptions()
    run_data_deletion()
