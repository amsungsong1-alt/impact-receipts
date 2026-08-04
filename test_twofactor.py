"""
test_twofactor.py — golden tests for utils/twofactor.py (Laudon Ch.8
hardening, C3: mandatory TOTP 2FA for admin/owner accounts).

No pytest, no network calls: pyotp/qrcode are real (lightweight, pure)
dependencies exercised directly -- no fake needed, since TOTP is a pure
algorithm (HMAC over a time counter), not a network call.
Run with: python test_twofactor.py
"""
import time

import utils.twofactor as twofactor


def run_generate_totp_secret_is_random_and_usable():
    a = twofactor.generate_totp_secret()
    b = twofactor.generate_totp_secret()
    assert a and b, "generated secrets must not be empty"
    assert a != b, "two calls must not produce the same secret"
    assert len(a) >= 16, "a base32 TOTP secret should be at least 16 chars"
    print("PASS: run_generate_totp_secret_is_random_and_usable")


def run_verify_totp_accepts_current_code_rejects_wrong_code():
    import pyotp
    secret = twofactor.generate_totp_secret()
    current_code = pyotp.TOTP(secret).now()
    assert twofactor.verify_totp(secret, current_code), "a genuinely current code should verify"
    assert not twofactor.verify_totp(secret, "000000"), "an arbitrary wrong code should not verify"

    other_secret = twofactor.generate_totp_secret()
    other_code = pyotp.TOTP(other_secret).now()
    if other_code != current_code:
        assert not twofactor.verify_totp(secret, other_code), \
            "a code generated from a DIFFERENT secret must not verify against this one"
    print("PASS: run_verify_totp_accepts_current_code_rejects_wrong_code")


def run_verify_totp_fails_closed_on_bad_input():
    assert not twofactor.verify_totp("", "123456")
    assert not twofactor.verify_totp("SECRET", "")
    assert not twofactor.verify_totp(None, None)
    assert not twofactor.verify_totp("not-valid-base32!!!", "123456")
    print("PASS: run_verify_totp_fails_closed_on_bad_input")


def run_provisioning_uri_contains_issuer_and_email():
    secret = twofactor.generate_totp_secret()
    uri = twofactor.get_provisioning_uri(secret, "founder@example.com", issuer="ImpactProof")
    assert uri, "a valid secret+email should produce a provisioning URI"
    assert uri.startswith("otpauth://totp/")
    assert "ImpactProof" in uri
    assert "founder%40example.com" in uri or "founder@example.com" in uri

    assert twofactor.get_provisioning_uri("", "founder@example.com") is None
    assert twofactor.get_provisioning_uri(secret, "") is None
    print("PASS: run_provisioning_uri_contains_issuer_and_email")


def run_qr_code_png_bytes_produces_valid_png():
    secret = twofactor.generate_totp_secret()
    uri = twofactor.get_provisioning_uri(secret, "founder@example.com")
    png = twofactor.qr_code_png_bytes(uri)
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n"), "should be a genuine PNG file"

    assert twofactor.qr_code_png_bytes("") is None
    print("PASS: run_qr_code_png_bytes_produces_valid_png")


if __name__ == "__main__":
    run_generate_totp_secret_is_random_and_usable()
    run_verify_totp_accepts_current_code_rejects_wrong_code()
    run_verify_totp_fails_closed_on_bad_input()
    run_provisioning_uri_contains_issuer_and_email()
    run_qr_code_png_bytes_produces_valid_png()
    print("\nAll test_twofactor.py tests passed.")
