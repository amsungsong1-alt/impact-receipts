-- 0045_rls_audits_and_logframe.sql
-- Laudon Ch.8 hardening, tier 5: audits, logframe_libraries, and
-- logframe_library_items -- the encrypted-at-rest, highest-sensitivity
-- content in this schema (see 0011_encrypt_audit_columns.sql), but still
-- reached exclusively via utils/audits.py's SQLAlchemy connection as
-- app_audits_rw, never the anon-key REST client (confirmed via grep of
-- every `.table(...)` call site). Default-deny for authenticated/anon plus
-- an app_audits_rw bypass -- a behavior no-op for the only role that
-- legitimately touches these tables today, while closing the gap where an
-- anon-key holder could otherwise read/write this content directly via
-- PostgREST despite the app itself never doing so.
alter table audits enable row level security;
create policy audits_service_bypass on audits
  for all to app_audits_rw using (true) with check (true);

alter table logframe_libraries enable row level security;
create policy logframe_libraries_service_bypass on logframe_libraries
  for all to app_audits_rw using (true) with check (true);

alter table logframe_library_items enable row level security;
create policy logframe_library_items_service_bypass on logframe_library_items
  for all to app_audits_rw using (true) with check (true);
