"""
utils/api_pricing.py — Laudon Ch.9 CRM, C4: real per-assessment Anthropic API
cost, feeding CLTV's gross-margin calculation.

Before this module, no call site anywhere in this codebase read `.usage` off
an Anthropic API response (confirmed by grep across all 5 call sites during
the Ch.9 Phase 1 audit) -- CLTV had no real cost floor to net against. This
module gives every call site a single, shared way to log usage
(log_api_usage()) and compute cost (compute_cost_pesewas()), reading pricing
from knowledge/model_pricing.yaml -- hot-reloadable, same convention as
knowledge/mel_calendar.yaml/knowledge/taxonomy.yaml, and explicitly a labeled
placeholder assumption (see that file's own comment), not a verified current
price list.

Degrades gracefully everywhere -- a pricing/logging failure must never break
the AI call it's measuring.
"""
from __future__ import annotations
import os

import yaml
from sqlalchemy import Column, BigInteger, Integer, Text, Float, DateTime, func
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()
_PK = BigInteger().with_variant(Integer, "sqlite")

_PRICING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "model_pricing.yaml"
)

# The two call sites that actually gate a scored assessment -- used by
# compute_average_cost_per_assessment() to exclude call sites (chat,
# logframe match) that don't correspond 1:1 with an assessment.
ASSESSMENT_CALL_SITES = {"irc_extraction", "batch_extraction"}


class ApiUsageLog(Base):
    __tablename__ = "api_usage_log"
    id = Column(_PK, primary_key=True)
    email = Column(Text)
    model = Column(Text, nullable=False)
    call_site = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_pesewas = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


_engine = None


def _get_engine():
    # Identical pattern to utils.crm._get_engine()/utils.customer_profiles._get_engine().
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


