"""
utils/twofactor.py — TOTP-based two-factor authentication (Laudon Ch.8
hardening, C3: "two-factor authentication available, and mandatory for owner
and admin"). This app's login is already single-factor-by-possession (an
emailed magic link + 6-digit code both land in the same inbox -- one factor,
not two, however it feels to the user). TOTP adds a genuine second,
independent factor (an authenticator app on a separate device) specifically
for the internal admin dashboard, where a compromised email account would
otherwise be sufficient to reach account/billing data across every customer.

Storage: users.totp_secret (Fernet-encrypted, see utils/crypto.py) and
users.totp_enabled (see supabase/migrations/0050_users_role_and_totp.sql).
This module never touches the database directly -- callers (app.py) read/
write those columns via utils.db, same convention as every other module
here, and pass the decrypted secret in.

Degrades gracefully like every other module in this codebase: a missing
`pyotp` dependency or malformed secret returns False/None rather than
raising, so a 2FA outage fails closed on verification (never grants access)
but never crashes the app for a non-admin user who never touches this code
path at all.
"""
from __future__ import annotations


def generate_totp_secret() -> str:
    """A new random base32 TOTP secret, generated at enrollment time --
    never derived from anything guessable (email, timestamp)."""
    import pyotp
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, email: str, issuer: str = "ImpactProof") -> str | None:
    """otpauth:// URI for a QR code, so the user can add this account to an
    authenticator app (Google Authenticator, 1Password, Authy, etc.) without
    hand-typing the secret. Returns None on any failure (e.g. pyotp not
    installed) -- callers must show the raw secret as a manual-entry
    fallback in that case, never block enrollment entirely on the QR path."""
    if not secret or not email:
        return None
    try:
        import pyotp
        return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)
    except Exception:
        return None


def verify_totp(secret: str, code: str) -> bool:
    """True if `code` is a currently-valid TOTP for `secret`. valid_window=1
    tolerates one 30-second step of clock drift in either direction (a
    real-world authenticator-app/server clock skew accommodation, not a
    security weakening -- it does not enlarge the code's guessable window
    meaningfully, +/-30s vs. the code's own 30s validity). Fails closed
    (False) on any malformed input or missing dependency -- never raises,
    never treats an error as "verified"."""
    if not secret or not code:
        return False
    try:
        import pyotp
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def qr_code_png_bytes(provisioning_uri: str) -> bytes | None:
    """PNG bytes for a scannable QR code of the provisioning URI, or None on
    any failure (missing `qrcode` dependency, invalid URI) -- callers must
    fall back to showing the secret/URI as text for manual entry."""
    if not provisioning_uri:
        return None
    try:
        import io
        import qrcode
        img = qrcode.make(provisioning_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None
