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

alter table documents disable row level security;

grant select, insert on documents to app_audits_rw;
grant usage, select on documents_id_seq to app_audits_rw;

-- ============================================================
-- DOWN
-- ============================================================
-- drop table if exists documents;
