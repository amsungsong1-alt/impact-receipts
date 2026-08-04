"""
test_auth_wiring.py — golden tests for the missing link between Supabase
Auth session minting (utils/supabase_auth.py) and RLS actually resolving
anyone's identity (utils/db.py::_get_authed_client/get_user_privileged/
link_auth_user_id, utils/auth.py::ensure_auth_session).

Context: 0046_rls_users.sql and 0047_rls_payments.sql cannot go live until
(a) utils/db.py's "logged-in user acting on their own row" functions
actually attach a per-user JWT instead of querying via the plain anon-key
client, (b) users.auth_user_id actually gets populated after a session is
minted (auth_email() resolves NOTHING otherwise, for anyone, ever), and
(c) columns not granted to `authenticated` (is_paid, plan,
free_checks_used, totp_secret/enabled) are written via the service-role
client, not the session-scoped one, since a valid JWT alone can't satisfy
a column-level REVOKE. This file verifies all three, using the same fake-
Supabase-client seam as test_billing.py/test_supabase_auth.py.

No pytest, no real network calls. Run with: python test_auth_wiring.py
"""
import os

from cryptography.fernet import Fernet

os.environ.setdefault("AUDIT_ENCRYPTION_KEY", Fernet.generate_key().decode())

import streamlit as st
import utils.db as db
import utils.auth as auth
import utils.supabase_auth as supabase_auth


# ---------------------------------------------------------------------------
# Minimal fakes -- just enough of the query-builder shape each test needs.
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, table, store, tag):
        self._table = table
        self._store = store
        self._tag = tag
        self._filters = {}
        self._pending = None  # (op, values), recorded at execute() time -- real PostgREST
                               # builders apply .eq(...) AFTER .update(...)/.upsert(...)/.insert(...)
                               # in the call chain, so the filters aren't complete until then.

    def select(self, *_a, **_k): return self
    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self

    def update(self, values):
        self._pending = ("update", values)
        return self

    def upsert(self, values, **_k):
        self._pending = ("upsert", values)
        return self

    def insert(self, values):
        self._pending = ("insert", values)
        return self

    def execute(self):
        if self._pending:
            op, values = self._pending
            self._store.setdefault("calls", []).append((self._tag, op, self._table, values, dict(self._filters)))
        rows = self._store.get("rows", {}).get(self._table, [])
        matched = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        class _Res:
            data = matched
        return _Res()


class _FakeClient:
    """`tag` identifies WHICH client (anon/authed/service) made a call, so
    tests can assert the right one was used without caring about exact
    query mechanics."""
    def __init__(self, store, tag):
        self._store = store
        self._tag = tag

    def table(self, name):
        return _FakeQuery(name, self._store, self._tag)


def run_get_authed_client_uses_session_token_when_present():
    """When a Supabase Auth access token is stored in this session, get_user()
    (and everything else routed through _get_authed_client()) must query via
    the session-scoped client build_session_scoped_client() returns -- NOT
    the plain anon client -- so auth.uid() actually resolves for RLS."""
    store = {"rows": {"users": [{"email": "a@example.com", "auth_user_id": "uuid-1"}]}}
    anon_client = _FakeClient(store, "anon")
    authed_client = _FakeClient(store, "authed")

    original_get_client = db._get_client
    original_build = supabase_auth.build_session_scoped_client
    db._get_client = lambda: anon_client
    supabase_auth.build_session_scoped_client = lambda token: authed_client if token == "tok-123" else None
    st.session_state["_supabase_auth_access_token"] = "tok-123"
    try:
        row = db.get_user("a@example.com")
        assert row is not None and row["email"] == "a@example.com", \
            "expected the authed client's row to be returned"
    finally:
        db._get_client = original_get_client
        supabase_auth.build_session_scoped_client = original_build
        st.session_state.pop("_supabase_auth_access_token", None)
    print("PASS: run_get_authed_client_uses_session_token_when_present")


def run_get_authed_client_falls_back_to_anon_without_token():
    """No token in session_state (Supabase Auth never minted for this
    session, or not configured at all) -- must fall back to the plain
    anon-key client, never raise, never silently return nothing when the
    anon path would have worked."""
    store = {"rows": {"users": [{"email": "b@example.com"}]}}
    anon_client = _FakeClient(store, "anon")

    original_get_client = db._get_client
    db._get_client = lambda: anon_client
    st.session_state.pop("_supabase_auth_access_token", None)
    try:
        row = db.get_user("b@example.com")
        assert row is not None and row["email"] == "b@example.com"
    finally:
        db._get_client = original_get_client
    print("PASS: run_get_authed_client_falls_back_to_anon_without_token")


