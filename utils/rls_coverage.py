"""
utils/rls_coverage.py — static RLS-coverage introspection shared by
test_rls_coverage.py (the CI gate) and scripts/security_audit.py (the
periodic IS audit). Laudon Ch.8 hardening, C3/C9.

No live Postgres connection: this repo is deliberately network-free in its
test suite (see CLAUDE.md) and there is no staging project to introspect
pg_tables/pg_policies against. Instead, this statically parses every file
in supabase/migrations/*.sql, in order, and reconstructs each table's final
RLS state the same way Postgres applies migrations sequentially:
  - `create table if not exists X (...)` registers X as a known table.
  - `alter table [if exists] X enable|disable row level security` updates
    X's last-seen RLS state (later files override earlier ones).
  - `create policy ... on X ...` records that X has at least one policy.
"""
import os
import re

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "supabase", "migrations"
)

# login_tokens and sessions are read BEFORE any Supabase Auth JWT exists --
# that's how a caller gets one -- so auth.uid()-keyed RLS has no identity to
# check yet at that point. See 0049_login_sessions_rls_rationale.sql for the
# full rationale. These are the ONLY tables exempt from coverage checks.
EXEMPT_TABLES = {"login_tokens", "sessions"}

_CREATE_TABLE_RE = re.compile(r'create\s+table\s+if\s+not\s+exists\s+"?(\w+)"?', re.IGNORECASE)
_ALTER_RLS_RE = re.compile(
    r'alter\s+table\s+(?:if\s+exists\s+)?"?(\w+)"?\s+(enable|disable)\s+row\s+level\s+security',
    re.IGNORECASE,
)
_CREATE_POLICY_RE = re.compile(r'create\s+policy\s+\S+\s+on\s+"?(\w+)"?', re.IGNORECASE)


def _load_migration_files() -> list[str]:
    files = [f for f in os.listdir(_MIGRATIONS_DIR) if f.endswith(".sql")]
    return sorted(files)  # zero-padded numeric prefixes sort in application order


def compute_rls_state() -> tuple[dict, dict, dict]:
    """Returns (tables, rls_state, policy_counts):
      tables: {table_name: first_migration_filename_seen}
      rls_state: {table_name: "enable"|"disable"} -- last statement wins
      policy_counts: {table_name: int}
    """
    tables: dict = {}
    rls_state: dict = {}
    policy_counts: dict = {}
    for fname in _load_migration_files():
        with open(os.path.join(_MIGRATIONS_DIR, fname), "r", encoding="utf-8") as fh:
            content = fh.read()
        for m in _CREATE_TABLE_RE.finditer(content):
            name = m.group(1).lower()
            tables.setdefault(name, fname)
        for m in _ALTER_RLS_RE.finditer(content):
            name, state = m.group(1).lower(), m.group(2).lower()
            rls_state[name] = state  # later files intentionally override earlier ones
        for m in _CREATE_POLICY_RE.finditer(content):
            name = m.group(1).lower()
            policy_counts[name] = policy_counts.get(name, 0) + 1
    return tables, rls_state, policy_counts
