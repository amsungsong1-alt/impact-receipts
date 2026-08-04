-- 0036_documents.sql
-- Laudon Ch.6, C1: the "documents" entity the prompt asks for -- metadata
-- only, never file content. Uploaded files are processed in-memory today
-- and never persisted, by deliberate minimization design; building this
-- literally (storing document content) would reverse that posture. This
-- table gives traceability (which document produced which assessment,
-- roughly when) without storing anything about what was actually in it.
--
-- content_hash is a SHA-256 digest of the extracted text, same technique as
-- export_verifications.content_hash (0019) -- lets a future feature detect
-- "this is the same document I saw before" without keeping the document.
--
-- NOT APPLIED TO PRODUCTION -- written and reviewed only.
create table if not exists documents (
  id             bigserial primary key,
  assessment_id  bigint references assessments(id) on delete set null,
  filename       text,
  content_hash   text,
  uploaded_at    timestamptz not null default now()
);

create index if not exists documents_assessment_idx on documents(assessment_id);

-- RLS (Laudon Ch.8 hardening, 2026): ownership flows through
-- assessments.user_hash (one-way, see 0031_assessments.sql); this table only
-- ever stores filename/content_hash metadata, never document content (see
-- header comment above). Only app_audits_rw ever touches it; default-deny
-- for every other role.
alter table documents enable row level security;

create policy documents_service_bypass on documents
  for all to app_audits_rw using (true) with check (true);

grant select, insert on documents to app_audits_rw;
grant usage, select on documents_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists documents;
