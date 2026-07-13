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
  `whatsapp.py` (WhatsApp Cloud API notifications/deep-links), `email_otp.py`, `anonymize.py`.

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

## AI call sites and models

All Claude calls read `ANTHROPIC_API_KEY` from `st.secrets` with an `os.environ` fallback, and
every call site has a graceful rule-based/manual fallback when the key is missing or the call
fails — the app must stay fully usable offline-from-API. Current model IDs in use:
`claude-sonnet-4-6` (Instant Report Check extraction, batch/portfolio extraction, Audit My
Report) and `claude-haiku-4-5-20251001` (Council Assessment, evidence-type debate, logframe
match, score-explanation chat). These are pinned, dated snapshots — check the current
recommended aliases before introducing a new call site.

## Testing

Four plain-`assert` golden-test files, no pytest, no network calls, no mocking framework
(API-calling functions are tested by temporarily swapping `council._call_haiku`, or
`utils.paystack.requests`/`utils.db._get_client`/`utils.auth._get_client`, for a fake):

```powershell
python test_app.py       # evaluator.py + diagnostics.py scoring behaviour
python test_council.py   # fabrication guard + logframe match
python test_metrics.py   # metrics event logging/summarization
python test_billing.py   # auth token lifecycle, metering, Paystack subscriptions/webhook sig
```

All four must pass before pushing a change that touches scoring, AI post-processing, metrics, or
billing/auth. When you intentionally change scoring behavior, re-baseline `test_app.py`'s golden
values in the same commit — a scoring change that leaves the golden values stale silently
breaks the safety net for the next change.

## Deployment

Streamlit Cloud auto-deploys `app.py` on push to `main` — but it cannot host a custom inbound
HTTP route, so the two features that need one (WhatsApp inbound messages, Paystack webhooks)
live as separate Supabase Edge Functions, deployed independently via the Supabase CLI:

```powershell
supabase functions deploy whatsapp-webhook
supabase functions deploy paystack-webhook
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

## Working conventions

- Rules are the source of truth for scores; AI narrates and interrogates around them — never
  let an AI call touch `compute_confidence`/`compute_clarity`/governance scoring/the diagnostic
  classifier/banding thresholds.
- One feature per commit, each independently revertable.
- New AI-assisted UI (buttons, expanders) must hide/disable cleanly when no API key is
  configured, leaving the manual/rule-based path fully functional.
- `_irc_widget()` (app.py) is the pattern for any field an AI feature pre-fills: write the
  plain session_state key, bump `st.session_state["_irc_fill_version"]`, then `st.rerun()`.
