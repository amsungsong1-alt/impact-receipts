# ImpactProof Security Policy

*Laudon Ch.8 hardening pass, last reviewed 2026-08-03. Internal document —
governs how ImpactProof itself is built and operated. See
`docs/acceptable_use_policy.md` for the customer-facing rules, and
`docs/incident_response_runbook.md` for what to do during an incident.*

## Scope and ownership

ImpactProof is currently operated by a single founder. Until the team grows,
the founder holds every role below. This is written as role titles, not a
name, so the document doesn't need editing the day a second person joins —
only the roster in `docs/compliance/records_of_processing.md` does.

| Role | Responsibility |
|---|---|
| Security Officer | Owns this policy, approves exceptions, is the incident commander (see runbook) |
| Data Protection Officer (DPO) | Point of contact for Act 843 / NDPA data-subject requests, breach notification decisions |
| On-call / operator | Has production access (Supabase, Streamlit Cloud, VPS, Anthropic, Resend, Paystack dashboards) |

Contact for all three roles today: the account associated with this
repository. Update this table the moment that stops being a single person.

## General controls

**Software.** Dependencies are pinned (`requirements.txt`) and scanned for
known-CVE releases in CI (`.github/workflows/ci.yml`, `pip-audit`). New
dependencies that touch document parsing (PDF/DOCX/XLSX/PPTX libraries) get
extra scrutiny before merging — that's the highest-risk parsing surface in
the app (a crafted upload is attacker-controlled input reaching that code
directly).

**Hardware/infrastructure.** Production runs on Streamlit Community Cloud
(primary) with a documented VPS/Docker fallback (`docker-compose.yml`,
`nginx/`, `scripts/deploy_vps.sh`) for the scenario where Streamlit Cloud is
unavailable — see `docs/disaster_recovery.md`.

**Computer operations.** Deploys happen via `git push` to `main`
(Streamlit Cloud auto-deploys) or `scripts/deploy_vps.sh` for the VPS path.
There is no staging environment today — this is a known gap; the
role-simulation SQL-editor technique and shadow-mode rollouts (see the RLS
migrations' own comments) are the mitigations used in its place for
schema/policy changes specifically.

**Data security.** See `docs/privacy_notice.md` for what's collected and
why. In summary: uploaded document bytes are processed in-memory only and
never persisted (enforced by `test_document_retention.py`); saved
assessment content is encrypted at rest (Fernet, `AUDIT_ENCRYPTION_KEY`,
`utils/crypto.py`); the encryption key lives only in deployment secrets,
never in the repository, and its loss makes existing encrypted content
permanently unrecoverable (no rotation mechanism exists yet — see the risk
register's row on this).

**Implementation controls.** Every merge to `main` must pass the full test
suite (`python test_*.py`, 25+ files, no pytest, no network calls) —
enforced in CI. Schema changes to tables carrying customer data go through
a numbered, reviewed SQL migration file (`supabase/migrations/`), never an
ad hoc change via the Supabase dashboard SQL editor in production.

**Administrative controls.** Admin dashboard access requires: (1) a shared
passphrase (`ADMIN_PASSPHRASE`, rate-limited fail-closed), (2) a DB-backed
role check (`users.role IN ('admin','owner')` or the legacy `is_admin`
flag), and (3) mandatory TOTP two-factor for any account on the new role
tier (`utils/twofactor.py`). All three layers are independent — no single
credential is sufficient on its own.

## Application controls

**Input controls.** File uploads are validated by content (magic bytes),
not just extension, size-capped, and macro-bearing formats are rejected
outright rather than sanitized (`utils/upload_guard.py`). LLM-extracted
structured data is validated against a schema before touching the database
or the UI (`utils/extraction_schema.py`) — model output is treated as
untrusted input, the same as a user-submitted form field.

**Processing controls.** The deterministic scoring engine (`evaluator.py`)
is pure and offline — same inputs always produce the same score, with zero
network dependency. The optional AI narrative layer (`council.py`) is
additive and degrades to a clear "unavailable" state per member on any API
failure, never blocking or corrupting the deterministic score.

**Output controls.** AI-drafted narrative text is checked against the
user's own submission before display (`utils/fabrication_guard.py`) — any
number or score claim the model invents that isn't traceable to the user's
own input is withheld, never shown as if verified.

## Risk assessment

See the risk assessment table produced at the start of this hardening pass
(numbered rows, asset/threat/probability/impact/control/gap format) —
retained in the planning record for this work. Re-run this exercise
whenever a major feature ships that introduces a new data flow or trust
boundary, not on a fixed calendar schedule.

## Identity and access management

See `supabase/migrations/0050_users_role_and_totp.sql` and
`docs/compliance/records_of_processing.md` for the current role model.
Summary: least privilege by default (`role` defaults to `'user'`, zero
admin surface); mandatory 2FA for `admin`/`owner`; forced re-authentication
(a fresh emailed code, `_require_step_up_reauth()`) before the one
genuinely destructive self-service action that exists today — permanently
deleting your own saved history.

## Disaster recovery vs. business continuity

Two separate documents, two separate concerns, per Laudon's own
distinction: `docs/disaster_recovery.md` (how the *systems* come back) and
`docs/business_continuity.md` (how the *business*, i.e. a customer
mid-assessment, keeps functioning while that happens).

## Information systems audit

`scripts/security_audit.py` checks RLS coverage, unencrypted columns, stale
access grants, secrets in the repo, dependency CVEs, certificate expiry, and
retention-policy violations, and outputs a ranked weakness list. Run it
after any change to the data model, IAM, or dependency set — not only on
schedule.
