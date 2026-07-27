"""
scripts/generate_data_dictionary.py

Laudon Ch.6, C2: regenerates docs/data_dictionary.md from the LIVE schema
(information_schema.tables/.columns -- always structurally fresh, can never
drift) merged with knowledge/data_dictionary_annotations.yaml (the parts no
introspection can produce: a plain-English definition, allowed values,
source, and owner per table/column).

A table or column present in the database but missing from the annotations
file renders as "**TODO: needs annotation**" rather than a guessed
description -- this script's own no-fabrication rule, applied to
documentation instead of evidence. It never invents a plausible-sounding
definition for something nobody has actually described.

Run:
    python scripts/generate_data_dictionary.py > docs/data_dictionary.md

Requires SUPABASE_DB_URL (same secret/env-var convention as every
utils/*.py module's _get_engine()) pointed at a real Postgres database --
information_schema doesn't exist in SQLite, so this cannot run against the
in-memory test fixtures the rest of this codebase's test suite uses. Point
it at a disposable branch database, never production, when regenerating
after a schema change that hasn't been applied to production yet.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone

import yaml

_ANNOTATIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge", "data_dictionary_annotations.yaml",
)

_TODO = "**TODO: needs annotation**"

# Tables intentionally excluded from the generated dictionary -- Postgres/
# Supabase system or extension-managed relations that would otherwise show
# up in information_schema.tables alongside this app's own tables.
_SYSTEM_TABLE_PREFIXES = ("pg_", "sql_")


def _get_engine():
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        print("SUPABASE_DB_URL is not set -- point it at a disposable branch database, "
              "never production.", file=sys.stderr)
        sys.exit(1)
    from sqlalchemy import create_engine
    return create_engine(db_url, pool_pre_ping=True)


def load_annotations() -> dict:
    """Same hot-reload-on-every-call convention as knowledge/mel_calendar.yaml
    etc. -- returns {} (never raises) if the file is missing or malformed,
    which simply means every table/column falls through to _TODO."""
    if not os.path.isfile(_ANNOTATIONS_PATH):
        return {}
    try:
        with open(_ANNOTATIONS_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def introspect_schema(engine) -> dict:
    """Returns {table_name: [{"column", "type", "nullable"}, ...]}, ordered
    by table name then ordinal position -- the live, structural ground
    truth this script never lets drift from what's actually in the
    database."""
    from sqlalchemy import text

    query = text("""
        select table_name, column_name, data_type, is_nullable
        from information_schema.columns
        where table_schema = 'public'
        order by table_name, ordinal_position
    """)
    schema: dict = {}
    with engine.connect() as conn:
        for table_name, column_name, data_type, is_nullable in conn.execute(query):
            if any(table_name.startswith(p) for p in _SYSTEM_TABLE_PREFIXES):
                continue
            schema.setdefault(table_name, []).append({
                "column": column_name, "type": data_type, "nullable": is_nullable == "YES",
            })
    return schema


def render_markdown(schema: dict, annotations: dict) -> str:
    tables_meta = annotations.get("tables", {})
    lines = [
        "# ImpactProof data dictionary",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`scripts/generate_data_dictionary.py` — do not hand-edit this file directly; edit "
        "`knowledge/data_dictionary_annotations.yaml` and regenerate instead.",
        "",
        f"{_TODO} markers below mean the live schema has a table/column with no matching "
        "entry in the annotations file — never a guessed description.",
        "",
    ]
    for table_name in sorted(schema.keys()):
        table_meta = tables_meta.get(table_name, {})
        table_desc = table_meta.get("description", _TODO)
        table_owner = table_meta.get("owner", _TODO)
        col_meta = table_meta.get("columns", {})

        lines.append(f"## `{table_name}`")
        lines.append("")
        lines.append(table_desc)
        lines.append("")
        lines.append(f"**Owner:** {table_owner}")
        lines.append("")
        lines.append("| Column | Type | Nullable | Definition | Allowed values | Source |")
        lines.append("|---|---|---|---|---|---|")
        for col in schema[table_name]:
            meta = col_meta.get(col["column"], {})
            definition = meta.get("definition", _TODO)
            allowed = meta.get("allowed_values", "—")
            source = meta.get("source", _TODO)
            nullable = "yes" if col["nullable"] else "no"
            lines.append(
                f"| `{col['column']}` | `{col['type']}` | {nullable} | {definition} | "
                f"{allowed} | {source} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    engine = _get_engine()
    schema = introspect_schema(engine)
    annotations = load_annotations()
    print(render_markdown(schema, annotations))
    return 0


if __name__ == "__main__":
    sys.exit(main())
