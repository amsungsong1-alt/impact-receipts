"""
test_receipts.py — golden tests for utils/receipts.py (Laudon Ch.10, C4).

Pure string-output tests, no DB, no network. Run with: python test_receipts.py
"""

from utils.receipts import build_receipt_html


def run_full_payment_renders_correctly():
    failures = []
    payment = {
        "paystack_reference": "ref_abc123",
        "amount_pesewas": 5000,
        "currency": "GHS",
        "plan": "monthly",
        "status": "success",
        "created_at": "2026-08-04T12:00:00+00:00",
    }
    org_context = {"email": "org@example.com", "primary_donors": ["USAID", "World Bank"]}
    html = build_receipt_html(payment, org_context)

    for expected in ("ref_abc123", "2026-08-04", "org@example.com", "Monthly",
                      "GHS 50.00", "Success", "USAID, World Bank"):
        if expected not in html:
            failures.append(f"expected {expected!r} to appear in the receipt, it did not")

    if "status-success" not in html:
        failures.append("expected the success status class for a 'success' payment")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a fully-populated payment renders every field correctly, including donor context.")


def run_failed_status_uses_other_class():
    # The stylesheet always DEFINES both .status-success/.status-other rules
    # -- check which class is actually APPLIED to the status cell, not just
    # whether either class name appears anywhere in the document.
    failures = []
    html = build_receipt_html({"status": "failed", "amount_pesewas": 500})
    if 'class="status-other"' not in html:
        failures.append("expected the non-success status class applied to a 'failed' payment's status cell")
    if 'class="status-success"' in html:
        failures.append("a failed payment must not have the success status class applied to its status cell")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a non-success status renders the 'other' status class, not the success one.")


def run_missing_fields_placeholder_not_crash():
    failures = []
    html = build_receipt_html({})
    if "—" not in html:
        failures.append("expected em-dash placeholders for an entirely empty payment dict")
    if "GHS 0.00" not in html:
        failures.append("expected a zero amount to render as 'GHS 0.00', not blank or an error")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: an empty payment dict degrades to placeholders, never raises.")


def run_never_raises_on_none():
    failures = []
    try:
        build_receipt_html(None)
        build_receipt_html(None, None)
        build_receipt_html({"amount_pesewas": None, "primary_donors": None}, {"primary_donors": None})
    except Exception as e:
        failures.append(f"build_receipt_html must never raise on None/malformed input, got {e!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: never raises on None payment/org_context or malformed field types.")


def run_no_external_assets():
    """A downloadable receipt must be fully self-contained -- no external
    stylesheet/script/image URLs an offline viewer or PDF converter can't
    resolve."""
    failures = []
    html = build_receipt_html({"paystack_reference": "ref1"})
    for forbidden in ("http://", "https://", "<script"):
        if forbidden in html:
            failures.append(f"receipt HTML must not contain {forbidden!r} -- it must be fully self-contained")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: receipt HTML is fully self-contained, no external assets or scripts.")


if __name__ == "__main__":
    run_full_payment_renders_correctly()
    run_failed_status_uses_other_class()
    run_missing_fields_placeholder_not_crash()
    run_never_raises_on_none()
    run_no_external_assets()
