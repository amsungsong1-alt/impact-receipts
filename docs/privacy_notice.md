# ImpactProof Privacy Notice

*Last reviewed: 2026-08-02, as part of the Laudon Ch.8 security & compliance
hardening pass. This is a working document for ImpactProof's own compliance
posture and for surfacing to customers/compliance officers who ask what
happens to their data — it is not a substitute for legal review before
publishing as a customer-facing policy page.*

## What we collect and why

| Data | Why | Where it lives |
|---|---|---|
| Account email | Login (magic link + one-time code), billing | Supabase Postgres (`users` table) |
| Uploaded document content (PDF/DOCX/TXT/CSV/PPTX/XLSX) | Extracting structured fields (Instant Report Check, Score My Report) so you don't retype them | **In memory only, for the duration of your request. Never written to disk or a database. Discarded when extraction finishes or your session ends.** |
| Assessment scores, submissions, and evidence text you type into the form | Producing your Confidence/Clarity score, and — if you opt in — saving it to your account history | Supabase Postgres (`audits` table), encrypted at rest (see below) if saved |
| Payment records | Billing, receipts, tax/accounting retention | Supabase Postgres (`payments` table), written by Paystack's webhook |

We do not require you to upload documents to use ImpactProof — the manual
entry form and the deterministic scoring engine work without ever sending a
document anywhere. Uploading is opt-in, for convenience.

## What happens to a document you upload

1. Your browser sends the file to ImpactProof's server over TLS.
2. The server extracts text from it (and, if you use Instant Report Check or
   Score My Report, sends up to 60,000 characters of that text to the
   Anthropic API — see below).
3. The file's raw bytes are **never written to disk, never stored in
   Supabase, and never uploaded to any cloud storage bucket** — this is
   enforced by automated tests (`test_document_retention.py`), not just a
   policy statement. Once extraction finishes, the bytes exist only in the
   server process's memory and are garbage-collected like any other
   temporary variable.
4. If you don't opt in to saving the resulting assessment to your account,
   nothing about that document or its content persists anywhere at all.

## What happens to text sent to the Anthropic API

Instant Report Check, Score My Report, and the optional Council Assessment
narrative all call Anthropic's Claude API, sending extracted document text
or your typed submission as a prompt.

As of this review, Anthropic's Commercial Terms of Service state that:
- Data submitted through the API is **not used to train Anthropic's
  models** by default (this is the standard commercial-API posture, distinct
  from Claude.ai consumer product data handling).
- Anthropic retains API inputs/outputs for a limited period for abuse
  monitoring and safety purposes, per their Privacy Policy and Trust &
  Safety documentation, unless a Zero Data Retention agreement is in place.
- Anthropic acts as a data processor (not controller) for content submitted
  via the API.

**These are Anthropic's own published commercial terms, not modified by
ImpactProof, and they change over time.** Before citing specific retention
windows or contractual language to a customer's compliance officer, or
before registering with Ghana's Data Protection Commission or under
Nigeria's NDPA, verify the current text at Anthropic's Commercial Terms of
Service and Privacy Policy, and consider whether a Data Processing Addendum
or Zero Data Retention agreement with Anthropic is warranted given
ImpactProof's own customer commitments — this is an open item tracked in
`docs/compliance/records_of_processing.md`.

## Cross-border transfer

ImpactProof's infrastructure (Supabase, Streamlit Cloud/VPS hosting,
Anthropic API) is hosted outside Ghana and Nigeria. Uploading a document or
running an assessment means its content (transiently, for extraction) and/or
your submission data (durably, if saved) crosses borders to reach these
providers. This is the same architecture every cloud-hosted SaaS tool used
by an NGO already has — it is called out explicitly here because Act 843 and
the NDPA both impose conditions on cross-border transfer that a data
controller (an NGO using ImpactProof) needs to be able to answer to its own
regulator. See `docs/compliance/records_of_processing.md` for the full
processing register.

## Encryption and retention of saved data

If you choose to save an assessment, the submission and evaluation content
is encrypted at rest (Fernet/AES, key held outside the database) before
being written to Supabase. You can permanently delete your saved history at
any time from the "Danger Zone" section of My Audits — this triggers an
immediate, irreversible delete, not a soft-delete or grace period.

## What we do not do

- We do not sell or share your data with third parties for marketing.
- We do not use your uploaded documents or submission content to train any
  model ourselves.
- We do not require document upload — every scoring path has a manual-entry
  alternative.

## Beneficiary data — please read before uploading

If your report or logframe contains information that could identify
individual beneficiaries — names, exact addresses, health status, or any
detail that could put someone at risk in a sensitive context (survivors of
violence, people with a stigmatized health status, LGBT+ programme
participants, people in a conflict-affected area) — **please redact it
before uploading**, or use the manual entry form instead. ImpactProof scores
report *quality*, not beneficiary identity, and never needs that level of
detail to do so. See the Acceptable Use Policy (`docs/acceptable_use_policy.md`)
for the full rationale and the lawful-basis requirement this reflects.

## Questions

Contact the ImpactProof team via the app's support channel with any privacy
question, including a request to see or delete your data.