def load_model_pricing() -> dict:
    """Re-reads knowledge/model_pricing.yaml fresh on every call --
    hot-reloadable, same convention as utils/mel_calendar.py. Returns {} if
    the file is missing or malformed rather than raising."""
    if not os.path.isfile(_PRICING_PATH):
        return {}
    try:
        with open(_PRICING_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def compute_cost_pesewas(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated GHS-pesewas cost for one API call. Returns 0.0 (never
    raises) if the model isn't in the pricing file or the file can't load --
    a missing rate should never crash the call it's measuring."""
    pricing = load_model_pricing()
    rates = pricing.get("models", {}).get(model)
    usd_to_ghs = pricing.get("usd_to_ghs_rate")
    if not rates or not usd_to_ghs:
        return 0.0
    try:
        input_usd = (input_tokens / 1_000_000) * rates.get("input_per_million_tokens_usd", 0)
        output_usd = (output_tokens / 1_000_000) * rates.get("output_per_million_tokens_usd", 0)
        return round((input_usd + output_usd) * usd_to_ghs * 100, 4)  # GHS -> pesewas
    except (TypeError, ValueError):
        return 0.0


def log_api_usage(email: str, model: str, call_site: str, input_tokens: int, output_tokens: int) -> None:
    """Best-effort, insert-only -- never raises. A logging failure must not
    block the AI feature it's measuring (same contract as utils.crm.log_event)."""
    engine = _get_engine()
    if not engine:
        return
    try:
        cost = compute_cost_pesewas(model, input_tokens or 0, output_tokens or 0)
        with Session(engine) as session:
            session.add(ApiUsageLog(
                email=email or None, model=model, call_site=call_site,
                input_tokens=input_tokens or 0, output_tokens=output_tokens or 0,
                estimated_cost_pesewas=cost,
            ))
            session.commit()
    except Exception:
        pass


def _assessment_costs(email: str | None = None) -> list[float] | None:
    """Shared query behind compute_average_cost_per_assessment()/
    compute_p95_cost_per_assessment() -- every ASSESSMENT_CALL_SITES row's
    estimated_cost_pesewas, optionally scoped to one account. Returns None
    (not []) on any DB failure so callers can distinguish "no engine/error"
    from "engine reachable, genuinely zero rows yet.\""""
    engine = _get_engine()
    if not engine:
        return None
    try:
        with Session(engine) as session:
            q = session.query(ApiUsageLog.estimated_cost_pesewas).filter(
                ApiUsageLog.call_site.in_(ASSESSMENT_CALL_SITES)
            )
            if email:
                q = q.filter(ApiUsageLog.email == email)
            return [c[0] for c in q.all()]
    except Exception:
        return None


def compute_average_cost_per_assessment(email: str | None = None) -> float | None:
    """Average estimated_cost_pesewas across api_usage_log rows tagged to a
    call site that actually gates a scored assessment (ASSESSMENT_CALL_SITES) --
    the real (not assumed) per-assessment API cost floor CLTV nets against.
    Optionally scoped to one account. Returns None if there's no matching
    data yet or on any DB failure -- CLTV must treat "no data" differently
    from "zero cost.\""""
    costs = _assessment_costs(email)
    if not costs:
        return None
    return round(sum(costs) / len(costs), 4)


def compute_p95_cost_per_assessment(email: str | None = None) -> float | None:
    """Laudon Ch.10, C1: the 95th-percentile estimated_cost_pesewas across
    ASSESSMENT_CALL_SITES rows -- a mean alone hides the expensive tail
    (long documents, retried extractions) that determines whether a heavy
    subscriber is actually margin-negative. Nearest-rank method (no numpy
    dependency needed for this). Returns None on no data/DB failure, same
    contract as compute_average_cost_per_assessment()."""
    costs = _assessment_costs(email)
    if not costs:
        return None
    ordered = sorted(costs)
    # Nearest-rank percentile: round(p * (n-1)), clamped into range -- exact
    # for n=1 (returns the only value) and matches numpy's default
    # interpolation closely enough for a cost-estimate use case.
    idx = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
    return round(ordered[idx], 4)


# Tertile boundaries (by input_tokens, a document-length proxy already
# stored on every row -- no new field needed) for bucketing cost by
# document length. Documented, not researched -- revisit once there's
# enough real-usage volume to derive these from an actual distribution
# instead of a plausible guess.
_DOC_LENGTH_SHORT_MAX_TOKENS = 2000
_DOC_LENGTH_MEDIUM_MAX_TOKENS = 8000


def compute_cost_by_document_length_bucket(email: str | None = None) -> dict:
    """Laudon Ch.10, C1: mean estimated_cost_pesewas grouped into short/
    medium/long buckets by input_tokens (a document-length proxy already
    logged at every ASSESSMENT_CALL_SITES call, so this needs no new
    column). Returns {"short": {"mean_cost_pesewas", "count"}, "medium": ...,
    "long": ...} -- a bucket with zero rows still appears with count 0 and a
    None mean, never silently omitted. Returns {} on no engine/DB failure."""
    engine = _get_engine()
    if not engine:
        return {}
    try:
        with Session(engine) as session:
            q = session.query(ApiUsageLog.input_tokens, ApiUsageLog.estimated_cost_pesewas).filter(
                ApiUsageLog.call_site.in_(ASSESSMENT_CALL_SITES)
            )
            if email:
                q = q.filter(ApiUsageLog.email == email)
            rows = q.all()
    except Exception:
        return {}

    buckets = {"short": [], "medium": [], "long": []}
    for input_tokens, cost in rows:
        tokens = input_tokens or 0
        if tokens <= _DOC_LENGTH_SHORT_MAX_TOKENS:
            buckets["short"].append(cost)
        elif tokens <= _DOC_LENGTH_MEDIUM_MAX_TOKENS:
            buckets["medium"].append(cost)
        else:
            buckets["long"].append(cost)

    return {
        name: {
            "mean_cost_pesewas": round(sum(costs) / len(costs), 4) if costs else None,
            "count": len(costs),
        }
        for name, costs in buckets.items()
    }


def compute_subscription_breakeven_assessments(
    monthly_price_pesewas: int, cost_per_assessment_pesewas: float | None = None
) -> float | None:
    """Laudon Ch.10, C1: the number of assessments per month at which a
    subscriber paying monthly_price_pesewas stops being margin-positive --
    breakeven_n = monthly_price_pesewas / cost_per_assessment_pesewas. A
    subscriber running MORE than this many assessments in a month is
    margin-negative for that month.

    Defaults cost_per_assessment_pesewas to compute_average_cost_per_assessment()
    (all accounts, not subscriber-only -- see docs/unit_economics.md's
    explicit TODO on this scoping gap) when not supplied. Returns None if no
    cost figure is available (no data yet, or the caller passed 0/None with
    nothing to fall back to) rather than a divide-by-zero or a guessed
    number."""
    if cost_per_assessment_pesewas is None:
        cost_per_assessment_pesewas = compute_average_cost_per_assessment()
    if not cost_per_assessment_pesewas or cost_per_assessment_pesewas <= 0:
        return None
    return round(monthly_price_pesewas / cost_per_assessment_pesewas, 2)
