"""
test_supabase_auth.py — golden tests for utils/supabase_auth.py (the
generate_link + verify_otp JWT-minting flow) and the new Supabase-Auth-token
storage functions in utils/auth.py (attach_auth_session/get_auth_session/
refresh_auth_session_if_needed).

No pytest, no real network calls, no real Supabase project: fake `supabase`
SDK objects stand in for the admin/anon clients (same swap-the-network-seam
approach as test_billing.py's fake Supabase client, applied to the
auth.admin.generate_link/auth.verify_otp/auth.refresh_session/postgrest.auth
shapes instead of the table query-builder shape). Run with:
python test_supabase_auth.py
"""
import os
import time
from datetime import datetime, timezone

from cryptography.fernet import Fernet

# A real (test-only) Fernet key so attach_auth_session()/get_auth_session()'s
# encrypt/decrypt round-trip actually exercises real Fernet, not a stub.
os.environ.setdefault("AUDIT_ENCRYPTION_KEY", Fernet.generate_key().decode())

import supabase as supabase_pkg
import utils.auth as auth
import utils.supabase_auth as supabase_auth


# ---------------------------------------------------------------------------
# Fakes for the supabase-py / gotrue-py auth surface
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, access_token, refresh_token, expires_at):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at


class _FakeUser:
    def __init__(self, id_):
        self.id = id_


class _FakeAuthResp:
    def __init__(self, session, user):
        self.session = session
        self.user = user


class _FakeLinkProps:
    def __init__(self, hashed_token):
        self.hashed_token = hashed_token


class _FakeLinkResp:
    def __init__(self, hashed_token):
        self.properties = _FakeLinkProps(hashed_token) if hashed_token else None


class _FakeAdminAuth:
    def __init__(self, hashed_token="fake-hashed-token"):
        self._hashed_token = hashed_token

    def generate_link(self, params):
        assert params["type"] == "magiclink"
        assert params["email"]
        return _FakeLinkResp(self._hashed_token)


class _FakeAuth:
    def __init__(self, hashed_token="fake-hashed-token"):
        self.admin = _FakeAdminAuth(hashed_token)
        self._verify_result = (_FakeSession("access-123", "refresh-456", 1999999999),
                                _FakeUser("uuid-abc"))
        self._refresh_result = (_FakeSession("access-789", "refresh-000", 2000000000),
                                 _FakeUser("uuid-abc"))

    def verify_otp(self, params):
        assert params["type"] == "magiclink"
        assert params["token_hash"]
        session, user = self._verify_result
        return _FakeAuthResp(session, user)

    def refresh_session(self, refresh_token):
        assert refresh_token
        session, user = self._refresh_result
        return _FakeAuthResp(session, user)


class _FakePostgrest:
    def __init__(self):
        self.auth_token = None

    def auth(self, token):
        self.auth_token = token


class _FakeClient:
    def __init__(self, hashed_token="fake-hashed-token"):
        self.auth = _FakeAuth(hashed_token)
        self.postgrest = _FakePostgrest()


def _fake_create_client_factory(hashed_token="fake-hashed-token"):
    def _fake_create_client(url, key):
        return _FakeClient(hashed_token)
    return _fake_create_client


def _set_supabase_env():
    os.environ["SUPABASE_URL"] = "https://fake-project.supabase.co"
    os.environ["SUPABASE_ANON_KEY"] = "fake-anon-key"
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "fake-service-role-key"


def _clear_supabase_env():
    for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# utils/supabase_auth.py
# ---------------------------------------------------------------------------

def run_mint_auth_session():
    _set_supabase_env()
    original_create_client = supabase_pkg.create_client
    original_admin_client = supabase_auth._admin_client
    supabase_pkg.create_client = _fake_create_client_factory()
    supabase_auth._admin_client = None
    try:
        session = supabase_auth.mint_auth_session("user@example.com")
        assert session is not None, "mint_auth_session should succeed with a well-formed fake response"
        assert session["access_token"] == "access-123"
        assert session["refresh_token"] == "refresh-456"
        assert session["auth_user_id"] == "uuid-abc"
        assert session["expires_at"] == 1999999999
    finally:
        supabase_pkg.create_client = original_create_client
        supabase_auth._admin_client = original_admin_client
        _clear_supabase_env()
    print("PASS: run_mint_auth_session")


def run_mint_auth_session_no_email():
    assert supabase_auth.mint_auth_session("") is None
    assert supabase_auth.mint_auth_session(None) is None
    print("PASS: run_mint_auth_session_no_email")


