"""
utils/mel_calendar.py — Laudon Ch.9 CRM, C3: the MEL donor-reporting
calendar.

Loads knowledge/mel_calendar.yaml (versioned, hot-reloadable -- same
discipline as utils/taxonomy.py/utils/inference.py) and exposes which
calendar months count as an expected donor-reporting window. The actual
months are a labeled placeholder assumption (see the YAML file's own
comment), not researched fact -- this module just reads whatever is there.

No Streamlit import, no API calls -- pure read of a static YAML file, same
UI-free discipline as evaluator.py/diagnostics.py/utils/taxonomy.py.
"""
from __future__ import annotations
import os

import yaml

_CALENDAR_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "mel_calendar.yaml"
)


def load_mel_calendar() -> dict:
    """Re-reads knowledge/mel_calendar.yaml fresh on every call -- hot-
    reloadable, same convention as utils/taxonomy.py::load_taxonomy().
    Returns {} if the file is missing or malformed rather than raising."""
    if not os.path.isfile(_CALENDAR_PATH):
        return {}
    try:
        with open(_CALENDAR_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def reporting_months(calendar: dict | None = None) -> list:
    cal = calendar if calendar is not None else load_mel_calendar()
    months = cal.get("reporting_months", [])
    return months if isinstance(months, list) else []


def is_reporting_month(month: int, calendar: dict | None = None) -> bool:
    """True if `month` (1-12) is one of the configured reporting-season
    months. Never raises on a malformed/out-of-range month."""
    try:
        return int(month) in reporting_months(calendar)
    except (TypeError, ValueError):
        return False