def run_get_user_privileged_prefers_service_role():
    """get_user_privileged() must use the service-role client when
    configured -- this is the system-level check upsert_user() and the new-
    vs-returning-user check in _complete_email_login rely on to work
    correctly even before any per-user JWT exists."""
    store = {"rows": {"users": [{"email": "c@example.com"}]}}
    service_client = _FakeClient(store, "service")

    original_get_service_client = db._get_service_client
    original_get_client = db._get_client
    db._get_service_client = lambda: service_client
    db._get_client = lambda: (_ for _ in ()).throw(AssertionError("should not fall back to anon when service-role is available"))
    try:
        row = db.get_user_privileged("c@example.com")
        assert row is not None and row["email"] == "c@example.com"
    finally:
        db._get_service_client = original_get_service_client
        db._get_client = original_get_client
    print("PASS: run_get_user_privileged_prefers_service_role")


def run_get_user_privileged_falls_back_when_service_role_unconfigured():
    store = {"rows": {"users": [{"email": "d@example.com"}]}}
    anon_client = _FakeClient(store, "anon")

    original_get_service_client = db._get_service_client
    original_get_client = db._get_client
    db._get_service_client = lambda: None  # not configured in this environment
    db._get_client = lambda: anon_client
    try:
        row = db.get_user_privileged("d@example.com")
        assert row is not None and row["email"] == "d@example.com"
    finally:
        db._get_service_client = original_get_service_client
        db._get_client = original_get_client
    print("PASS: run_get_user_privileged_falls_back_when_service_role_unconfigured")


def run_link_auth_user_id_writes_via_service_role():
    """This is the write that makes auth_email() resolve at all -- must
    happen via service-role (auth_user_id isn't set yet at call time, so
    auth_email() can't authorize a session-scoped UPDATE for this row)."""
    store = {"rows": {"users": [{"email": "e@example.com"}]}}
    service_client = _FakeClient(store, "service")

    original_get_service_client = db._get_service_client
    db._get_service_client = lambda: service_client
    try:
        db.link_auth_user_id("e@example.com", "uuid-999")
        calls = store.get("calls", [])
        assert any(
            c[0] == "service" and c[1] == "update" and c[2] == "users"
            and c[3].get("auth_user_id") == "uuid-999" and c[4].get("email") == "e@example.com"
            for c in calls
        ), f"expected a service-role UPDATE of users.auth_user_id, got: {calls}"
    finally:
        db._get_service_client = original_get_service_client
    print("PASS: run_link_auth_user_id_writes_via_service_role")


def run_privileged_setters_prefer_service_role_over_authenticated_grant():
    """mark_paid/set_user_plan/set_user_totp write columns NOT granted to
    `authenticated` (0046_rls_users.sql) -- they must go through the
    service-role client even when a valid session JWT is available, or
    these writes would be silently rejected by Postgres's column-level
    REVOKE once RLS is enforced."""
    store = {"rows": {"users": []}}
    service_client = _FakeClient(store, "service")
    authed_client_should_not_be_used = _FakeClient(store, "authed")

    original_get_service_client = db._get_service_client
    original_get_client = db._get_client
    db._get_service_client = lambda: service_client
    db._get_client = lambda: authed_client_should_not_be_used
    try:
        db.mark_paid("f@example.com", days=30)
        db.set_user_plan("f@example.com", "agency")
        db.set_user_totp("f@example.com", "encrypted-secret", True)
        calls = store.get("calls", [])
        non_service_calls = [c for c in calls if c[0] != "service"]
        assert not non_service_calls, f"expected every privileged write to use the service-role client, got: {non_service_calls}"
        assert len(calls) == 3, f"expected 3 service-role writes, got {len(calls)}: {calls}"
    finally:
        db._get_service_client = original_get_service_client
        db._get_client = original_get_client
    print("PASS: run_privileged_setters_prefer_service_role_over_authenticated_grant")


