"""
test_mel_calendar.py — golden tests for utils/mel_calendar.py (Laudon Ch.9
CRM, C3): loading knowledge/mel_calendar.yaml and the reporting-month check.

Mirrors test_taxonomy.py's structure exactly (same hot-reload convention as
utils/taxonomy.py). No pytest, no network calls. Run with:
python test_mel_calendar.py
"""

from utils import mel_calendar


def run_calendar_loads_cleanly():
    failures = []
    data = mel_calendar.load_mel_calendar()

    if not data:
        failures.append("load_mel_calendar() returned an empty dict -- knowledge/mel_calendar.yaml failed to load")
    if "reporting_months" not in data:
        failures.append("mel_calendar.yaml is missing the expected 'reporting_months' key")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: MEL calendar loads cleanly — 'reporting_months' key present.")


def run_is_reporting_month():
    failures = []
    calendar = {"reporting_months": [3, 6, 9, 12, 1]}

    for month in (3, 6, 9, 12, 1):
        if not mel_calendar.is_reporting_month(month, calendar):
            failures.append(f"expected month {month} to be a reporting month")
    for month in (2, 4, 5, 7, 8, 10, 11):
        if mel_calendar.is_reporting_month(month, calendar):
            failures.append(f"expected month {month} to NOT be a reporting month")

    # Malformed/out-of-range input degrades to False, never raises.
    if mel_calendar.is_reporting_month(None, calendar):
        failures.append("expected None month to degrade to False")
    if mel_calendar.is_reporting_month("not a month", calendar):
        failures.append("expected a non-numeric month to degrade to False")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: is_reporting_month — correct membership check, malformed input degrades to False.")


def run_degrades_gracefully_on_missing_file():
    """load_mel_calendar() must return {} (not raise) when
    knowledge/mel_calendar.yaml doesn't exist -- matches
    utils/inference.py's/utils/taxonomy.py's degrade-gracefully convention."""
    failures = []
    original_path = mel_calendar._CALENDAR_PATH
    mel_calendar._CALENDAR_PATH = "/nonexistent/path/that/does/not/exist.yaml"
    try:
        data = mel_calendar.load_mel_calendar()
        if data != {}:
            failures.append(f"expected {{}} for a missing calendar file, got {data}")
        if mel_calendar.reporting_months() != []:
            failures.append("expected [] for reporting_months when the calendar file can't load")
        if mel_calendar.is_reporting_month(6):
            failures.append("expected is_reporting_month to degrade to False when the calendar file can't load")
    finally:
        mel_calendar._CALENDAR_PATH = original_path

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: missing calendar file degrades to {}/[]/False everywhere, never raises.")


if __name__ == "__main__":
    run_calendar_loads_cleanly()
    run_is_reporting_month()
    run_degrades_gracefully_on_missing_file()
