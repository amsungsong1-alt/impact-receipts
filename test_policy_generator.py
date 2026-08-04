"""
test_policy_generator.py — golden tests for utils/policy_generator.py
(Laudon Ch.6 Phase 2, C7 policy-generator half).

No pytest, no network calls, no DB, no API. Pure string-output tests. Run
with: python test_policy_generator.py
"""
from datetime import date

from utils.policy_generator import generate_information_policy_draft


def run_full_profile_fills_known_slots():
    failures = []
    profile = {
        "org_name": "Northern Ghana WASH Alliance",
        "account_sector": "WASH",
        "country": "Ghana",
        "primary_donors": ["USAID", "World Bank"],
    }
    draft = generate_information_policy_draft(profile, today=date(2026, 8, 4))

    for expected in ("Northern Ghana WASH Alliance", "WASH", "Ghana", "USAID, World Bank", "2026-08-04"):
        if expected not in draft:
            failures.append(f"expected {expected!r} to appear in the draft, it did not")

    # Known fields must NOT be placeholders.
    for leaked_placeholder in (
        "[Add: your organisation's name]", "[Add: your sector (e.g. Health, WASH)]",
        "[Add: your country of operation]", "[Add: your primary donors]",
    ):
        if leaked_placeholder in draft:
            failures.append(f"a known field incorrectly rendered as a placeholder: {leaked_placeholder!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a fully-populated profile fills every known slot with its actual value, "
          "no placeholder leaks through for a field that was actually supplied.")


def run_empty_profile_placeholders_everything():
    """The whole point of this feature: nothing is ever invented. An empty
    profile must produce ONLY placeholders for every unknown field."""
    failures = []
    draft = generate_information_policy_draft({}, today=date(2026, 8, 4))

    for expected_placeholder in (
        "[Add: your organisation's name]", "[Add: your sector (e.g. Health, WASH)]",
        "[Add: your country of operation]", "[Add: your primary donors]",
    ):
        if expected_placeholder not in draft:
            failures.append(f"expected placeholder {expected_placeholder!r} for a missing field, not found")

    # None of the specific example values from the full-profile test above
    # should ever leak in when the caller supplied nothing. "WASH" is
    # excluded here -- it legitimately appears as an "(e.g. Health, WASH)"
    # authoring hint INSIDE the sector placeholder itself, not as a
    # substituted value; the placeholder assertion above already confirms
    # that whole bracketed instruction is present.
    for forbidden in ("USAID", "Ghana", "World Bank", "Northern Ghana"):
        if forbidden in draft:
            failures.append(f"an empty profile must never contain a real-looking value like {forbidden!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: an empty profile produces only explicit placeholders — nothing is ever invented "
          "or defaulted to a plausible-looking value.")


def run_partial_profile_mixes_correctly():
    failures = []
    draft = generate_information_policy_draft(
        {"account_sector": "Health", "country": ""}, today=date(2026, 8, 4)
    )
    if "Health" not in draft:
        failures.append("supplied account_sector 'Health' should appear in the draft")
    if "[Add: your country of operation]" not in draft:
        failures.append("an empty country string should still render as a placeholder, not blank/None")
    if "[Add: your sector" in draft:
        failures.append("account_sector was supplied ('Health') -- its placeholder must not also appear")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a partially-populated profile correctly mixes real values and placeholders "
          "field-by-field, independently.")


def run_no_donors_list_placeholders_not_empty_string():
    """An empty/missing primary_donors list must placeholder, not silently
    render as an empty 'Primary donors/funders ... :' line."""
    failures = []
    for donors_value in (None, []):
        draft = generate_information_policy_draft({"primary_donors": donors_value}, today=date(2026, 8, 4))
        if "[Add: your primary donors]" not in draft:
            failures.append(f"primary_donors={donors_value!r} should placeholder, got no placeholder present")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: a missing/empty primary_donors list correctly placeholders rather than "
          "rendering a blank donor line.")


def run_never_raises():
    failures = []
    try:
        generate_information_policy_draft(None)
        generate_information_policy_draft({"account_sector": None, "primary_donors": "not-a-list-a-string"})
    except Exception as e:
        failures.append(f"generate_information_policy_draft() must never raise on odd input, got {e!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: never raises on None profile or malformed field types.")


def run_disclaimer_present():
    """The 'this is a draft, not legal advice' framing must always be present
    -- this is a customer-facing document, not an internal note."""
    failures = []
    draft = generate_information_policy_draft({"account_sector": "Health"})
    if "not legal advice" not in draft or "STARTING POINT" not in draft:
        failures.append("the draft-not-legal-advice disclaimer must always be present")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: the 'draft, not legal advice' disclaimer is always present regardless of profile content.")


if __name__ == "__main__":
    run_full_profile_fills_known_slots()
    run_empty_profile_placeholders_everything()
    run_partial_profile_mixes_correctly()
    run_no_donors_list_placeholders_not_empty_string()
    run_never_raises()
    run_disclaimer_present()