def run_ensure_auth_session_mints_and_links_when_never_attached():
    """No auth session ever attached to this app session token -- must mint
    a fresh one, persist it (attach_auth_session), AND back-fill
    users.auth_user_id (link_auth_user_id) -- all three, not just the mint."""
    calls = {"attach": None, "link": None}

    original_get_client = auth._get_client
    auth._get_client = lambda: _FakeClient({"rows": {"sessions": []}}, "sessions")  # get_auth_session finds nothing

    original_mint = supabase_auth.mint_auth_session
    supabase_auth.mint_auth_session = lambda email: {
        "access_token": "new-access", "refresh_token": "new-refresh",
        "auth_user_id": "uuid-linked", "expires_at": 9999999999,
    }

    original_attach = auth.attach_auth_session
    def _fake_attach(raw_token, session):
        calls["attach"] = (raw_token, session)
    auth.attach_auth_session = _fake_attach

    import utils.db as db_module
    original_link = db_module.link_auth_user_id
    def _fake_link(email, auth_user_id):
        calls["link"] = (email, auth_user_id)
    db_module.link_auth_user_id = _fake_link

    try:
        token = auth.ensure_auth_session("g@example.com", "raw-session-token")
        assert token == "new-access", f"expected the freshly minted access token back, got {token!r}"
        assert calls["attach"] == ("raw-session-token", {
            "access_token": "new-access", "refresh_token": "new-refresh",
            "auth_user_id": "uuid-linked", "expires_at": 9999999999,
        }), f"attach_auth_session was not called correctly: {calls['attach']}"
        assert calls["link"] == ("g@example.com", "uuid-linked"), \
            f"link_auth_user_id was not called correctly -- auth_email() would never resolve: {calls['link']}"
    finally:
        auth._get_client = original_get_client
        supabase_auth.mint_auth_session = original_mint
        auth.attach_auth_session = original_attach
        db_module.link_auth_user_id = original_link
    print("PASS: run_ensure_auth_session_mints_and_links_when_never_attached")


def run_ensure_auth_session_skips_mint_when_already_fresh():
    """An already-fresh (not-near-expiry) auth session must be reused, not
    re-minted -- re-minting on every request would be wasteful and would
    call the real Supabase Admin API far more than necessary."""
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    original_refresh = auth.refresh_auth_session_if_needed
    auth.refresh_auth_session_if_needed = lambda raw_token, threshold_seconds=300: {
        "access_token": "still-fresh-token", "refresh_token": "r", "expires_at": future,
    }
    mint_was_called = {"value": False}
    original_mint = supabase_auth.mint_auth_session
    def _fake_mint(email):
        mint_was_called["value"] = True
        return None
    supabase_auth.mint_auth_session = _fake_mint
    try:
        token = auth.ensure_auth_session("h@example.com", "raw-session-token")
        assert token == "still-fresh-token"
        assert not mint_was_called["value"], "should not have minted a new session when an existing one was fresh"
    finally:
        auth.refresh_auth_session_if_needed = original_refresh
        supabase_auth.mint_auth_session = original_mint
    print("PASS: run_ensure_auth_session_skips_mint_when_already_fresh")


def run_ensure_auth_session_degrades_to_none_on_total_failure():
    original_refresh = auth.refresh_auth_session_if_needed
    auth.refresh_auth_session_if_needed = lambda raw_token, threshold_seconds=300: None
    original_mint = supabase_auth.mint_auth_session
    supabase_auth.mint_auth_session = lambda email: None  # Supabase Auth unavailable/unconfigured
    try:
        token = auth.ensure_auth_session("i@example.com", "raw-session-token")
        assert token is None, "should degrade to None, never raise, when Supabase Auth is unavailable"
    finally:
        auth.refresh_auth_session_if_needed = original_refresh
        supabase_auth.mint_auth_session = original_mint
    print("PASS: run_ensure_auth_session_degrades_to_none_on_total_failure")

    assert auth.ensure_auth_session("", "tok") is None
    assert auth.ensure_auth_session("j@example.com", "") is None
    print("PASS: run_ensure_auth_session_degrades_to_none_on_total_failure (empty-input guards)")


if __name__ == "__main__":
    run_get_authed_client_uses_session_token_when_present()
    run_get_authed_client_falls_back_to_anon_without_token()
    run_get_user_privileged_prefers_service_role()
    run_get_user_privileged_falls_back_when_service_role_unconfigured()
    run_link_auth_user_id_writes_via_service_role()
    run_privileged_setters_prefer_service_role_over_authenticated_grant()
    run_ensure_auth_session_mints_and_links_when_never_attached()
    run_ensure_auth_session_skips_mint_when_already_fresh()
    run_ensure_auth_session_degrades_to_none_on_total_failure()
    print("\nAll test_auth_wiring.py tests passed.")
