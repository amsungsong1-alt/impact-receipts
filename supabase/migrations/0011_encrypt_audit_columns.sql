-- 0011_encrypt_audit_columns.sql
-- submissions_json/evaluations_json move from jsonb to text: encrypted
-- Fernet ciphertext is not valid JSON, and nothing in this codebase does a
-- SQL-level JSON path query into these two columns (utils/audits.py's
-- list_audits()/get_audit()/_recompute_bucket() only ever read the
-- denormalized donor/sector/org_type/score columns at the SQL level, never
-- the JSON content itself -- confirmed by reading every query in that file).
--
-- IMPORTANT: this migration does NOT itself encrypt any existing data. The
-- `::text` cast below only stringifies whatever is currently stored (valid
-- JSON becomes a JSON-shaped string) -- it does not run existing rows
-- through Fernet. Rows saved before utils/audits.py's encryption wiring
-- shipped remain plaintext-readable (just now text instead of jsonb) until a
-- separate, one-time backfill re-saves them through the encryption path.
-- Do not treat "this migration ran" as "all existing audit content is now
-- encrypted."
alter table audits alter column submissions_json type text using submissions_json::text;
alter table audits alter column evaluations_json type text using evaluations_json::text;