def run_mint_auth_session_no_service_key_configured():
    """Supabase Auth is additive -- an unconfigured service-role key must
    degrade to None, never raise, so login keeps working without it."""
    _clear_supabase_env()
    os.environ["SUPABASE_URL"] = "https://fake-project.supabase.co"
    os.environ["SUPABASE_ANON_KEY"] = "fake-anon-key"
    original_admin_client = supabase_auth._admin_client
    supabase_auth._admin_client = None
    try:
        assert supabase_auth.mint_auth_session("user@example.com") is None
    finally:
        supabase_auth._admin_client = original_admin_client
        _clear_supabase_env()
    print("PASS: run_mint_auth_session_no_service_key_configured")


def run_mint_auth_session_malformed_link_response():
    """A future gotrue-py version renaming/removing `properties.hashed_token`
    must degrade to None, not raise -- this is the exact SDK response-shape
    fragility flagged in the module docstring."""
    _set_supabase_env()
    original_create_client = supabase_pkg.create_client
    original_admin_client = supabase_auth._admin_client
    supabase_pkg.create_client = _fake_create_client_factory(hashed_token=None)
    supabase_auth._admin_client = None
    try:
        assert supabase_auth.mint_auth_session("user@example.com") is None
    finally:
        supabase_pkg.create_client = original_create_client
        supabase_auth._admin_client = original_admin_client
        _clear_supabase_env()
    print("PASS: run_mint_auth_session_malformed_link_response")


def run_refresh_auth_session():
    _set_supabase_env()
    original_create_client = supabase_pkg.create_client
    supabase_pkg.create_client = _fake_create_client_factory()
    try:
        result = supabase_auth.refresh_auth_session("refresh-456")
        assert result is not None
        assert result["access_token"] == "access-789"
        assert result["refresh_token"] == "refresh-000"
        assert supabase_auth.refresh_auth_session("") is None
    finally:
        supabase_pkg.create_client = original_create_client
        _clear_supabase_env()
    print("PASS: run_refresh_auth_session")


def run_build_session_scoped_client():
    _set_supabase_env()
    original_create_client = supabase_pkg.create_client
    supabase_pkg.create_client = _fake_create_client_factory()
    try:
        client = supabase_auth.build_session_scoped_client("some-access-token")
        assert client is not None
        assert client.postgrest.auth_token == "some-access-token"
        assert supabase_auth.build_session_scoped_client("") is None
    finally:
        supabase_pkg.create_client = original_create_client
        _clear_supabase_env()
    print("PASS: run_build_session_scoped_client")


# ---------------------------------------------------------------------------
# utils/auth.py — attach_auth_session / get_auth_session /
# refresh_auth_session_if_needed (session-scoped token storage)
# ---------------------------------------------------------------------------

class _FakeSessionsQuery:
    def __init__(self, rows):
        self._rows = rows
        self._op = None
        self._payload = None
        self._filters = []

    def select(self, *_a, **_kw):
        self._op = self._op or "select"
        return self

    def update(self, fields):
        self._op = "update"
        self._payload = dict(fields)
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def execute(self):
        matches = [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]
        if self._op == "update":
            for r in matches:
                r.update(self._payload)

        class _Res:
            pass
        res = _Res()
        res.data = matches
        return res


class _FakeAuthDbClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "sessions"
        return _FakeSessionsQuery(self._rows)


def run_attach_and_get_auth_session():
    token_hash = auth._hash_token("raw-token-1")
    rows = [{"token_hash": token_hash}]
    fake = _FakeAuthDbClient(rows)
    original = auth._get_client
    auth._get_client = lambda: fake
    try:
        far_future = int(time.time()) + 3600
        auth.attach_auth_session("raw-token-1", {
            "access_token": "acc-1", "refresh_token": "ref-1", "expires_at": far_future,
        })
        stored = rows[0]
        assert stored["auth_access_token"] != "acc-1", "must be encrypted at rest, not plaintext"
        result = auth.get_auth_session("raw-token-1")
        assert result is not None
        assert result["access_token"] == "acc-1"
        assert result["refresh_token"] == "ref-1"
        assert result["expires_at"] is not None
        # No auth session ever attached for this token -> None, not a crash
        rows.append({"token_hash": auth._hash_token("raw-token-never-attached")})
        assert auth.get_auth_session("raw-token-never-attached") is None
        assert auth.get_auth_session("") is None
        assert auth.attach_auth_session("", {"access_token": "x", "refresh_token": "y"}) is None
        assert auth.attach_auth_session("raw-token-1", None) is None
    finally:
        auth._get_client = original
    print("PASS: run_attach_and_get_auth_session")


