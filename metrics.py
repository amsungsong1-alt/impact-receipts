"""
metrics.py — privacy-safe usage instrumentation.

Append-only JSON-lines event log. NO PII and NO result/document text is ever
logged — only an event type, a one-way anonymous session hash, a timestamp,
and (for score_uplift events) a numeric score delta.

Storage is a local file today. log_event()/read_events() are the only call
sites the rest of the app should use, so swapping the backend to Supabase
later means changing this module only — not any caller.

Caveat: on Streamlit Community Cloud the filesystem is ephemeral and does
not survive a redeploy/restart, so this file-backed store is a starting
point for local development and short-lived demos, not a durable record —
swap to Supabase (see module docstring above) before relying on it for
real pitch-day numbers collected over multiple deploys.
"""

import hashlib
import json
import os
import pathlib
import time

METRICS_PATH = pathlib.Path(os.environ.get("IMPACTPROOF_METRICS_PATH", "metrics_events.jsonl"))

EVENT_TYPES = {
    "demo_viewed",
    "check_completed",
    "ai_questions_generated",
    "draft_withheld_fabrication",
    "payment_initiated",
    "payment_completed",
    "score_uplift",
}


def session_hash(raw_id: str) -> str:
    """One-way anonymous session identifier — the raw id (email or a random
    per-session uuid) is never itself written to the log."""
    return hashlib.sha256((raw_id or "").encode("utf-8")).hexdigest()[:16]


def log_event(event_type: str, session_id: str, score_band: str = "",
              score_uplift: float | None = None) -> None:
    """Append one event. Never raises — a metrics failure must not break the
    product, the same graceful-degradation contract as the AI features."""
    if event_type not in EVENT_TYPES:
        return
    record = {
        "ts":      time.time(),
        "session": session_hash(session_id),
        "event":   event_type,
    }
    if score_band:
        record["score_band"] = score_band
    if score_uplift is not None:
        record["score_uplift"] = score_uplift
    try:
        with open(METRICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def read_events() -> list[dict]:
    """Read all logged events. Returns [] if the file doesn't exist yet or
    can't be read — never raises."""
    if not METRICS_PATH.exists():
        return []
    events = []
    try:
        with open(METRICS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return events


def summarize(events: list[dict] | None = None) -> dict:
    """Compute the admin-view rollups: totals per event type, average
    score_uplift, and a demo -> check -> payment conversion funnel (counted
    by distinct session, not raw event count)."""
    if events is None:
        events = read_events()

    totals: dict[str, int] = {}
    uplifts: list[float] = []
    demo_sessions:    set[str] = set()
    check_sessions:   set[str] = set()
    payment_sessions: set[str] = set()

    for e in events:
        et = e.get("event", "")
        totals[et] = totals.get(et, 0) + 1
        sess = e.get("session", "")
        if et == "score_uplift" and isinstance(e.get("score_uplift"), (int, float)):
            uplifts.append(e["score_uplift"])
        elif et == "demo_viewed" and sess:
            demo_sessions.add(sess)
        elif et == "check_completed" and sess:
            check_sessions.add(sess)
        elif et == "payment_completed" and sess:
            payment_sessions.add(sess)

    return {
        "totals":         totals,
        "average_uplift": round(sum(uplifts) / len(uplifts), 2) if uplifts else 0.0,
        "funnel": {
            "demo_viewed":       len(demo_sessions),
            "check_completed":   len(check_sessions),
            "payment_completed": len(payment_sessions),
        },
    }


def daily_counts(events: list[dict] | None = None) -> list[dict]:
    """Total event volume per UTC calendar day, sorted oldest-first — the
    input to a growth-over-time trend chart. Returns [{"date": "YYYY-MM-DD",
    "count": int}, ...], one row per day that has at least one event (no
    zero-filled gaps — the caller can reindex if it needs a continuous axis)."""
    if events is None:
        events = read_events()

    counts: dict[str, int] = {}
    for e in events:
        ts = e.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        counts[day] = counts.get(day, 0) + 1

    return [{"date": d, "count": c} for d, c in sorted(counts.items())]
