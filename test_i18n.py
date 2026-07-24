"""
test_i18n.py — golden tests for the pricing/ROI internationalization layer:
utils/exchange_rates.py, utils/geoip.py, roi_config.py, and app.py's
_checkout_route_for_currency() currency-routing decision.

No pytest, no real network calls: utils.exchange_rates's
`_fetch_rates_from_api_uncached` is swapped for a fake (same
swap-the-network-seam approach as test_billing.py's `paystack.requests`
fake), and utils.geoip's `_visitor_ip`/`_country_from_ip` are swapped
directly. Run with: python test_i18n.py
"""

import streamlit as st

import roi_config
import utils.exchange_rates as exchange_rates
import utils.geoip as geoip


def run_exchange_rates():
    failures = []
    original_fetch = exchange_rates._fetch_rates_from_api_uncached
    exchange_rates._fetch_rates_from_api_uncached = lambda: {
        "GHS": 1.0, "NGN": 100.0, "KES": 10.0, "ZAR": 2.0,
        "USD": 0.1, "GBP": 0.08, "EUR": 0.09,
    }
    try:
        # 1. GHS is always a straight passthrough, no rate lookup needed.
        if exchange_rates.convert_pesewas(5000, "GHS") != 5000:
            failures.append("convert_pesewas(GHS) should return the amount unchanged")

        # 2. Known fixture rate converts correctly (5000 pesewas * 100.0 = 500000).
        got = exchange_rates.convert_pesewas(5000, "NGN")
        if got != 500000:
            failures.append(f"convert_pesewas(NGN) expected 500000, got {got}")

        # 3. Unsupported currency code returns the amount unchanged (defensive).
        if exchange_rates.convert_pesewas(5000, "XXX") != 5000:
            failures.append("convert_pesewas with an unsupported currency should return the amount unchanged")

        # 4. format_amount renders a currency-appropriate string.
        formatted = exchange_rates.format_amount(500000, "NGN")
        if "5,000.00" not in formatted or "₦" not in formatted:
            failures.append(f"format_amount(NGN) unexpected output: {formatted!r}")
        formatted_ghs = exchange_rates.format_amount(5000, "GHS")
        if formatted_ghs != "GHS 50.00":
            failures.append(f"format_amount(GHS) expected 'GHS 50.00', got {formatted_ghs!r}")

        # 5. Static fallback path: API returns None -> static rates used, never raises.
        exchange_rates._fetch_rates_from_api_uncached = lambda: None
        rates = exchange_rates.get_rates()
        if rates != exchange_rates._STATIC_FALLBACK_RATES_VS_GHS:
            failures.append("get_rates() should return the static fallback table when the API is unreachable")
        if not exchange_rates.convert_pesewas(5000, "USD") > 0:
            failures.append("convert_pesewas should still produce a positive amount on the fallback path")

    finally:
        exchange_rates._fetch_rates_from_api_uncached = original_fetch

    # 6. The real (unswapped) _fetch_rates_from_api_uncached rejects an
    # incomplete API response (missing a supported currency) rather than
    # silently returning a partial rate table -- tested against the actual
    # parsing logic via a fake `requests`, not the swapped-out function
    # above, since a caller-supplied fetch function could otherwise bypass
    # this validation entirely.
    import utils.exchange_rates as _er_module

    class _FakeGeoResponse:
        def json(self):
            return {
                "result": "success",
                "conversion_rates": {"GHS": 1.0, "NGN": 100.0},  # missing KES/ZAR/USD/GBP/EUR
            }

    class _FakeRequestsModule:
        @staticmethod
        def get(url, timeout=None):
            return _FakeGeoResponse()

    import sys as _sys
    original_secret_key = _er_module._secret_key
    original_requests_module = _sys.modules.get("requests")
    _er_module._secret_key = lambda: "fake_key"
    _sys.modules["requests"] = _FakeRequestsModule()
    try:
        incomplete_result = _er_module._fetch_rates_from_api_uncached()
        if incomplete_result is not None:
            failures.append("an incomplete conversion_rates response should make "
                             f"_fetch_rates_from_api_uncached return None, got {incomplete_result!r}")
    finally:
        _er_module._secret_key = original_secret_key
        if original_requests_module is not None:
            _sys.modules["requests"] = original_requests_module
        else:
            del _sys.modules["requests"]

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: exchange_rates — conversion math, formatting, and static-fallback degradation.")


