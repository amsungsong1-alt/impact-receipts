"""
test_rls_coverage.py — CI gate for Row-Level Security coverage (Laudon Ch.8
hardening, prompt 08 acceptance criterion: "Zero tables without RLS; test
enforces it in CI").

No pytest, no real network calls, no live Postgres connection: this repo's
existing test suite is deliberately network-free (see CLAUDE.md), and there
is no staging Supabase project to introspect `pg_tables`/`pg_policies`
against. Instead, this statically parses every file in
supabase/migrations/*.sql, in order, and reconstructs each table's final RLS
state the same way Postgres would apply the migrations sequentially:
  - `create table if not exists X (...)` registers X as a known table.
  - `alter table [if exists] X enable|disable row level security` updates
    X's last-seen RLS state (later files override earlier ones, matching
    real migration application order).
  - `create policy ... on X ...` records that X has at least one policy.

A table with RLS enabled but zero policies is a silent deny-all -- that's a
correctness bug (breaks every legitimate caller), not a security win, so it
fails this test the same as RLS being disabled.

Run with: python test_rls_coverage.py
"""
from utils.rls_coverage import compute_rls_state, EXEMPT_TABLES


def run_every_known_table_has_rls_state_recorded():
    """Every `create table` must have at least one explicit enable/disable
    statement somewhere -- a table nobody ever touched RLS on at all is the
    exact "silently exposes everything" failure mode this test exists to
    catch (Supabase's own default for a table created outside the SQL
    editor's RLS wizard is RLS-off with full anon/authenticated grants)."""
    tables, rls_state, _ = compute_rls_state()
    missing = sorted(t for t in tables if t not in rls_state)
    assert not missing, (
        f"Table(s) with no RLS enable/disable statement at all -- undefined, "
        f"unreviewed RLS posture: {missing}"
    )
    print(f"PASS: run_every_known_table_has_rls_state_recorded ({len(tables)} tables checked)")


def run_every_non_exempt_table_has_rls_enabled():
    tables, rls_state, _ = compute_rls_state()
    violations = sorted(
        t for t in tables
        if t not in EXEMPT_TABLES and rls_state.get(t) != "enable"
    )
    assert not violations, (
        f"Table(s) without RLS enabled (and not in the documented "
        f"EXEMPT_TABLES allowlist): {violations}. If a new table is "
        f"genuinely exempt, add it to EXEMPT_TABLES here AND write a "
        f"migration documenting why, matching "
        f"0049_login_sessions_rls_rationale.sql's pattern -- do not just "
        f"widen the allowlist silently."
    )
    print(f"PASS: run_every_non_exempt_table_has_rls_enabled "
          f"({len(tables) - len(EXEMPT_TABLES)} tables enabled, {len(EXEMPT_TABLES)} documented exemptions)")


def run_every_rls_enabled_table_has_at_least_one_policy():
    """RLS enabled with zero policies is a silent deny-all -- catches a
    migration that flips RLS on but forgets the accompanying create policy
    statement(s), which would look identical to "secured" in a naive check
    but actually just breaks every legitimate caller."""
    tables, rls_state, policy_counts = compute_rls_state()
    violations = sorted(
        t for t in tables
        if rls_state.get(t) == "enable" and policy_counts.get(t, 0) == 0
    )
    assert not violations, (
        f"Table(s) with RLS enabled but zero policies -- silent deny-all, "
        f"not actually secured: {violations}"
    )
    print("PASS: run_every_rls_enabled_table_has_at_least_one_policy")


def run_exempt_tables_are_explicitly_disabled_not_just_forgotten():
    """The exemption allowlist above is for a considered "RLS doesn't apply
    here" decision, not a silent gap -- sanity-check that the exempt tables
    are actually explicitly disabled somewhere (0005_disable_rls.sql), not
    merely absent from the enabled set by omission."""
    tables, rls_state, _ = compute_rls_state()
    for t in EXEMPT_TABLES:
        assert t in tables, f"Exempt table {t!r} doesn't exist in any migration -- stale EXEMPT_TABLES entry?"
        assert rls_state.get(t) == "disable", (
            f"Exempt table {t!r} has no explicit 'disable row level security' "
            f"statement -- its exemption isn't actually documented in SQL."
        )
    print("PASS: run_exempt_tables_are_explicitly_disabled_not_just_forgotten")


if __name__ == "__main__":
    run_every_known_table_has_rls_state_recorded()
    run_every_non_exempt_table_has_rls_enabled()
    run_every_rls_enabled_table_has_at_least_one_policy()
    run_exempt_tables_are_explicitly_disabled_not_just_forgotten()
    print("\nAll test_rls_coverage.py tests passed.")
