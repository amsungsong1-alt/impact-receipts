"""
utils/warehouse.py — Laudon Ch.6 Phase 2, C5: read-only OLAP slice/dice
queries over the star-schema warehouse (dim_donor/dim_sector/dim_org_type/
dim_date/fact_assessment, migration 0055, populated by
scripts/populate_warehouse.py).

Same graceful-degradation contract as utils/audits.py: no SUPABASE_DB_URL,
no engine, a DB error, or a bucket below MIN_SLICE_SAMPLE all return an
empty list rather than raising or showing a misleading near-empty slice.
Read-only -- this module never writes to any warehouse table; that's
scripts/populate_warehouse.py's job alone.
"""
from __future__ import annotations
import os

MIN_SLICE_SAMPLE = 10  # matches utils.audits.MIN_BENCHMARK_SAMPLE's rationale

_engine = None

_DIMENSION_QUERIES = {
    "donor": """
        select d.donor as label, count(*) as n,
               avg(f.confidence_score) as avg_confidence, avg(f.clarity_score) as avg_clarity,
               avg(case when f.criteria_passed_count + f.criteria_failed_count > 0
                        then 1.0 * f.criteria_passed_count / (f.criteria_passed_count + f.criteria_failed_count)
                        else null end) as pass_rate
        from fact_assessment f join dim_donor d on f.donor_id = d.id
        group by d.donor having count(*) >= :min_sample
        order by n desc
    """,
    "sector": """
        select s.sector as label, count(*) as n,
               avg(f.confidence_score) as avg_confidence, avg(f.clarity_score) as avg_clarity,
               avg(case when f.criteria_passed_count + f.criteria_failed_count > 0
                        then 1.0 * f.criteria_passed_count / (f.criteria_passed_count + f.criteria_failed_count)
                        else null end) as pass_rate
        from fact_assessment f join dim_sector s on f.sector_id = s.id
        group by s.sector having count(*) >= :min_sample
        order by n desc
    """,
    "org_type": """
        select o.org_type as label, count(*) as n,
               avg(f.confidence_score) as avg_confidence, avg(f.clarity_score) as avg_clarity,
               avg(case when f.criteria_passed_count + f.criteria_failed_count > 0
                        then 1.0 * f.criteria_passed_count / (f.criteria_passed_count + f.criteria_failed_count)
                        else null end) as pass_rate
        from fact_assessment f join dim_org_type o on f.org_type_id = o.id
        group by o.org_type having count(*) >= :min_sample
        order by n desc
    """,
    "quarter": """
        select d.year || ' Q' || d.quarter as label, count(*) as n,
               avg(f.confidence_score) as avg_confidence, avg(f.clarity_score) as avg_clarity,
               avg(case when f.criteria_passed_count + f.criteria_failed_count > 0
                        then 1.0 * f.criteria_passed_count / (f.criteria_passed_count + f.criteria_failed_count)
                        else null end) as pass_rate
        from fact_assessment f join dim_date d on f.date_key = d.date_key
        group by d.year, d.quarter having count(*) >= :min_sample
        order by d.year, d.quarter
    """,
}


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


def slice_by(dimension: str, engine=None) -> list:
    """Returns [{"label", "n", "avg_confidence", "avg_clarity", "pass_rate"}, ...]
    for the given dimension ("donor" | "sector" | "org_type" | "quarter"),
    buckets with fewer than MIN_SLICE_SAMPLE assessments excluded. Empty list
    on an unknown dimension, no engine, no warehouse tables yet, or any DB
    error -- never raises."""
    query = _DIMENSION_QUERIES.get(dimension)
    if not query:
        return []
    engine = engine or _get_engine()
    if not engine:
        return []
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(text(query), {"min_sample": MIN_SLICE_SAMPLE}).mappings().all()
        return [
            {
                "label": r["label"],
                "n": r["n"],
                "avg_confidence": round(float(r["avg_confidence"]), 2) if r["avg_confidence"] is not None else None,
                "avg_clarity": round(float(r["avg_clarity"]), 2) if r["avg_clarity"] is not None else None,
                "pass_rate": round(float(r["pass_rate"]), 2) if r["pass_rate"] is not None else None,
            }
            for r in rows
        ]
    except Exception:
        return []
