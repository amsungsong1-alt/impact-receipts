# ImpactProof Incident Response Runbook

*Last reviewed: 2026-08-03. Use this during a suspected security incident —
not as a reference to read for the first time while one is happening.*

## Roles

Per `docs/security_policy.md`: the **Security Officer** is the incident
commander for every incident. The **DPO** owns the notification decision
and drafts/sends any regulator or customer communication. Today, one person
holds both roles — the runbook still names them separately so the division
of responsibility is clear the moment a second person joins.

## The six phases

### 1. Detect

Triggers that should start this runbook: a `scripts/security_audit.py` run
surfaces a new high-severity finding; `scripts/verify_audit_chain.py`
reports a broken hash chain; a gitleaks/pre-commit alert on a real secret
(not a documented false positive in `.gitleaks.toml`); an admin-gate
lockout alert email; a report from a user or a third party; unexplained
data in `access_log` (an action from an IP or account pattern that doesn't
match normal use).

**Action:** Note the exact time you became aware (not when the incident
started — when *you* found out). This timestamp starts every clock below.

### 2. Contain

Stop the bleeding before investigating root cause in depth.

- Compromised credential (API key, `ADMIN_PASSPHRASE`, `SUPABASE_DB_URL`,
  `AUDIT_ENCRYPTION_KEY`): rotate it immediately in the relevant secret
  store (Streamlit Cloud secrets / VPS `.env` / Supabase project settings /
  Anthropic console). Note that rotating `AUDIT_ENCRYPTION_KEY` makes all
  existing encrypted content unreadable under the new key — only rotate
  this one if the key itself (not just another credential) is the
  compromised item, and plan a re-encryption pass under the old key first
  if at all possible.
- Compromised account: `revoke_all_sessions(email)` (Billing page, or
  directly via the `sessions` table) and force a password/2FA reset path
  for that account.
- Active RLS/data-exposure bug: the emergency lever is
  `alter table <x> disable row level security;` to restore the pre-bug
  application-level-only posture while you fix the policy — see
  `supabase/migrations/0005_disable_rls.sql`'s own history for why this is
  a safe, instant, reversible action (does not drop the policy, table
  owner always retains access).
- Active abuse (cost attack, brute force): the fail-closed rate limiters
  already block this automatically; if they're somehow not engaging,
  temporarily reduce `max_count`/`window_seconds` in the relevant call site
  or pull the API key being abused.

### 3. Assess

- What data was actually exposed/affected? Which table(s), how many rows,
  which accounts? Query `access_log` (and its hash chain,
  `scripts/verify_audit_chain.py`) for the actual sequence of events.
- Does this meet the bar for a notifiable breach under Act 843 or the NDPA?
  As a rule of thumb: any unauthorized access to, or loss of, personal data
  (beneficiary data in an uploaded document, an account's email, a
  Logframe indicator with individual-level detail) is notifiable-risk
  territory. An internal near-miss with no actual data exposure (e.g. a
  caught bug that never shipped) is not.
- Who is affected — which customer account(s), and transitively, do they
  have beneficiaries whose data was in the affected content?

### 4. Notify

**Nigeria (NDPA 2023): 72-hour clock starts at the detection timestamp
from Phase 1.** The NDPA requires notifying the Nigeria Data Protection
Commission (NDPC) within 72 hours of becoming aware of a breach likely to
result in a risk to data subjects' rights. Build your timeline backward
from that deadline the moment you're in Phase 3:

| Time from detection | Milestone |
|---|---|
| T+0 | Detected. Containment begins immediately (Phase 2). |
| T+4h (target) | Containment substantially complete; assessment (Phase 3) underway. |
| T+24h (target) | Assessment complete enough to decide: notifiable or not? If yes, notification drafting begins. |
| **T+72h (hard deadline, NDPA)** | NDPC notification sent, if the assessment concluded this is a notifiable breach involving Nigerian data subjects. |
| T+72h+ | Affected customers/individuals notified directly, per Act 843/NDPA data-subject-facing requirements, as soon as practicable after the regulator notification (or in parallel, if the facts are already clear). |

**Ghana (Act 843):** Ghana's Data Protection Act imposes a notification
duty to the Data Protection Commission and affected individuals without the
NDPA's specific numeric deadline — treat "without undue delay" as
functionally the same 72-hour target above rather than a reason to move
slower, and verify the current statutory/regulatory guidance text before
finalizing any actual notification, since this summary is not a substitute
for reading Act 843's current text or taking legal advice at the time of a
real incident.

**Do not wait for a perfect understanding of root cause before notifying**
if the 72-hour NDPA clock is running — an initial notification with known
facts, followed by a supplementary one once the investigation concludes, is
the correct approach under both regimes.

### 5. Remediate

Fix the root cause, not just the symptom. Add a regression test that would
have caught this (matching this hardening pass's own convention —
`test_document_retention.py`, `test_rls_coverage.py`, etc. all exist
because of a specific thing they now prevent from silently regressing).
Update `docs/compliance/records_of_processing.md` if the incident changes
any answer in that register (e.g., a new cross-border transfer you hadn't
accounted for).

### 6. Review

Within a week of resolution: write down what happened, what the actual
timeline was (compare to the targets above), what worked, what didn't, and
what changes (code, process, or this runbook) result. File it wherever
`docs/compliance/` decisions are tracked. This is the step most likely to
get skipped under time pressure — don't skip it; it's the only phase that
makes the next incident faster to handle.