def run_refresh_auth_session_if_needed_still_fresh():
    """A token that isn't near expiry must be returned as-is, without calling
    utils.supabase_auth.refresh_auth_session at all (avoids an unnecessary
    refresh-token rotation on every page load)."""
    token_hash = auth._hash_token("raw-token-2")
    rows = [{"token_hash": token_hash}]
    fake = _FakeAuthDbClient(rows)
    original_client = auth._get_client
    auth._get_client = lambda: fake
    original_refresh = supabase_auth.refresh_auth_session
    _refresh_called = {"count": 0}

    def _tripwire(refresh_token):
        _refresh_called["count"] += 1
        return None
    supabase_auth.refresh_auth_session = _tripwire
    try:
        far_future = int(time.time()) + 3600
        auth.attach_auth_session("raw-token-2", {
            "access_token": "acc-fresh", "refresh_token": "ref-fresh", "expires_at": far_future,
        })
        result = auth.refresh_auth_session_if_needed("raw-token-2", threshold_seconds=300)
        assert result is not None
        assert result["access_token"] == "acc-fresh"
        assert _refresh_called["count"] == 0, "must not refresh a token that isn't near expiry"
    finally:
        auth._get_client = original_client
        supabase_auth.refresh_auth_session = original_refresh
    print("PASS: run_refresh_auth_session_if_needed_still_fresh")


def run_refresh_auth_session_if_needed_expiring_soon():
    """A token expiring within threshold_seconds must be refreshed and the
    new tokens persisted back onto the sessions row."""
    token_hash = auth._hash_token("raw-token-3")
    rows = [{"token_hash": token_hash}]
    fake = _FakeAuthDbClient(rows)
    original_client = auth._get_client
    auth._get_client = lambda: fake
    original_refresh = supabase_auth.refresh_auth_session

    def _fake_refresh(refresh_token):
        assert refresh_token == "ref-old"
        return {"access_token": "acc-new", "refresh_token": "ref-new",
                "auth_user_id": "uuid-abc", "expires_at": int(time.time()) + 7200}
    supabase_auth.refresh_auth_session = _fake_refresh
    try:
        soon = int(time.time()) + 10  # within any reasonable threshold
        auth.attach_auth_session("raw-token-3", {
            "access_token": "acc-old", "refresh_token": "ref-old", "expires_at": soon,
        })
        result = auth.refresh_auth_session_if_needed("raw-token-3", threshold_seconds=300)
        assert result is not None
        assert result["access_token"] == "acc-new"
        persisted = auth.get_auth_session("raw-token-3")
        assert persisted["access_token"] == "acc-new", "refreshed tokens must be persisted, not just returned"
        assert persisted["refresh_token"] == "ref-new"
    finally:
        auth._get_client = original_client
        supabase_auth.refresh_auth_session = original_refresh
    print("PASS: run_refresh_auth_session_if_needed_expiring_soon")


def run_refresh_auth_session_if_needed_refresh_fails_keeps_old_token():
    """If Supabase itself is unreachable, keep serving the possibly-stale
    token rather than returning nothing -- Supabase Auth/RLS is additive and
    must never be a reason to break a page render."""
    token_hash = auth._hash_token("raw-token-4")
    rows = [{"token_hash": token_hash}]
    fake = _FakeAuthDbClient(rows)
    original_client = auth._get_client
    auth._get_client = lambda: fake
    original_refresh = supabase_auth.refresh_auth_session
    supabase_auth.refresh_auth_session = lambda refresh_token: None
    try:
        soon = int(time.time()) + 10
        auth.attach_auth_session("raw-token-4", {
            "access_token": "acc-stale", "refresh_token": "ref-stale", "expires_at": soon,
        })
        result = auth.refresh_auth_session_if_needed("raw-token-4", threshold_seconds=300)
        assert result is not None
        assert result["access_token"] == "acc-stale"
    finally:
        auth._get_client = original_client
        supabase_auth.refresh_auth_session = original_refresh
    print("PASS: run_refresh_auth_session_if_needed_refresh_fails_keeps_old_token")


def run_refresh_auth_session_if_needed_no_session_attached():
    token_hash = auth._hash_token("raw-token-5")
    rows = [{"token_hash": token_hash}]
    fake = _FakeAuthDbClient(rows)
    original_client = auth._get_client
    auth._get_client = lambda: fake
    try:
        assert auth.refresh_auth_session_if_needed("raw-token-5") is None
        assert auth.refresh_auth_session_if_needed("") is None
    finally:
        auth._get_client = original_client
    print("PASS: run_refresh_auth_session_if_needed_no_session_attached")


if __name__ == "__main__":
    run_mint_auth_session()
    run_mint_auth_session_no_email()
    run_mint_auth_session_no_service_key_configured()
    run_mint_auth_session_malformed_link_response()
    run_refresh_auth_session()
    run_build_session_scoped_client()
    run_attach_and_get_auth_session()
    run_refresh_auth_session_if_needed_still_fresh()
    run_refresh_auth_session_if_needed_expiring_soon()
    run_refresh_auth_session_if_needed_refresh_fails_keeps_old_token()
    run_refresh_auth_session_if_needed_no_session_attached()
    print("\nAll test_supabase_auth.py tests passed.")
