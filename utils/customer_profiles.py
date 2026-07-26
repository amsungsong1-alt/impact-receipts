"""
utils/customer_profiles.py — Laudon Ch.9 CRM, C1: read-only access to the
customer_profiles materialized table.

This module NEVER assembles/recomputes a profile itself -- the single
CustomerProfile assembly path is the refresh_customer_profiles() SQL function
(supabase/migrations/0024_customer_profiles.sql), invoked hourly by the
customer-profile-refresh Edge Function. Python only ever SELECTs the
already-materialized result. Same SUPABASE_DB_URL/SQLAlchemy engine pattern
as utils/crm.py and utils/audits.py; degrades gracefully (None/[]) on any DB
failure, never raises.
"""
from __future__ import annotations
import os

from sqlalchemy import Column, BigInteger, Integer, Boolean, Text, DateTime, func
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()

_PK = BigInteger().with_variant(Integer, "sqlite")


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    email = Column(Text, primary_key=True)
    plan = Column(Text)
    subscription_status = Column(Text)
    signup_at = Column(DateTime(timezone=True))
    last_active_at = Column(DateTime(timezone=True))
    total_assessments = Column(Integer, default=0)
    assessments_last_30d = Column(Integer, default=0)
    revision_count_last_30d = Column(Integer, default=0)
    lifetime_payment_count = Column(Integer, default=0)
    lifetime_revenue_pesewas = Column(_PK, default=0)
    last_payment_status = Column(Text)
    last_payment_at = Column(DateTime(timezone=True))
    wa_conversation_count = Column(Integer, default=0)
    last_wa_at = Column(DateTime(timezone=True))
    email_domain = Column(Text)
    domain_user_count = Column(Integer, default=1)
    distinct_donor_count_30d = Column(Integer, default=0)
    active_in_equivalent_window_last_cycle = Column(Boolean, default=False)
    computed_at = Column(DateTime(timezone=True))


_engine = None


def _get_engine():
    # Identical pattern to utils.crm._get_engine()/utils.audits._get_engine().
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


def _row_to_dict(row: CustomerProfile) -> dict:
    return {
        "email": row.email,
        "plan": row.plan,
        "subscription_status": row.subscription_status,
        "signup_at": row.signup_at,
        "last_active_at": row.last_active_at,
        "total_assessments": row.total_assessments or 0,
        "assessments_last_30d": row.assessments_last_30d or 0,
        "revision_count_last_30d": row.revision_count_last_30d or 0,
        "lifetime_payment_count": row.lifetime_payment_count or 0,
        "lifetime_revenue_pesewas": row.lifetime_revenue_pesewas or 0,
        "last_payment_status": row.last_payment_status,
        "last_payment_at": row.last_payment_at,
        "wa_conversation_count": row.wa_conversation_count or 0,
        "last_wa_at": row.last_wa_at,
        "email_domain": row.email_domain,
        "domain_user_count": row.domain_user_count or 1,
        "distinct_donor_count_30d": row.distinct_donor_count_30d or 0,
        "active_in_equivalent_window_last_cycle": bool(row.active_in_equivalent_window_last_cycle),
        "computed_at": row.computed_at,
    }


def get_customer_profile(email: str) -> dict | None:
    """Reads one account's materialized profile. Returns None if the
    account has never been through a refresh_customer_profiles() run yet,
    if email is falsy, or on any DB failure -- never raises."""
    if not email:
        return None
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            row = session.get(CustomerProfile, email)
            return _row_to_dict(row) if row else None
    except Exception:
        return None


def list_customer_profiles() -> list[dict]:
    """Reads every materialized profile -- the basis for
    utils.crm.build_behavioral_segments(). Returns [] on any DB failure."""
    engine = _get_engine()
    if not engine:
        return []
    try:
        with Session(engine) as session:
            rows = session.query(CustomerProfile).all()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []
