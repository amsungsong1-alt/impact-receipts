"""
utils/crypto.py — Fernet-based field-level encryption for stored audit
content (utils/audits.py's submissions_json/evaluations_json, and the
Logframe Library's free-text indicator columns).

Key rotation is explicitly OUT OF SCOPE for this module: encrypt_text()/
decrypt_text() use a single active key read from AUDIT_ENCRYPTION_KEY.
Rotating the key would require a separate re-encryption migration script
(decrypt every row with the old key, re-encrypt with the new one) -- not
implemented here. Losing AUDIT_ENCRYPTION_KEY makes all encrypted content
permanently unrecoverable -- back it up somewhere outside Supabase/Streamlit
secrets, not just in one place.

Same secrets-fallback convention as every other module: st.secrets ->
os.environ, never raises on a missing key -- callers must check for a None
return and fail closed (never silently store/return plaintext).
"""
from __future__ import annotations
import os


def _get_secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(key) or os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    key = _get_secret("AUDIT_ENCRYPTION_KEY")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception:
        _fernet = None
    return _fernet


def encrypt_text(plaintext: str) -> str | None:
    """Returns ciphertext (ascii-safe, storable in a plain text column), or
    None if AUDIT_ENCRYPTION_KEY isn't configured or encryption fails --
    callers must treat None as "cannot proceed," never fall back to storing
    plaintext."""
    f = _get_fernet()
    if f is None or plaintext is None:
        return None
    try:
        return f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    except Exception:
        return None


def decrypt_text(ciphertext: str) -> str | None:
    """Returns the original plaintext, or None if decryption fails (wrong/
    missing key, corrupted ciphertext, or not actually Fernet-encrypted)."""
    f = _get_fernet()
    if f is None or not ciphertext:
        return None
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception:
        return None
