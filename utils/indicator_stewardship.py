"""
utils/indicator_stewardship.py — Laudon Ch.6 Phase 2, C7 (indicator
stewardship register only; the "draft information policy generator" half of
C7 is deliberately deferred to its own scoping pass -- see
project_laudon_prompt_pack_roadmap memory for why: a customer-facing
document generator needs a dedicated no-fabrication design, not a rushed
add-on here).

Surfaces indicators (migration 0035's `indicators` table, part of Phase 1's
0030-0037) that this account has used across multiple assessments with
inconsistent target/baseline values -- a real data-governance signal: two
submissions calling something "% of households with improved water access"
but recording different targets either means the indicator's definition
drifted over time, or two genuinely different things are being tracked
under one name. Flag-only, same flag-never-correct contract as
evaluator.check_data_quality_flags() -- this never decides which value is
"correct," only surfaces the inconsistency for a human to resolve.

Scoped to the caller's OWN account (via assessments.user_hash, same
metrics.session_hash() pattern as utils/assessment_links.py) rather than a
global cross-account view -- indicator names are free text an org chooses
for itself, so mixing different accounts' definitions of a similarly-named
indicator together would be noisy and not actually actionable for anyone.
"""
from __future__ import annotations
import os

MIN_USES_TO_FLAG = 2  # an indicator used only once has nothing to be inconsistent with

_engine = None


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    try:
        import streamlit as st
        db_url = st.secrets.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL", "")
    except Exception:
        db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        _engine = create_engine(db_url, pool_pre_ping=True)
    except Exception:
        _engine = None
    return _engine


def find_indicator_inconsistencies(email: str, engine=None) -> list:
    """Returns [{"indicator_name", "use_count", "distinct_targets",
    "distinct_baselines"}, ...] for this account's own indicator names used
    MIN_USES_TO_FLAG+ times where the recorded target and/or baseline values
    aren't all identical (case/whitespace-insensitive match on the name
    itself). Never raises; returns [] for an empty email, no engine, a
    missing table, or any DB error."""
    if not email:
        return []
    engine = engine or _get_engine()
    if not engine:
        return []
    try:
        from sqlalchemy import text
        from metrics import session_hash
        with engine.connect() as conn:
            rows = conn.execute(text("""
                select i.indicator_name, i.logframe_target, i.logframe_baseline
                from indicators i
                join assessments a on a.id = i.assessment_id
                where a.user_hash = :user_hash
                  and i.indicator_name is not null and trim(i.indicator_name) != ''
            """), {"user_hash": session_hash(email)}).all()
    except Exception:
        return []

    by_name: dict = {}
    for name, target, baseline in rows:
        key = name.strip().lower()
        entry = by_name.setdefault(
            key, {"indicator_name": name.strip(), "targets": set(), "baselines": set(), "use_count": 0}
        )
        entry["use_count"] += 1
        if target and target.strip():
            entry["targets"].add(target.strip())
        if baseline and baseline.strip():
            entry["baselines"].add(baseline.strip())

    findings = []
    for entry in by_name.values():
        if entry["use_count"] < MIN_USES_TO_FLAG:
            continue
        if len(entry["targets"]) > 1 or len(entry["baselines"]) > 1:
            findings.append({
                "indicator_name": entry["indicator_name"],
                "use_count": entry["use_count"],
                "distinct_targets": sorted(entry["targets"]),
                "distinct_baselines": sorted(entry["baselines"]),
            })
    findings.sort(key=lambda f: f["use_count"], reverse=True)
    return findings
