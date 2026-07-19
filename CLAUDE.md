# ImpactProof — architecture notes for Claude Code

ImpactProof is a Streamlit SaaS that scores NGO/MEL donor-report evidence on two axes
(Confidence, Clarity) across eight rule-based criteria, with AI features layered on top for
interrogation, drafting, and indicator matching. Deployment: GitHub → Streamlit Cloud
(auto-deploys on push to `main`).

## Non-negotiable rule: no fabrication

No AI feature may invent, estimate, or impute a number, date, or fact the user didn't supply.
AI may question, critique, rephrase, and flag gaps — never fill them with generated content.
`council.check_fabrication()` (council.py) is the machine-checked enforcement of this: it
extracts every numeral/year/percentage from an AI-drafted statement and verifies each one
appears somewhere in the user's own raw submission fields (not the truncated, score-annotated
LLM prompt context — see `council._submission_fact_text()`). Anything that fails is withheld,
not shown, with the literal message "AI draft withheld — it introduced content not in your
evidence." Any new AI feature that rewrites user text must route through this guard (or an
equivalent) before rendering its output.

## File map

- **`app.py`** (~11,500 lines) — the Streamlit UI. Four screens driven by
  `st.session_state["screen"]` (0–3: Landing, Result Submission, Confidence Snapshot,
  Portfolio Dashboard), mirrored into `st.query_params`. Screen 1 has an internal 4-tab flow
  per result slot. `main()` is the single entry point.
- **`evaluator.py`** — the deterministic scoring engine. No Streamlit import, no API calls,
  same inputs always produce the same outputs. `evaluate_submission()` is the top-level
  orchestrator; `compute_confidence`/`compute_clarity`/`compute_beneficiary_voice_bonus` are
  the scoring primitives. Includes the org-type-aware two-track threshold (CBO/Government=3.5,
  National NGO=3.75, INGO=4.0).
- **`diagnostics.py`** — readiness-band and diagnostic-state classification (7-state badge:
  STRONG / NEEDS REFINEMENT / MISLEADING / UNDEREVIDENCED / FUNDAMENTALLY WEAK / INCOMPLETE /
  INVALID INPUT, collapsed into a 3-state readiness band). Also UI-free.
- **`council.py`** — every live Claude API call for advisory/AI-assist features:
  - `run_council_assessment()` — 5-persona Claude Haiku "Council Assessment" (Evidence Auditor,
    Programme Strategist, Critical Reviewer, Implementation Guide, Donor Lens) + one synthesis
    call producing `upgraded_result_statement`/`upgraded_evidence_statement` and a plain-English
    reporting-team brief. Fabrication-guarded (see above) before returning.
  - `debate_evidence_type()` — 5-member debate classifying evidence into the closest-fit type.
  - `match_logframe_indicator()` — matches a result statement against user-pasted logframe
    indicators; never forces a match, and discards any suggestion that isn't verbatim one of
    the pasted candidates.
  - `_calculate_projected_scores()` — deterministic, no AI (sums `fixes[].score_impact_value`).
- **`metrics.py`** — privacy-safe usage instrumentation. Append-only JSON-lines event log (no
  PII, no result text — timestamp, one-way session hash, event type, score band/delta only).
  `log_event()`/`read_events()`/`summarize()` are the only call sites the rest of the app should
  use; the backend can move to Supabase later without touching callers. **Caveat:** Streamlit
  Community Cloud's filesystem is ephemeral and does not survive a redeploy — this file-backed
  store is fine for local dev and short demos, not a durable record across deploys.
- **`donor_templates.py`** — static donor-specific diagnostic copy (USAID, FCDO, GIZ, World
  Bank citations). No functions, no API calls.
- **`prompts.py`** — mostly UI copy/tooltips consumed by app.py. Also contains a dormant,
  unused `SYSTEM_PROMPT`/`build_user_prompt()` for an earlier full-LLM-scorer design that was
  superseded by the deterministic `evaluator.py` — not wired into any current call path.
- **`utils/`** — `db.py` (Supabase user/draft/example/payment-history persistence), `paystack.py`
  (one-off payments + Plan-tied subscriptions, cancellation, webhook signature verification),
  `auth.py` (magic-link login tokens + durable session tokens), `metering.py` (centralized
  free-check/paid-plan access checks — the single place every feature gate should read),
  `audits.py` (SQLAlchemy-backed opt-in saved audit history, Logframe Library, anonymized
  benchmark, append-only access log, rate limiting, and account-data-deletion — a second,
  direct-Postgres access path into the same Supabase database, alongside `db.py`'s REST-based
  one), `crypto.py` (Fernet field-level encryption for stored audit content), `whatsapp.py`
  (WhatsApp Cloud API notifications/deep-links), `email_otp.py`, `anonymize.py`, `crm.py`
  (per-account CRM events + Trial/Active-Free/Professional/Agency/Churn-risk segmentation for
  the admin dashboard — a third, deliberately separate, plaintext-account-identified
  direct-Postgres store alongside `audits.py`'s and `metrics.py`'s anonymous one).

