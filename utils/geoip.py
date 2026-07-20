"""
geoip.py — IP-based default currency, decoupled from exchange_rates.py
(different concern, different provider, independently swappable).

Reads the visitor's forwarding IP from request headers (same st.context
pattern already used at app.py's _get_app_url()/utils/paystack.py's
_base_url() for the Host header) and calls a free IP-geolocation API to
map country -> currency. Never raises, never blocks page render; falls
back to USD on any failure or unmapped country.
"""
from __future__ import annotations
import os

_COUNTRY_TO_CURRENCY = {
    "GH": "GHS",
    "NG": "NGN",
    "KE": "KES",
    "ZA": "ZAR",
    "GB": "GBP",
    # Eurozone
    "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "NL": "EUR",
    "BE": "EUR", "IE": "EUR", "PT": "EUR", "AT": "EUR", "FI": "EUR",
    "GR": "EUR", "LU": "EUR", "SK": "EUR", "SI": "EUR", "LT": "EUR",
    "LV": "EUR", "EE": "EUR", "CY": "EUR", "MT": "EUR", "HR": "EUR",
}

_DEFAULT_CURRENCY = "USD"


def _secret_key() -> str:
    env_val = os.environ.get("IP_GEOLOCATION_API_KEY", "")
    try:
        import streamlit as st
        try:
            val = st.secrets["IP_GEOLOCATION_API_KEY"]
            if val:
                return val
        except KeyError:
            pass
        except Exception:
            pass
        return st.secrets.get("IP_GEOLOCATION_API_KEY") or env_val
    except Exception:
        return env_val


def _visitor_ip() -> str:
    """Best-effort visitor IP from forwarded headers (behind the existing
    Nginx reverse proxy on the VPS path, or Streamlit Cloud's own forwarded
    headers). Returns "" if unavailable."""
    try:
        import streamlit as st
        headers = st.context.headers
        for header_name in ("X-Forwarded-For", "x-forwarded-for"):
            val = headers.get(header_name)
            if val:
                return val.split(",")[0].strip()
        return ""
    except Exception:
        return ""


def _country_from_ip(ip: str) -> str:
    """Calls a free IP-geolocation API to resolve a country code. Returns
    "" on any failure. ipapi.co's free tier accepts no key for low volume;
    IP_GEOLOCATION_API_KEY is only appended if configured."""
    if not ip:
        return ""
    try:
        import requests
        url = f"https://ipapi.co/{ip}/country/"
        key = _secret_key()
        params = {"key": key} if key else {}
        r = requests.get(url, params=params, timeout=5)
        code = (r.text or "").strip().upper()
        if len(code) == 2:
            return code
        return ""
    except Exception:
        return ""


def default_currency_from_ip() -> str:
    """Public entry point. Resolves the visitor's country from their IP and
    maps it to a supported currency; falls back to USD on any failure or
    unmapped country. Caches the result in st.session_state for the
    duration of the session (per-visitor, not a shared st.cache_data
    cache), so this only ever does the network round trip once per visit."""
    try:
        import streamlit as st
        if "_geoip_default_currency" in st.session_state:
            return st.session_state["_geoip_default_currency"]
    except Exception:
        return _DEFAULT_CURRENCY

    try:
        ip = _visitor_ip()
        country = _country_from_ip(ip)
        currency = _COUNTRY_TO_CURRENCY.get(country, _DEFAULT_CURRENCY)
    except Exception:
        currency = _DEFAULT_CURRENCY

    try:
        import streamlit as st
        st.session_state["_geoip_default_currency"] = currency
    except Exception:
        pass
    return currency
