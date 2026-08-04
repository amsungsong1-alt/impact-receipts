-- 0041_rls_examples.sql
-- Laudon Ch.8 hardening: first table to get real RLS (not just the
-- disable-everywhere posture from 0005), chosen deliberately as the
-- lowest-risk table in the whole schema to prove the migration mechanics
-- (syntax, rollback via `alter table examples disable row level security;`,
-- CI's test_rls_coverage.py check) before touching anything with real user
-- data. `examples` holds shared placeholder text (field_name/sector/value),
-- has no tenant column, and both roles that reach it via the anon-key REST
-- client (utils/db.py::save_example/get_examples) do so on behalf of any
-- signed-in-or-not visitor -- so "authenticated, anon" read+insert is the
-- correct policy, not a behavior change from today's RLS-off posture.
alter table examples enable row level security;

create policy examples_read_all on examples
  for select to authenticated, anon using (true);

create policy examples_insert_all on examples
  for insert to authenticated, anon with check (true);
