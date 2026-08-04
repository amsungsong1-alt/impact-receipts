-- 0051_access_log_hash_chain.sql
-- Laudon Ch.8 hardening, C4: tamper-evident (not just append-only) audit
-- trail. 0009_least_privilege_role.sql + 0010_access_log.sql already make
-- access_log append-only BY GRANT SCOPE for the app's own app_audits_rw
-- role (no UPDATE/DELETE grant) -- but that's a permissions fence, not
-- cryptographic tamper evidence: anyone connecting as a more privileged
-- role (the Postgres superuser, or a leaked service-role/DB-owner
-- credential) could still silently edit or delete rows with no trace.
-- Hash-chaining each row to the one before it (Laudon's blockchain point,
-- applied at a proportionate scale -- one linear chain in one table, not a
-- distributed ledger) means even a privileged edit breaks a chain that can
-- be independently re-verified later (scripts/verify_audit_chain.py),
-- rather than silently succeeding.
create extension if not exists pgcrypto;

alter table access_log add column if not exists prev_hash text;
alter table access_log add column if not exists row_hash text;

-- BEFORE INSERT (not application code) so no insert path -- direct SQL,
-- Supabase's REST client, a future feature -- can add a row to this table
-- without it being chained in. A trigger is also the only place that can
-- safely read NEW.created_at (populated by the column default before a
-- BEFORE trigger runs) to include the timestamp in the hash, so the chain
-- also catches a row being backdated, not just its content being edited.
create or replace function access_log_set_hash_chain() returns trigger
language plpgsql
as $$
declare
  _prev_hash text;
begin
  -- Serializes concurrent inserts for the duration of this transaction so
  -- two simultaneous writes can't both read the same "last row" and each
  -- compute a chain link pointing at it -- that would fork the chain into
  -- two branches instead of one linear, fully-ordered sequence. Released
  -- automatically at transaction end; do not wrap this trigger's caller in
  -- a long-running transaction elsewhere, or inserts will queue behind it.
  perform pg_advisory_xact_lock(hashtext('access_log_hash_chain'));

  select row_hash into _prev_hash from access_log order by id desc limit 1;
  new.prev_hash := coalesce(_prev_hash, '');
  new.row_hash := encode(
    digest(
      coalesce(new.prev_hash, '') || '|' ||
      coalesce(new.email, '') || '|' ||
      coalesce(new.action, '') || '|' ||
      coalesce(new.resource_type, '') || '|' ||
      coalesce(new.resource_id, '') || '|' ||
      coalesce(new.ip_address, '') || '|' ||
      coalesce(new.created_at::text, ''),
      'sha256'
    ),
    'hex'
  );
  return new;
end;
$$;

drop trigger if exists access_log_hash_chain_trigger on access_log;
create trigger access_log_hash_chain_trigger
  before insert on access_log
  for each row execute function access_log_set_hash_chain();
