"""
exchange_rates.py — daily-cached FX conversion for pricing/ROI display.

Fetches GHS-based rates from exchangerate-api.com once per day (Streamlit's
own st.cache_data TTL — no DB table needed, since a lost cache on redeploy
just costs one extra API call, same as a cold DB-cache miss would). Falls
back to a static rate table on any failure so the pricing page never
crashes or blocks checkout for lack of network/API key.

All 7 supported currencies (GHS, NGN, KES, ZAR, USD, GBP, EUR) use a
100-subunit convention, so conversion is a straight multiply-and-round.
"""
from __future__ import annotations
import os

SUPPORTED_CURRENCIES = ["GHS", "NGN", "KES", "ZAR", "USD", "GBP", "EUR"]

_CURRENCY_SYMBOLS = {
    "GHS": "GHS",
    "NGN": "₦",
    "KES": "KSh",
    "ZAR": "R",
    "USD": "$",
    "GBP": "£",
    "EUR": "€",
}

# Approximate rates vs. GHS base (1 GHS = X of currency). Hand-updated
# periodically; used whenever the live API is unreachable, unkeyed, or
# returns a malformed response. Never blocks checkout.
_STATIC_FALLBACK_RATES_VS_GHS = {
    "GHS": 1.0,
    "NGN": 105.0,
    "KES": 11.5,
    "ZAR": 1.55,
    "USD": 0.067,
    "GBP": 0.053,
    "EUR": 0.062,
}


def _secret_key() -> str:
    env_val = os.environ.get("EXCHANGE_RATE_API_KEY", "")
    try:
        import streamlit as st
        try:
            val = st.secrets["EXCHANGE_RATE_API_KEY"]
            if val:
                return val
        except KeyError:
            pass
        except Exception:
            pass
        return st.secrets.get("EXCHANGE_RATE_API_KEY") or env_val
    except Exception:
        return env_val


def _fetch_rates_from_api_uncached() -> dict[str, float] | None:
    """GET https://v6.exchangerate-api.com/v6/{key}/latest/GHS. One call
    returns rates for every currency, not one call per pair (important for
    free-tier quota). Returns a dict covering SUPPORTED_CURRENCIES, or None
    on any failure (missing key, network error, bad response, missing
    currencies). Never raises."""
    key = _secret_key()
    if not key:
        return None
    try:
        import requests
        r = requests.get(
            f"https://v6.exchangerate-api.com/v6/{key}/latest/GHS",
            timeout=10,
        )
        data = r.json()
        if data.get("result") != "success":
            return None
        conversion_rates = data.get("conversion_rates", {})
        rates = {}
        for currency in SUPPORTED_CURRENCIES:
            rate = conversion_rates.get(currency)
            if rate is None:
                return None
            rates[currency] = float(rate)
        return rates
    except Exception:
        return None


def _fetch_rates_from_api() -> dict[str, float] | None:
    """Cached wrapper around _fetch_rates_from_api_uncached(). Cached
    separately (not decorated at module-import time) so tests can swap the
    uncached function for a fake without fighting Streamlit's cache."""
    try:
        import streamlit as st
        cached = st.cache_data(ttl=86400, show_spinner=False)(_fetch_rates_from_api_uncached)
        return cached()
    except Exception:
        return _fetch_rates_from_api_uncached()


def get_rates() -> dict[str, float]:
    """Public entry point. Live API result if available, else the static
    fallback. Always returns a complete dict covering every currency in
    SUPPORTED_CURRENCIES — never partial, never raises."""
    rates = _fetch_rates_from_api()
    if rates:
        return rates
    return dict(_STATIC_FALLBACK_RATES_VS_GHS)


def convert_pesewas(amount_ghs_pesewas: int, target_currency: str) -> int:
    """Converts a GHS-pesewas integer amount into the smallest unit of
    target_currency (kobo/cents/pence — all 7 supported currencies use a
    100-subunit convention, so this is a straight multiply-and-round).
    target_currency not in SUPPORTED_CURRENCIES returns the amount
    unchanged (defensive; callers should validate first)."""
    if target_currency not in SUPPORTED_CURRENCIES:
        return amount_ghs_pesewas
    if target_currency == "GHS":
        return amount_ghs_pesewas
    rate = get_rates().get(target_currency, 1.0)
    return round(amount_ghs_pesewas * rate)


def format_amount(amount_minor_units: int, currency: str) -> str:
    """Presentation helper, e.g. format_amount(1234500, 'NGN') -> '₦12,345.00'."""
    symbol = _CURRENCY_SYMBOLS.get(currency, currency)
    major = amount_minor_units / 100
    if currency == "GHS":
        return f"{symbol} {major:,.2f}"
    return f"{symbol}{major:,.2f}"
