"""
roi_config.py — per-country/currency MEL consultant day-rate ranges and the
ROI/rework-cost framing derived from them, for the pricing page and paywall.

Only GHS has a sourced figure (DevEx MEL Salary Survey 2024). All other
currencies are estimates pending real sourcing — see is_estimated below.
Do not treat estimated ranges as citable; the UI must visibly flag them
differently from the GHS figure.
"""

ROI_DAY_RATES = {
    "GHS": {
        "country_label": "Ghana",
        "day_rate_low": 1200,
        "day_rate_high": 1800,
        "currency_symbol": "GHS",
        "is_estimated": False,
        "source": "DevEx MEL Salary Survey (2024)",
    },
    "NGN": {
        "country_label": "Nigeria",
        "day_rate_low": 80000,
        "day_rate_high": 150000,
        "currency_symbol": "₦",
        "is_estimated": True,
        "source": "",
    },
    "KES": {
        "country_label": "Kenya",
        "day_rate_low": 15000,
        "day_rate_high": 30000,
        "currency_symbol": "KSh",
        "is_estimated": True,
        "source": "",
    },
    "ZAR": {
        "country_label": "South Africa",
        "day_rate_low": 3000,
        "day_rate_high": 6000,
        "currency_symbol": "R",
        "is_estimated": True,
        "source": "",
    },
    "USD": {
        "country_label": "International (USD)",
        "day_rate_low": 250,
        "day_rate_high": 450,
        "currency_symbol": "$",
        "is_estimated": True,
        "source": "",
    },
    "GBP": {
        "country_label": "International (GBP)",
        "day_rate_low": 200,
        "day_rate_high": 350,
        "currency_symbol": "£",
        "is_estimated": True,
        "source": "",
    },
    "EUR": {
        "country_label": "International (EUR)",
        "day_rate_low": 220,
        "day_rate_high": 380,
        "currency_symbol": "€",
        "is_estimated": True,
        "source": "",
    },
}

REWORK_HOURS_LOW = 40  # matches existing "40+ hours of rework" copy

# Derived so that GHS 1,200-1,800/day reproduces the existing shipped
# "GHS 12,000-17,000" rework-cost band exactly. Applied uniformly to every
# currency's day-rate range so the relationship between day rate and
# rework cost stays consistent across currencies.
_REWORK_MULTIPLIER_LOW = 10.0          # 1200 * 10.0 = 12000
_REWORK_MULTIPLIER_HIGH = 17000 / 1800  # 1800 * (17000/1800) = 17000


def rejected_report_cost_range(currency: str) -> tuple[int, int]:
    """Returns (low, high) cost-of-one-rejected-report in `currency`'s major
    units. Falls back to the GHS entry if `currency` is not configured."""
    entry = ROI_DAY_RATES.get(currency, ROI_DAY_RATES["GHS"])
    low = round(entry["day_rate_low"] * _REWORK_MULTIPLIER_LOW)
    high = round(entry["day_rate_high"] * _REWORK_MULTIPLIER_HIGH)
    return low, high


def cost_range_str(currency: str) -> str:
    """Just the 'GHS 12,000-17,000' figure, no surrounding sentence."""
    entry = ROI_DAY_RATES.get(currency, ROI_DAY_RATES["GHS"])
    resolved_currency = currency if currency in ROI_DAY_RATES else "GHS"
    symbol = entry["currency_symbol"]
    low_cost, high_cost = rejected_report_cost_range(resolved_currency)
    return f"{symbol} {low_cost:,}–{high_cost:,}"


def short_rework_cost_line(currency: str) -> str:
    """Condensed 'GHS 12,000-17,000 in rework costs from a donor-queried
    report' fragment, for the shorter upgrade-prompt captions that don't
    have room for the full roi_copy() paragraph."""
    return f"{cost_range_str(currency)} in rework costs from a donor-queried report"


def day_rate_line(currency: str) -> str:
    """'At Ghana MEL consultant rates (GHS 1,200-1,800/day)' fragment, with
    an estimate disclaimer for currencies whose day rate isn't
    independently sourced yet."""
    entry = ROI_DAY_RATES.get(currency, ROI_DAY_RATES["GHS"])
    symbol = entry["currency_symbol"]
    suffix = " (estimated)" if entry["is_estimated"] else ""
    return (
        f"At {entry['country_label']} MEL consultant rates{suffix} "
        f"({symbol} {entry['day_rate_low']:,}–{entry['day_rate_high']:,}/day)"
    )


def roi_copy(currency: str, monthly_price_ghs_pesewas: int = 5000) -> str:
    """Returns the full ROI sentence for `currency`, matching the existing
    shipped GHS copy verbatim, with an estimate disclaimer appended for
    currencies whose day rate isn't independently sourced yet.
    monthly_price_ghs_pesewas is the Professional-tier monthly price in GHS
    pesewas (callers should pass app.py's PRICE_MONTHLY_GHS) — converted to
    `currency` here so the sentence never shows a raw, unconverted "50" for
    non-GHS currencies."""
    from utils import exchange_rates

    entry = ROI_DAY_RATES.get(currency, ROI_DAY_RATES["GHS"])
    resolved_currency = currency if currency in ROI_DAY_RATES else "GHS"
    symbol = entry["currency_symbol"]
    low_cost, high_cost = rejected_report_cost_range(resolved_currency)
    monthly_display = exchange_rates.format_amount(
        exchange_rates.convert_pesewas(monthly_price_ghs_pesewas, resolved_currency),
        resolved_currency,
    )

    text = (
        f"The ROI is immediate: {monthly_display}/month vs. {symbol} {low_cost:,}–{high_cost:,} "
        f"in rework costs. "
    )
    if entry["is_estimated"]:
        text += (
            f"Estimated average {entry['country_label']} MEL consultant day rate ≈ "
            f"{symbol} {entry['day_rate_low']:,}–{entry['day_rate_high']:,}/day "
            f"(estimated — not yet independently sourced for {entry['country_label']}). "
        )
    else:
        text += (
            f"{entry['source']}: average {entry['country_label']} consultant day rate ≈ "
            f"{symbol} {entry['day_rate_low']:,}–{entry['day_rate_high']:,}/day. "
        )
    text += (
        f"One rejected USAID, Mastercard Foundation, or FCDO report = {REWORK_HOURS_LOW}+ hours of rework. "
        "ImpactProof catches the gaps donors flag — before your report goes out. "
        "Score every KPI in 60 seconds. Download a citable Readiness Card with a reference ID."
    )
    return text