def run_geoip():
    failures = []
    original_visitor_ip = geoip._visitor_ip
    original_country_from_ip = geoip._country_from_ip
    st.session_state.clear()
    try:
        # 1. Known country maps to its currency.
        geoip._visitor_ip = lambda: "1.2.3.4"
        geoip._country_from_ip = lambda ip: "GH"
        if geoip.default_currency_from_ip() != "GHS":
            failures.append("default_currency_from_ip should map GH -> GHS")

        # 2. Unmapped country falls back to USD.
        st.session_state.clear()
        geoip._country_from_ip = lambda ip: "JP"
        if geoip.default_currency_from_ip() != "USD":
            failures.append("default_currency_from_ip should default to USD for an unmapped country")

        # 3. API/IP failure never raises, falls back to USD.
        st.session_state.clear()
        geoip._visitor_ip = lambda: ""
        geoip._country_from_ip = lambda ip: (_ for _ in ()).throw(ConnectionError("down"))
        try:
            result = geoip.default_currency_from_ip()
        except Exception as exc:
            failures.append(f"default_currency_from_ip raised on failure: {exc!r}")
            result = None
        if result != "USD":
            failures.append(f"default_currency_from_ip should default to USD on failure, got {result!r}")

        # 4. Result is cached in session_state for the rest of the session.
        st.session_state.clear()
        geoip._visitor_ip = lambda: "1.2.3.4"
        geoip._country_from_ip = lambda ip: "NG"
        first = geoip.default_currency_from_ip()
        geoip._country_from_ip = lambda ip: "KE"  # should not be consulted again
        second = geoip.default_currency_from_ip()
        if first != "NGN" or second != "NGN":
            failures.append(f"default_currency_from_ip should cache per-session, got {first!r} then {second!r}")
    finally:
        geoip._visitor_ip = original_visitor_ip
        geoip._country_from_ip = original_country_from_ip
        st.session_state.clear()

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: geoip — country-to-currency mapping, unmapped/failure fallback to USD, per-session caching.")


def run_roi_config():
    failures = []

    # 1. Byte-for-byte regression guard: today's shipped GHS copy must not
    # silently change (GHS 1,200-1,800/day -> GHS 12,000-17,000).
    got = roi_config.rejected_report_cost_range("GHS")
    if got != (12000, 17000):
        failures.append(f"rejected_report_cost_range('GHS') expected (12000, 17000), got {got}")

    # 2. Unconfigured currency falls back to the GHS range.
    if roi_config.rejected_report_cost_range("XXX") != (12000, 17000):
        failures.append("rejected_report_cost_range should fall back to GHS for an unconfigured currency")

    # 3. Estimated currencies carry a visible disclaimer; GHS does not.
    ngn_copy = roi_config.roi_copy("NGN")
    if "estimated" not in ngn_copy.lower():
        failures.append("roi_copy('NGN') should disclose that its day-rate figure is estimated")
    ghs_copy = roi_config.roi_copy("GHS")
    if "estimated" in ghs_copy.lower():
        failures.append("roi_copy('GHS') should not carry an estimate disclaimer (it's sourced)")
    if "DevEx MEL Salary Survey" not in ghs_copy:
        failures.append("roi_copy('GHS') should keep citing its real source")

    # 4. No fabricated source citation for estimated currencies.
    for code, entry in roi_config.ROI_DAY_RATES.items():
        if entry["is_estimated"] and entry["source"]:
            failures.append(f"ROI_DAY_RATES[{code!r}] is_estimated=True but has a non-empty 'source' — "
                             "estimated figures must not carry a fabricated citation")

    # 5. cost_range_str / short_rework_cost_line stay consistent with the range tuple.
    low, high = roi_config.rejected_report_cost_range("USD")
    range_str = roi_config.cost_range_str("USD")
    if f"{low:,}" not in range_str or f"{high:,}" not in range_str:
        failures.append(f"cost_range_str('USD') {range_str!r} doesn't match rejected_report_cost_range {(low, high)}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: roi_config — GHS figures unchanged, estimated currencies disclosed with no fabricated sourcing.")


def run_checkout_routing():
    """_checkout_route_for_currency lives in app.py; imported lazily here so
    a failure to import app.py (e.g. a real missing dependency) surfaces as
    this test's own failure rather than breaking collection of the others."""
    import app

    failures = []
    expected = {
        "GHS": "paystack_native",
        "NGN": "paystack_ghs_fallback",
        "KES": "paystack_ghs_fallback",
        "ZAR": "paystack_ghs_fallback",
        "USD": "flutterwave",
        "GBP": "flutterwave",
        "EUR": "flutterwave",
    }
    for currency, want in expected.items():
        got = app._checkout_route_for_currency(currency)
        if got != want:
            failures.append(f"_checkout_route_for_currency({currency!r}) expected {want!r}, got {got!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("PASS: checkout routing — GHS native, NGN/KES/ZAR fall back to Paystack GHS charge, USD/GBP/EUR route to Flutterwave.")


if __name__ == "__main__":
    run_exchange_rates()
    run_geoip()
    run_roi_config()
    run_checkout_routing()