## Billing & auth

Self-serve subscription billing (Paystack: card, mobile money, bank — Ghana). Durable,
passwordless accounts: a login email carries both a magic link (single-use, ~20 min,
`utils/auth.py`'s `login_tokens` table, redeemed via a confirm-click landing page — never on a
bare GET, since email security scanners can pre-fetch and burn a link) and a 6-digit code
fallback (unchanged from before, still session-local). A successful login issues a long-lived
(~60 day, slides forward on use) session token mirrored into the URL as `?session=...`
(`utils/auth.py`'s `sessions` table), so a bookmarked/returning visit re-authenticates silently
without retyping an email — no cookie library, following the same query-param-mirroring pattern
`screen`/`tab` already use.

`utils/metering.py` (`check_access()`/`record_check()`) is the single source of truth for "can
this account do X" — every feature gate should read it rather than re-deriving
`is_paid`/`free_checks_used` independently (a past bug: three features read a session-state key
nothing ever wrote, making them silently unlimited-free). `FREE_CHECKS_LIMIT` is defined there,
not in `app.py`.

Subscriptions are real Paystack Plans (Professional monthly/annual, Agency monthly — plan codes
created once via `scripts/setup_paystack_plans.py`, pasted into secrets), not the older
"buy N days" one-off-transaction model — pay-per-use is the one tier that intentionally stays a
plain one-off transaction. `supabase/functions/paystack-webhook/` (a Supabase Edge Function,
since Streamlit Cloud can't host a custom inbound route) handles renewal/failure/cancellation
events and is the DB-authoritative writer for subscription status; `payments` is the durable
invoice-history table read by the billing settings page.

## Opt-in audit persistence, Logframe Library, benchmark

Off by default, and the stateless no-storage path stays fully functional for anyone who never
opts in. `utils/audits.py` connects to the same Supabase Postgres database `utils/db.py` uses,
but directly via SQLAlchemy (a `SUPABASE_DB_URL` connection-string secret) rather than through
Supabase's REST API — schema lives in `supabase/migrations/0006`–`0011` (the SQLAlchemy models
map onto that schema, they don't generate it), and every new table there has RLS explicitly
disabled, matching `0005`'s fix and this app's anon-key/app-level-auth security model.
`SUPABASE_DB_URL` should use `app_audits_rw` (created in `0009`), a least-privilege role scoped
only to this module's own tables — not the default `postgres` superuser, which bypasses every
GRANT/REVOKE check and would silently defeat the access log's append-only guarantee below.

A user who checks "Save this audit to my private history (encrypted at rest)" on Screen 2 gets
one `audits` row per submission-run (not per individual result — `evaluations`/
`submissions_snapshot` are always a run's worth together), viewable/re-downloadable/deletable
from the My Audits page. `submissions_json`/`evaluations_json` (and the Logframe Library's five
free-text fields) are genuinely encrypted at rest via `utils/crypto.py` (Fernet, key in
`AUDIT_ENCRYPTION_KEY`) — the denormalized `donor`/`sector`/`org_type`/score columns stay
unencrypted by design (constrained dropdown values, not free text), so listing and
benchmarking never need decryption. Key rotation isn't implemented; losing
`AUDIT_ENCRYPTION_KEY` makes existing encrypted content permanently unrecoverable. The Logframe
Library (`logframe_libraries`/`logframe_library_items`) lets a user save a named, reusable
indicator list from Screen 1's Logframe tab and load it into a future audit instead of retyping
it — reuses the same column shape as CSV Portfolio upload and IRC batch extraction.

The "How you compare" benchmark (`audit_aggregate_stats`) buckets by `(donor, sector, org_type)`
— `org_type` matters because it changes the actual pass/fail threshold used for scoring (3.5
CBO/Government, 3.75 National NGO, 4.0 INGO), so bucketing by donor+sector alone would compare
submissions scored against different bars. Buckets store raw score arrays only (no submission
content), recomputed synchronously right after each opt-in save; `get_benchmark()` returns
`None` below `MIN_BENCHMARK_SAMPLE` (10) rather than showing a percentile from a near-empty
bucket. Shown both on-screen (`_render_result_card()`) and on the exported PDF
(`_build_html_report_card()`).

`access_log` (`0010`) is an append-only trail (every `utils/audits.py` write, plus
`"account_purge"`) — append-only via GRANT scope, not RLS: `app_audits_rw` gets `select`/`insert`
only, no `update`/`delete`. `check_rate_limit()` reads it to throttle save/upload actions
(`save_audit`, `add_library_items`, Instant Report Check extraction, CSV Portfolio upload) and
fails *open* on any DB error, matching this module's degrade-gracefully convention — paired with
Nginx's own `limit_req` zone (`nginx/conf.d/impactproof.conf`) at the HTTP layer.

The "erase my history" Danger Zone (My Audits page) calls `purge_account_audit_content()`
(deletes `audits` + `logframe_libraries`, items cascade) plus `utils/db.py`'s
`clear_user_draft()`/`delete_wa_conversations()` — deliberately scoped to MEL content only:
`payments` (independent tax/accounting retention), `sessions`/`login_tokens`, and the `users`
row itself are untouched. `wa_conversations` has no foreign key to `users` at all, so
`delete_wa_conversations()` is the only thing that ever removes those rows.

Row isolation is enforced entirely in application code (every `utils/audits.py` function checks
`row.email == <caller-supplied email>` before returning/mutating), not Postgres RLS — see the
prior paragraph's incident. The actual bug surface for cross-account leakage is therefore always
upstream, in whatever calls into this module: every `app.py` call site has been audited to
confirm it only ever passes a freshly-read `st.session_state.get("user_email", "")`, and
`_load_from_inputs_json()` was fixed to never let uploaded/imported data overwrite an
already-authenticated session's email (the concrete vulnerability this pattern was written to
close — see git history).

## CRM analytics & onboarding email drip

`utils/crm.py` logs per-account events (`signup`, `audit_run`, `framework_used`, `tier_change`,
`upgrade_prompt_shown`/`_clicked`, `whatsapp_click`) to a `crm_events` table — deliberately a
new table, not an extension of `metrics.py` (anonymous, one-way-hashed session ids, tested to
never leak an email — see `test_metrics.py`) or `utils/audits.py`'s `AccessLog`/`access_log`
(a permanent security-audit trail excluded from account purges). `crm_events` is high-volume
growth data and *is* in scope for the "erase my history" purge (`purge_account_crm_events()`).
Connects via the same `SUPABASE_DB_URL`/SQLAlchemy pattern as `utils/audits.py`, granted to the
same `app_audits_rw` role (schema in `supabase/migrations/0012`–`0013`).

`build_segments()` buckets every account into Trial / Active-Free / Professional / Agency /
Churn-risk (mutually exclusive, Churn-risk computed first across any tier — 30+ days since the
last `crm_events` row, not `sessions.last_seen_at`, since a session refreshes on any page load
even without a meaningful action) plus a cross-cutting `agency_ready` flag (2+ distinct donor
frameworks or 3+ audit runs in a rolling 30 days — computed from `crm_events` directly, not the
opt-in-only `audits` table, so it doesn't blindly miss the majority of usage that never opts
into saving audit history). Shown on the hidden `?admin=1` dashboard (`_render_admin_view()`,
`app.py`) with per-segment CSV export; that gate is now rate-limited and logged
(`check_rate_limit`/`log_access`, both from `utils/audits.py`) since it went from exposing only
anonymous counts to plaintext account emails.

The day-0 welcome email (`utils/email_otp.py`'s `send_welcome_email()`) already existed; day-3
(case study) and day-7 (upgrade offer) are new (`send_case_study_email()`/
`send_upgrade_offer_email()`, same file). Since Streamlit has no background-job runner and the
VPS's host crontab only covers that one deployment, the actual scheduled sends happen from a
third Supabase Edge Function, `supabase/functions/onboarding-drip/`, invoked hourly by
`pg_cron`/`pg_net` (`supabase/migrations/0014`) — the only mechanism that reaches signups from
both deployments, since it lives entirely in Supabase. That function re-implements the same
HTML as TS string literals (Deno can't import the Python module) — keep both copies in sync by
hand if the marketing copy changes. Unsubscribe is a `users.unsubscribe_token` (migration
`0013`) linked from every marketing send's footer, routed through `app.py`'s `?unsubscribe=`
query-param landing (`_render_unsubscribe_landing()`) to `utils/db.py`'s
`set_marketing_opt_out_by_token()` — never reveals whether a given token matched a real account.

## AI call sites and models

All Claude calls read `ANTHROPIC_API_KEY` from `st.secrets` with an `os.environ` fallback, and
every call site has a graceful rule-based/manual fallback when the key is missing or the call
fails — the app must stay fully usable offline-from-API. Current model IDs in use:
`claude-sonnet-4-6` (Instant Report Check extraction, batch/portfolio extraction, Audit My
Report) and `claude-haiku-4-5-20251001` (Council Assessment, evidence-type debate, logframe
match, score-explanation chat). These are pinned, dated snapshots — check the current
recommended aliases before introducing a new call site.

## Testing

Seven plain-`assert` golden-test files, no pytest, no network calls, no mocking framework
(API-calling functions are tested by temporarily swapping `council._call_haiku`, or
`utils.paystack.requests`/`utils.db._get_client`/`utils.auth._get_client`, for a fake;
`test_audits.py`/`test_crm.py` swap `utils.audits._get_engine`/`utils.crm._get_engine` for an
in-memory SQLite engine instead, since the same SQLAlchemy models work unchanged against either
dialect — note SQLite doesn't enforce foreign keys by default unlike Postgres, so that fixture
explicitly enables `PRAGMA foreign_keys=ON` to exercise cascade-delete behavior correctly;
`test_security.py` imports `app.py` itself in Streamlit's "bare mode," where `st.session_state`
still behaves as a plain dict within one process):

```powershell
python test_app.py       # evaluator.py + diagnostics.py scoring behaviour
python test_council.py   # fabrication guard + logframe match
python test_metrics.py   # metrics event logging/summarization
python test_billing.py   # auth token lifecycle, metering, Paystack subscriptions/webhook sig
python test_audits.py    # saved audits, logframe library, benchmark, access log, encryption, deletion
python test_crm.py       # crm events, agency-ready detection, account segmentation, purge
python test_security.py  # app.py-level regression tests (currently: the user_email overwrite guard)
```

All seven must pass before pushing a change that touches scoring, AI post-processing, metrics,
billing/auth, or audit persistence. When you intentionally change scoring behavior, re-baseline
`test_app.py`'s golden values in the same commit — a scoring change that leaves the golden values
stale silently breaks the safety net for the next change.

## Deployment

Streamlit Cloud auto-deploys `app.py` on push to `main` — but it cannot host a custom inbound
HTTP route or a background/scheduled job, so three features live as separate Supabase Edge
Functions, deployed independently via the Supabase CLI: two inbound webhooks (WhatsApp, Paystack)
and one `pg_cron`-scheduled function (the onboarding email drip):

```powershell
supabase functions deploy whatsapp-webhook
supabase functions deploy paystack-webhook
supabase functions deploy onboarding-drip
```

Each function has its own secrets, set via `supabase secrets set` — a **separate store** from
Streamlit's `st.secrets`/App settings, even though some values (e.g. `PAYSTACK_SECRET_KEY`) are
the same underlying key duplicated into both places. Register each function's URL
(`https://<PROJECT_REF>.supabase.co/functions/v1/<name>`) in the corresponding provider's
dashboard (Meta for WhatsApp, Paystack's Settings → API Keys & Webhooks). Deploy/register the
webhook *before* relying on the feature it supports in production — e.g. don't wire a live
Paystack Plan's Subscribe button until `paystack-webhook` is deployed and registered, or renewal/
failure/cancellation events have nowhere to land.

Database schema changes live in `supabase/migrations/` — apply new files with `supabase db push`
(or paste each file's SQL into the Supabase SQL editor) rather than hand-writing `ALTER TABLE`
statements against a running project.

### Docker / VPS deployment (alternative to Streamlit Cloud)

A self-hosted path exists alongside Streamlit Cloud's auto-deploy — the two are parallel
options, not a replacement of one by the other, and both read the same secret *names* from
different stores (Streamlit Cloud's App settings → Secrets vs. Docker's `.env`/`env_file:`).
Every secret-read call site in the codebase already has an `os.environ` fallback, so moving to
Docker needed zero application-code changes. `Dockerfile` + `docker-compose.yml` (`app` + `nginx`
+ an on-demand `certbot` service) + `nginx/` (reverse proxy, WebSocket upgrade headers, the
`Host` header Streamlit's `enableXsrfProtection=true` requires, gzip, `limit_req` rate limiting)
+ `scripts/deploy_vps.sh` (assumes an existing Ubuntu/Debian VPS — DigitalOcean/Hetzner both
provision plain Ubuntu boxes, no cloud-API integration needed). The two Supabase Edge Functions
are hosted by Supabase independently of where the Streamlit app itself runs — this deployment
path requires zero changes to them. TLS's first-ever certificate issuance is a documented,
manual two-phase process (Nginx must already be serving the ACME challenge before certbot can
succeed against it) — not something the deploy script attempts to automate blind. OSS Nginx has
no active upstream health check (that's an Nginx-Plus feature); recovery relies on Docker's
`HEALTHCHECK` + `restart: unless-stopped` on both real services.

## Working conventions

- Rules are the source of truth for scores; AI narrates and interrogates around them — never
  let an AI call touch `compute_confidence`/`compute_clarity`/governance scoring/the diagnostic
  classifier/banding thresholds.
- One feature per commit, each independently revertable.
- New AI-assisted UI (buttons, expanders) must hide/disable cleanly when no API key is
  configured, leaving the manual/rule-based path fully functional.
- `_irc_widget()` (app.py) is the pattern for any field an AI feature pre-fills: write the
  plain session_state key, bump `st.session_state["_irc_fill_version"]`, then `st.rerun()`.
