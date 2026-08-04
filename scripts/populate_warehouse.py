"""
scripts/populate_warehouse.py

Laudon Ch.6 Phase 2, C4: ETL from the OLTP-shaped assessments/criterion_scores
tables (migrations 0030-0037) into the star-schema warehouse (dim_donor/
dim_sector/dim_org_type/dim_date/fact_assessment, migration 0055).

Unlike scripts/quality_audit.py and scripts/generate_data_dictionary.py, this
script does plain SQLAlchemy reads/inserts, not information_schema
introspection -- so it can and does run against the in-memory SQLite fixture
in test_populate_warehouse.py, the same convention utils/assessment_facts.py
uses, even though production use is Postgres via SUPABASE_DB_URL.

Idempotent and incremental: only assessments not already present in
fact_assessment are loaded on each run (dimension rows are get-or-create,
fact rows are insert-only) -- safe to run repeatedly, e.g. on a schedule,
without duplicating facts.

Run:
    python scripts/populate_warehouse.py

Requires SUPABASE_DB_URL pointed at a real Postgres database with 0030-0037
and 0055 already applied. Point it at a disposable branch database, never
production, until this script has been reviewed against real data.
"""
from __future__ import annotations
import os
import sys
from datetime import date, datetime

from sqlalchemy import (
    Column, BigInteger, Integer, Text, Date, Numeric, DateTime, ForeignKey,
    func, select, text,
)
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()

# Same SQLite/rowid-alias autoincrement compat trick as utils/audits.py's _PK.
_PK = BigInteger().with_variant(Integer, "sqlite")


class DimDonor(Base):
    __tablename__ = "dim_donor"
    id = Column(_PK, primary_key=True)
    donor = Column(Text, nullable=False, unique=True)


class DimSector(Base):
    __tablename__ = "dim_sector"
    id = Column(_PK, primary_key=True)
    sector = Column(Text, nullable=False, unique=True)


class DimOrgType(Base):
    __tablename__ = "dim_org_type"
    id = Column(_PK, primary_key=True)
    org_type = Column(Text, nullable=False, unique=True)


class DimDate(Base):
    __tablename__ = "dim_date"
    date_key = Column(Date, primary_key=True)
    year = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    month_name = Column(Text, nullable=False)


class FactAssessment(Base):
    __tablename__ = "fact_assessment"
    id = Column(_PK, primary_key=True)
    assessment_id = Column(BigInteger, nullable=False, unique=True)
    donor_id = Column(BigInteger, ForeignKey("dim_donor.id"))
    sector_id = Column(BigInteger, ForeignKey("dim_sector.id"))
    org_type_id = Column(BigInteger, ForeignKey("dim_org_type.id"))
    date_key = Column(Date, ForeignKey("dim_date.date_key"))
    confidence_score = Column(Numeric)
    clarity_score = Column(Numeric)
    verdict = Column(Text)
    criteria_passed_count = Column(Integer)
    criteria_failed_count = Column(Integer)
    loaded_at = Column(DateTime(timezone=True), server_default=func.now())


_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# A criterion "passes" at >=70% of its own max value (evaluator.DIMENSION_MAP's
# third tuple element) -- a documented threshold for this warehouse-only
# pass/fail count. The real scored value is untouched and stays in
# criterion_scores.score; this is a derived aggregate, not a replacement.
_PASS_THRESHOLD_FRACTION = 0.7


def _get_engine():
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        print("SUPABASE_DB_URL is not set -- point it at a disposable branch database, "
              "never production.", file=sys.stderr)
        sys.exit(1)
    from sqlalchemy import create_engine
    return create_engine(db_url, pool_pre_ping=True)


def _get_or_create(session: Session, model, unique_field: str, value):
    """Look up a dimension row by its unique text value, creating it if
    absent. Returns None (never a guessed/default row) when value is empty."""
    if not value:
        return None
    existing = session.execute(
        select(model).where(getattr(model, unique_field) == value)
    ).scalar_one_or_none()
    if existing:
        return existing.id
    row = model(**{unique_field: value})
    session.add(row)
    session.flush()
    return row.id


def _coerce_date(value):
    """Normalizes a created_at value read back via a raw text() query to a
    plain date. Postgres's driver returns a native datetime for a
    timestamptz column; SQLite (used only in tests) returns a string via the
    raw-SQL path -- both are handled here rather than assuming one shape.
    Returns None for anything unparseable, never guesses."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _get_or_create_date(session: Session, d: date):
    if not d:
        return None
    existing = session.get(DimDate, d)
    if existing:
        return d
    session.add(DimDate(
        date_key=d, year=d.year, quarter=(d.month - 1) // 3 + 1,
        month=d.month, month_name=_MONTH_NAMES[d.month],
    ))
    session.flush()
    return d


def _count_passed_failed(criterion_rows, dimension_map: dict) -> tuple:
    """criterion_rows: iterable of (criterion, score) pairs. Skips any
    criterion whose max value or score isn't known rather than guessing a
    pass/fail verdict for it."""
    passed, failed = 0, 0
    for criterion, score in criterion_rows:
        entry = dimension_map.get(criterion)
        if entry is None or score is None:
            continue
        max_val = entry[2]
        if float(score) >= _PASS_THRESHOLD_FRACTION * max_val:
            passed += 1
        else:
            failed += 1
    return passed, failed


def populate(engine) -> int:
    """Loads every assessment not yet present in fact_assessment. Returns the
    count of new fact rows written. Never raises on a missing/None field --
    the corresponding dimension FK is simply left null."""
    from evaluator import DIMENSION_MAP

    loaded = 0
    with Session(engine) as session:
        already_loaded = set(
            session.execute(select(FactAssessment.assessment_id)).scalars().all()
        )
        rows = session.execute(text(
            "select id, donor, sector, org_type, confidence_score, clarity_score, "
            "verdict, created_at from assessments"
        )).all()
        for (assessment_id, donor, sector, org_type, confidence_score,
             clarity_score, verdict, created_at) in rows:
            if assessment_id in already_loaded:
                continue

            criterion_rows = session.execute(text(
                "select criterion, score from criterion_scores where assessment_id = :aid"
            ), {"aid": assessment_id}).all()
            passed, failed = _count_passed_failed(criterion_rows, DIMENSION_MAP)

            donor_id = _get_or_create(session, DimDonor, "donor", donor)
            sector_id = _get_or_create(session, DimSector, "sector", sector)
            org_type_id = _get_or_create(session, DimOrgType, "org_type", org_type)
            date_key = _get_or_create_date(session, _coerce_date(created_at))

            session.add(FactAssessment(
                assessment_id=assessment_id, donor_id=donor_id, sector_id=sector_id,
                org_type_id=org_type_id, date_key=date_key,
                confidence_score=confidence_score, clarity_score=clarity_score,
                verdict=verdict, criteria_passed_count=passed, criteria_failed_count=failed,
            ))
            loaded += 1
        session.commit()
    return loaded


def main() -> int:
    engine = _get_engine()
    count = populate(engine)
    print(f"Warehouse populate complete: {count} new fact_assessment row(s) loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
