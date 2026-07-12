"""
test_metrics.py — golden tests for metrics.py (log_event/read_events/summarize).

Uses a temp file for METRICS_PATH so this never touches a real event log.
No network calls. Run with: python test_metrics.py
"""

import pathlib
import tempfile

import metrics


def run():
    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        metrics.METRICS_PATH = pathlib.Path(tmp) / "events.jsonl"

        # 1. Unknown event types are silently dropped, not raised.
        metrics.log_event("not_a_real_event", "user-a@example.com")
        if metrics.read_events():
            failures.append("unknown event_type should not be written")

        # 2. session_hash never leaks the raw id.
        h = metrics.session_hash("user-a@example.com")
        if "user-a@example.com" in h or h == "":
            failures.append(f"session_hash leaked raw id or was empty: {h!r}")

        # 3. Basic event round-trips with score_band, no PII fields present.
        metrics.log_event("check_completed", "user-a@example.com", score_band="Strong")
        events = metrics.read_events()
        if len(events) != 1:
            failures.append(f"expected 1 event after first valid log_event, got {len(events)}")
        else:
            e = events[0]
            if e.get("event") != "check_completed" or e.get("score_band") != "Strong":
                failures.append(f"unexpected event record: {e!r}")
            if "session_id" in e or "email" in e or "result_statement" in e:
                failures.append(f"event record leaked a raw identifier or result text: {e!r}")
            if e.get("session") != h:
                failures.append("same raw id must hash to the same session token")

        # 4. score_uplift events carry a numeric delta.
        metrics.log_event("score_uplift", "user-a@example.com", score_uplift=1.5)
        events = metrics.read_events()
        if len(events) != 2 or events[-1].get("score_uplift") != 1.5:
            failures.append(f"score_uplift event not recorded correctly: {events}")

        # 5. summarize() totals, average uplift, and session-deduped funnel.
        metrics.log_event("demo_viewed", "user-a@example.com")
        metrics.log_event("demo_viewed", "user-b@example.com")
        metrics.log_event("check_completed", "user-b@example.com", score_band="Weak")
        metrics.log_event("payment_completed", "user-b@example.com")
        metrics.log_event("score_uplift", "user-b@example.com", score_uplift=0.5)

        summary = metrics.summarize()
        if summary["totals"].get("check_completed") != 2:
            failures.append(f"expected 2 check_completed events, got {summary['totals']}")
        if summary["totals"].get("demo_viewed") != 2:
            failures.append(f"expected 2 demo_viewed events, got {summary['totals']}")
        if summary["average_uplift"] != 1.0:  # mean of 1.5 and 0.5
            failures.append(f"expected average_uplift 1.0, got {summary['average_uplift']}")
        if summary["funnel"]["demo_viewed"] != 2:
            failures.append(f"expected funnel demo_viewed=2 (distinct sessions), got {summary['funnel']}")
        if summary["funnel"]["check_completed"] != 2:
            failures.append(f"expected funnel check_completed=2 (distinct sessions), got {summary['funnel']}")
        if summary["funnel"]["payment_completed"] != 1:
            failures.append(f"expected funnel payment_completed=1, got {summary['funnel']}")

        # 6. daily_counts() buckets by UTC calendar day and sorts oldest-first.
        import time as _time
        _day1 = _time.mktime(_time.strptime("2026-07-01", "%Y-%m-%d"))
        _day2 = _time.mktime(_time.strptime("2026-07-03", "%Y-%m-%d"))
        _fixed_events = [
            {"ts": _day1, "event": "demo_viewed", "session": "a"},
            {"ts": _day1 + 3600, "event": "check_completed", "session": "a"},
            {"ts": _day2, "event": "demo_viewed", "session": "b"},
        ]
        daily = metrics.daily_counts(_fixed_events)
        if [d["date"] for d in daily] != sorted(d["date"] for d in daily):
            failures.append(f"daily_counts() must be sorted oldest-first, got {daily}")
        _by_date = {d["date"]: d["count"] for d in daily}
        if len(daily) != 2 or list(_by_date.values()) != [2, 1]:
            failures.append(f"expected 2 days with counts [2, 1], got {daily}")
        if metrics.daily_counts([]) != []:
            failures.append("daily_counts([]) should return []")

        # 7. read_events()/summarize() on a missing file return empty, not raise.
        metrics.METRICS_PATH = pathlib.Path(tmp) / "does_not_exist.jsonl"
        if metrics.read_events() != []:
            failures.append("read_events() on a missing file should return []")
        empty_summary = metrics.summarize()
        if empty_summary["totals"] != {} or empty_summary["average_uplift"] != 0.0:
            failures.append(f"summarize() on no events should be all-zero, got {empty_summary}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)

    print("PASS: metrics — event logging, anonymization, and summary rollups verified.")


if __name__ == "__main__":
    run()
