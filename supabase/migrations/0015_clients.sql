-- 0015_clients.sql
-- Agency-tier concept: a Client is a named grouping an agency user creates to
-- organize their own saved audits (e.g. "Action Aid Ghana", "GIZ WASH
-- consortium"). Mirrors logframe_libraries' shape/conventions exactly
-- (0007_logframe_library.sql) -- a small, user-owned table with no content
-- of its own beyond a name, referenced by audits.client_id.
--
-- Gated in application code by users.plan == 'agency' (utils/metering.py) --
-- nothing here enforces that at the DB level; a non-agency account that
-- somehow inserts a client row is harmless (it just won't be reachable from
-- any UI), matching this codebase's existing "enforce in app code, not SQL"
-- convention (see 0005's RLS-disable comment).
create table if not exists clients (
  id          bigserial primary key,
  email       text not null references users(email) on delete cascade,
  name        text not null,
  created_at  timestamptz not null default now()
);

create index if not exists clients_email_idx on clients(email);

alter table clients disable row level security;

-- Nullable: existing audits (and audits saved by non-agency users) have no
-- client. ON DELETE SET NULL, not CASCADE -- deleting a Client must not
-- delete the underlying audits, only unassign them (an audit is real,
-- billable-check history; a Client is just an agency-side label on it).
alter table audits add column if not exists client_id bigint references clients(id) on delete set null;

create index if not exists audits_client_idx on audits(client_id);

grant select, insert, update, delete on clients to app_audits_rw;
grant usage, select on clients_id_seq to app_audits_rw;
