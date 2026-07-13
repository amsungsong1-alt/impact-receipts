-- 0000_base_schema.sql
-- Foundational schema this app has always assumed exists (previously
-- documented only as prose in README.md and utils/db.py docstrings, never
-- as a tracked file -- this migration makes the schema actually reproducible
-- from a clean Supabase project, which the later 0001-0004 migrations rely
-- on: they only ALTER/reference `users`, they don't create it).

create table if not exists users (
  email             text primary key,
  free_checks_used  int default 0,
  is_paid           bool default false,
  paid_until        date,
  created_at        timestamptz default now(),
  draft_json        text
);

create table if not exists examples (
  id          bigserial primary key,
  field_name  text not null,
  sector      text not null,
  value       text not null,
  created_at  timestamptz default now()
);

create table if not exists wa_conversations (
  id          bigserial primary key,
  created_at  timestamptz default now(),
  context_id  text,
  user_email  text,
  direction   text,
  phone       text,
  body        text,
  success     boolean
);
