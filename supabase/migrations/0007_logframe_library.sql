-- 0007_logframe_library.sql
-- Reusable, named logframe indicator lists a user saves once and loads into
-- future audits instead of retyping. Item columns deliberately mirror the
-- logframe subset of app.py's _PORTFOLIO_COLUMNS -- the same shape CSV
-- Portfolio upload and Instant Report Check batch extraction already
-- produce, so "save these extracted/uploaded indicators to my library"
-- is a straight insert with no new mapping logic.
create table if not exists logframe_libraries (
  id          bigserial primary key,
  email       text not null references users(email) on delete cascade,
  name        text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists logframe_library_items (
  id                  bigserial primary key,
  library_id          bigint not null references logframe_libraries(id) on delete cascade,
  indicator_name      text,
  logframe_indicator  text,
  logframe_baseline   text,
  logframe_target     text,
  logframe_achievement text,
  sector              text,
  created_at          timestamptz not null default now()
);

create index if not exists logframe_libraries_email_idx on logframe_libraries(email);
create index if not exists logframe_library_items_library_idx on logframe_library_items(library_id);

alter table logframe_libraries disable row level security;
alter table logframe_library_items disable row level security;
