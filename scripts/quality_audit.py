"""
scripts/quality_audit.py

Laudon Ch.6, C3 (operationalising Ch.12's seven data-quality dimensions):
runs a structured survey of ImpactProof's own data and writes every finding
to the quality_audits table (migration 0037).

Five of the seven dimensions are implemented here — completeness,
consistency, uniqueness, validity, timeliness. The remaining two,
**accuracy** and **accessibility**, are documented as not automatable given
what ImpactProof has today (accuracy needs ground truth to compare against;
accessibility needs an end-user perception survey) — this script says so
explicitly rather than silently pretending 5-of-7 is 7-of-7.

Run:
    python scripts/quality_audit.py

Requires SUPABASE_DB_URL pointed at a real Postgres database (this cannot
run against the in-memory SQLite fixtures the rest of this codebase's test
suite uses — information_schema's FK/constraint introspection is Postgres-
specific). Point it at a disposable branch database, never production,
until this script has been reviewed against real data at least once.

Scheduling this on a recurring cadence (pg_cron, same pattern as
customer-profile-refresh) is a natural next step, not built in this pass —
this script is runnable manually today, which is Phase 1's actual ask.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timedelta, timezone

# (table, column) pairs that should be unique but predate a UNIQUE
# constraint on some rows, or are worth double-checking regardless.
_UNIQUENESS_CHECKS = [
    ("payments", "paystack_reference"),
    ("audits", "ref_id"),
    ("export_verifications", "ref_id"),
]

# (table, column, allowed_values) for text columns whose valid-value set
# exists only as a Python-side allowlist today (no DB CHECK/enum) --
# mirrors utils/crm.py::ALLOWED_EVENT_TYPES etc. Kept here, not imported
# from the app, so this script has zero dependency on Streamlit/app.py
# being importable in whatever environment it runs in.
_ENUM_CHECKS = [
    ("payments", "status", {"success", "failed"}),
    ("payments", "source", {"redirect_verify", "webhook"}),
    ("crm_events", "event_type", {
        "signup", "audit_run", "framework_used", "tier_change",
        "upgrade_prompt_shown", "upgrade_prompt_clicked", "whatsapp_click", "revision_run",
    }),
]

# (table, column, min, max) for numeric columns with a known semantic range
# but no DB CHECK constraint (predate migration 0031's CHECK convention).
_RANGE_CHECKS = [
    ("audits", "primary_confidence_score", 0, 5),
    ("audits", "primary_clarity_score", 0, 5),
    ("users", "free_checks_used", 0, None),
]

# (table, timestamp_column, max_age_hours, context) for staleness checks.
_STALENESS_CHECKS = [
    ("customer_profiles", "computed_at", 25, "should refresh hourly via customer-profile-refresh"),
]

# Only write a completeness finding when a column's null rate exceeds this
# fraction -- otherwise every nullable column in the schema would produce
# noise, defeating "runs clean, or every finding has a ticket."
_COMPLETENESS_THRESHOLD = 0.05


class Finding:
    def __init__(self, dimension: str, table_name: str, column_name: str | None,
                 finding: str, severity: str, sample_count: int | None = None):
        self.dimension = dimension
        self.table_name = table_name
        self.column_name = column_name
        self.finding = finding
        self.severity = severity
        self.sample_count = sample_count

    def __repr__(self):
        col = f".{self.column_name}" if self.column_name else ""
        return f"[{self.severity.upper()}] {self.dimension}: {self.table_name}{col} — {self.finding}"


def _get_engine():
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        print("SUPABASE_DB_URL is not set -- point it at a disposable branch database, "
              "never production.", file=sys.stderr)
        sys.exit(1)
    from sqlalchemy import create_engine
    return create_engine(db_url, pool_pre_ping=True)


def check_completeness(engine) -> list[Finding]:
    """Null rate per column, across every table -- only a finding when the
    rate exceeds _COMPLETENESS_THRESHOLD, so a clean run stays clean."""
    from sqlalchemy import text
    findings = []
    with engine.connect() as conn:
        tables = conn.execute(text(
            "select table_name from information_schema.tables where table_schema='public' "
            "and table_type='BASE TABLE'"
        )).scalars().all()
        for table in tables:
            columns = conn.execute(text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name=:t"
            ), {"t": table}).scalars().all()
            total = conn.execute(text(f'select count(*) from "{table}"')).scalar()
            if not total:
                continue
            for col in columns:
                nulls = conn.execute(text(
                    f'select count(*) from "{table}" where "{col}" is null'
                )).scalar()
                rate = nulls / total
                if rate > _COMPLETENESS_THRESHOLD:
                    severity = "critical" if rate >= 0.5 else "warning"
                    findings.append(Finding(
                        "completeness", table, col,
                        f"{nulls}/{total} rows ({rate:.0%}) are null",
                        severity, sample_count=nulls,
                    ))
    return findings


def check_consistency(engine) -> list[Finding]:
    """Orphaned foreign keys -- discovers every declared FK via
    information_schema (not a hardcoded list, so this stays accurate as the
    schema evolves) and counts child rows whose FK value has no matching
    parent. A real FK constraint prevents NEW orphans; this catches rows
    that predate the constraint or were inserted by a superuser bypassing
    it."""
    from sqlalchemy import text
    findings = []
    with engine.connect() as conn:
        fks = conn.execute(text("""
            select
                tc.table_name as child_table, kcu.column_name as child_column,
                ccu.table_name as parent_table, ccu.column_name as parent_column
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
                on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
            join information_schema.constraint_column_usage ccu
                on tc.constraint_name = ccu.constraint_name and tc.table_schema = ccu.table_schema
            where tc.constraint_type = 'FOREIGN KEY' and tc.table_schema = 'public'
        """)).all()
        for child_table, child_column, parent_table, parent_column in fks:
            orphans = conn.execute(text(f"""
                select count(*) from "{child_table}" c
                where c."{child_column}" is not null
                and not exists (
                    select 1 from "{parent_table}" p where p."{parent_column}" = c."{child_column}"
                )
            """)).scalar()
            if orphans:
                findings.append(Finding(
                    "consistency", child_table, child_column,
                    f"{orphans} row(s) reference a non-existent {parent_table}.{parent_column}",
                    "critical", sample_count=orphans,
                ))
    return findings


def check_uniqueness(engine) -> list[Finding]:
    """Duplicate values in columns that should be unique -- _UNIQUENESS_CHECKS
    covers both DB-enforced-going-forward columns (auditing historical data
    from before the constraint existed) and business keys with no DB
    constraint at all."""
    from sqlalchemy import text
    findings = []
    with engine.connect() as conn:
        for table, column in _UNIQUENESS_CHECKS:
            dupes = conn.execute(text(f"""
                select count(*) from (
                    select "{column}" from "{table}"
                    where "{column}" is not null
                    group by "{column}" having count(*) > 1
                ) d
            """)).scalar()
            if dupes:
                findings.append(Finding(
                    "uniqueness", table, column,
                    f"{dupes} distinct value(s) of {column} appear more than once",
                    "critical", sample_count=dupes,
                ))
    return findings


def check_validity(engine) -> list[Finding]:
    """Out-of-range numeric values and out-of-allowlist enum values, for
    columns not covered by a DB CHECK constraint (a real CHECK already
    prevents new violations; this audits historical/pre-constraint data and
    the columns migration 0031 onward hasn't touched)."""
    from sqlalchemy import text
    findings = []
    with engine.connect() as conn:
        for table, column, low, high in _RANGE_CHECKS:
            conditions = []
            if low is not None:
                conditions.append(f'"{column}" < {low}')
            if high is not None:
                conditions.append(f'"{column}" > {high}')
            if not conditions:
                continue
            where = " or ".join(conditions)
            bad = conn.execute(text(f'select count(*) from "{table}" where {where}')).scalar()
            if bad:
                findings.append(Finding(
                    "validity", table, column,
                    f"{bad} row(s) fall outside the expected range "
                    f"[{low if low is not None else '-inf'}, {high if high is not None else '+inf'}]",
                    "critical", sample_count=bad,
                ))
        for table, column, allowed in _ENUM_CHECKS:
            placeholders = ", ".join(f"'{v}'" for v in allowed)
            bad = conn.execute(text(
                f'select count(*) from "{table}" where "{column}" is not null '
                f'and "{column}" not in ({placeholders})'
            )).scalar()
            if bad:
                findings.append(Finding(
                    "validity", table, column,
                    f"{bad} row(s) have a value outside the known allowlist {sorted(allowed)}",
                    "warning", sample_count=bad,
                ))
    return findings


def check_timeliness(engine) -> list[Finding]:
    """Staleness -- rows whose timestamp column is older than expected,
    per _STALENESS_CHECKS."""
    from sqlalchemy import text
    findings = []
    now = datetime.now(timezone.utc)
    with engine.connect() as conn:
        for table, ts_column, max_age_hours, context in _STALENESS_CHECKS:
            cutoff = now - timedelta(hours=max_age_hours)
            stale = conn.execute(text(
                f'select count(*) from "{table}" where "{ts_column}" < :cutoff'
            ), {"cutoff": cutoff}).scalar()
            if stale:
                findings.append(Finding(
                    "timeliness", table, ts_column,
                    f"{stale} row(s) older than {max_age_hours}h ({context})",
                    "warning", sample_count=stale,
                ))
    return findings


def not_automatable_findings() -> list[str]:
    """Laudon's remaining two of seven dimensions -- documented explicitly,
    never silently skipped, and never written to quality_audits: that
    table's CHECK constraint (0037) deliberately only allows the 5
    automatable dimension values, so these are reported to stdout only,
    never as a row that would misleadingly look like a completed
    accuracy/accessibility audit."""
    return [
        "Accuracy is not automatable: it requires ground truth to compare stored "
        "values against, which ImpactProof doesn't have for its own operational data.",
        "Accessibility is not automatable: it requires an end-user perception "
        "survey, which hasn't been run.",
    ]


def write_findings(engine, findings: list[Finding]) -> None:
    """Every Finding passed here must already carry one of the 5 automatable
    dimension values (completeness/consistency/uniqueness/validity/
    timeliness) -- see not_automatable_findings() for why the other two
    never reach this function."""
    from sqlalchemy import text
    if not findings:
        return
    with engine.begin() as conn:
        for f in findings:
            conn.execute(text("""
                insert into quality_audits (dimension, table_name, column_name, finding, severity, sample_count)
                values (:dimension, :table_name, :column_name, :finding, :severity, :sample_count)
            """), {
                "dimension": f.dimension, "table_name": f.table_name, "column_name": f.column_name,
                "finding": f.finding, "severity": f.severity, "sample_count": f.sample_count,
            })


def main() -> int:
    engine = _get_engine()
    findings: list[Finding] = []
    findings += check_completeness(engine)
    findings += check_consistency(engine)
    findings += check_uniqueness(engine)
    findings += check_validity(engine)
    findings += check_timeliness(engine)

    write_findings(engine, findings)

    print(f"Quality audit complete: {len(findings)} finding(s) written to quality_audits.")
    for f in findings:
        print(" ", f)
    print()
    print("Not automatable this pass (documented, not skipped silently):")
    for note in not_automatable_findings():
        print(" ", note)

    return 1 if any(f.severity == "critical" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
