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
- **`knowledge/rules/`** — Laudon Ch.11 expert-system rule base, one YAML file per criterion
  (`directness.yaml`, `verification.yaml`, etc.). Each rule carries `id`/`criterion`/
  `condition`/`confidence_effect`/`clarity_effect`/`rationale`/`source`/`version`, transcribed
  from `evaluator.get_what_to_fix()`'s live trigger conditions (kept in sync by construction —
  `test_inference.py` asserts the two agree on every golden fixture). Hot-reloadable
  (`utils/inference.py::load_rule_base()` re-reads the YAML on every call, no caching) and
  editable by a non-programmer. **Does not replace `compute_confidence()`/`compute_clarity()`**
  — those remain the tested, deterministic source of truth for the actual scores; this rule
  base only produces a firing trace (`evaluate_submission()`'s `rule_trace`/`rule_base_version`
  keys) for auditability. Conditions are evaluated by a tiny closed-form comparison parser
  (`utils/inference.py::evaluate_condition()`), never an `eval()` — a real trust boundary since
  the YAML is meant to be hand-edited by MEL specialists.
- **`knowledge/taxonomy.yaml`** (`utils/taxonomy.py`) — versioned MEL taxonomy: evaluation
  types, logframe result levels (Output/Outcome/Impact), and the real OECD-DAC criterion
  mapping (only 4 of 8 criteria — `framework_crosswalk.py` has no OECD-DAC citation for the
  other 4, and this module says so rather than force-mapping a guess). Same hot-reload
  convention as `knowledge/rules/`.
- **`knowledge/donor_questions.yaml`** (`utils/interrogator.py::select_questions()`) — Laudon
  Ch.11 Donor Interrogator: a bounded question-selection agent, not a free-generation one — it
  only ever picks or declines a pre-authored question transcribed from
  `donor_templates.DONOR_DIAGNOSTICS[donor][criterion]["low"]`, keyed to a *fired* rule from
  `utils/inference.py`'s trace. Declines gracefully (never invents filler) for an uncovered
  (donor, criterion) pair or an uncertain extracted field. Session-only — no persistence yet.
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
  (per-account CRM events + Trial/Active-Free/Professional/Agency/Churn-risk plan-tier
  segmentation for the admin dashboard — a third, deliberately separate, plaintext-account-
  identified direct-Postgres store alongside `audits.py`'s and `metrics.py`'s anonymous one;
  also carries Laudon Ch.9's *behavioural* segmentation — `build_behavioral_segments()`,
  a parallel, separate function answering "is this account actually using the product," not
  "what tier does it pay for" — plus MEL-calendar-aware churn and CLTV), `customer_profiles.py`
  (read-only accessor over the `customer_profiles` table — see below; never assembles a
  profile itself), `mel_calendar.py` (`knowledge/mel_calendar.yaml`'s hot-reloadable donor-
  reporting-season config, a labeled placeholder assumption, not researched fact),
  `api_pricing.py` (real Anthropic API token/cost logging + `knowledge/model_pricing.yaml`'s
  hot-reloadable per-model rates — also a labeled placeholder, not a verified current price
  list), `lifecycle_triggers.py` (deterministic, individually-disableable Ch.9 C6 triggers),
  `cross_sell.py` (behaviour-only Ch.9 C7 recommendation logging — never demographic).

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

## Outcome feedback loop

`utils/outcomes.py` is a *third*, distinct privacy model alongside `utils/audits.py`
(plaintext-email, row-ownership-checked) and `utils/crm.py` (plaintext-email, growth
analytics): `outcome_feedback` (`supabase/migrations/0016`) only ever stores a one-way hash
of the account email (`metrics.session_hash()`, reused directly rather than duplicated —
never the email itself), so a row can never be joined back to a real account by anyone,
including us. There is no row-ownership check against a real email here, only a hash
comparison at write time.

After a user downloads a Readiness Card (`app.py`, the `pdf_card_btn`/`html_card_btn`
buttons) or an Audit My Report Excel workbook (`smr_excel_dl`), `schedule_followup()` inserts
a `pending` row keyed to that download's reference ID, capturing `confidence_score`/
`clarity_score`/`score_band` **at export time** rather than joining back to the opt-in-only
`audits` table later — this needs to work for every download, not just the minority who
opt into saving audit history. A multi-result Excel export uses its *weakest*-scoring
result as the representative band, matching the "highest-leverage gap" framing the CSV
Portfolio heatmap already uses elsewhere. On a later visit, `_render_outcome_followup_banner()`
(called once near the top of `main()`, before the screen dispatch) shows the oldest pending
item as a dismissible banner asking whether the donor accepted it; answering or skipping both
permanently clear that item so it never reappears.

The hidden `?admin=1` dashboard's "Donor acceptance rate by score band" section
(`_render_admin_outcome_stats()`) computes the rate as `Accepted / (Accepted + Revisions
requested + Rejected)` — "Not yet submitted" responses are excluded from that denominator
entirely, since no donor decision has happened yet — and withholds a band's rate below
`MIN_BAND_SAMPLE` (10) decided responses, the same near-empty-sample safeguard as the
benchmark feature's `MIN_BENCHMARK_SAMPLE`. This table is intentionally **not** covered by
`purge_account_audit_content()`/`purge_account_crm_events()` — there's no plaintext email to
purge, and the hash alone was never reversible to an account in the first place.

## CRM behavioural segmentation & customer profiles (Laudon Ch.9)

`customer_profiles` (`supabase/migrations/0024`) consolidates every touch point this app
actually has — `crm_events`, `payments`, `wa_conversations`, `users` — into one materialized
row per account. The single assembly path is `refresh_customer_profiles()`, a Postgres
function created by that same migration, invoked hourly by the `customer-profile-refresh`
Edge Function (`supabase/functions/customer-profile-refresh/`, scheduled via `0025`, same
`pg_cron`/`pg_net` pattern as `onboarding-drip`). The Edge Function is deliberately thin — it
only checks `CRON_SECRET` and calls the RPC — so the join/aggregation logic exists in exactly
one place, not duplicated in hand-written TypeScript the way `onboarding-drip`'s HTML templates
are. `utils/customer_profiles.py` is a read-only accessor over the table; it never recomputes
anything.

`utils/crm.py::build_behavioral_segments()` buckets every profile into `trial` / `episodic` /
`embedded` / `org_emergent` / `dormant_seasonal` / `at_risk` / `lapsed`, via
`compute_behavioral_segment()` (pure function, config in `BEHAVIORAL_SEGMENT_THRESHOLDS`) —
deliberately a *separate* function from the existing plan-tier `build_segments()`
(Trial/Active-Free/Professional/Agency/Churn-risk), since the two answer genuinely different
questions and share no algorithm: plan tier is "what does this account pay for," behavioural
segment is "is this account actually using the product." `dormant_seasonal` (currently outside
an expected reporting window, but was active in this same off-season slot last cycle — an
expected, non-urgent lull) and `at_risk` (currently inside an expected reporting window and
quiet despite having history — a genuine warning) are the two easiest to conflate; see
`compute_behavioral_segment()`'s docstring for the exact disambiguation. `reporting window` is
read from `knowledge/mel_calendar.yaml`/`utils/mel_calendar.py` (hot-reloadable, same
convention as `knowledge/rules/`/`knowledge/taxonomy.yaml`) — **the configured months are a
labeled placeholder assumption, not researched fact**; adjust them to your actual customer
base. `record_segment_transition()`/`list_segment_history()` (`customer_segment_history`,
append-only) log only actual transitions, not every computation — "the transition matrix is
more informative than the snapshot."

Churn is behavioural and MEL-calendar-aware, not subscription-cancellation-based (a pay-per-use
customer who stops using never cancels anything, so billing status alone can't see it):
`compute_behavioral_churn_rate()` (currently `at_risk`/`lapsed` over the historically-active
cohort) and `compute_revenue_churn_rate()` (derived entirely from existing `payments` history —
ever had a subscription-tier payment, but the most recent successful payment is pay-per-use —
no new instrumentation needed) both withhold a rate (return `None`) below `MIN_CHURN_SAMPLE`
(10), same near-empty-sample safeguard as the benchmark/outcome-acceptance features.
`time_to_second_assessment()`/`_distribution()` (days between an account's 1st and 2nd
`audit_run` event) is the leading retention indicator called out in the Ch.9 build prompt.

A new `"revision_run"` `crm_events` type (distinct from `audit_run`) fires when a user re-scores
the same result in-session (`app.py`'s existing `_is_rescore` flag, previously used only to
skip double-charging) — the strongest signal `embedded` relies on.

`docs/crm_metrics.md` records baselines for these metrics before/as they ship, per Laudon's
§9-4 warning that enterprise applications fail when a firm can't measure whether they worked.

**C4 — CLTV.** `api_usage_log` (migration `0026`) captures real token usage/cost at all 5
Anthropic call sites (`council.py::_call_haiku()` and 4 in `app.py`) via
`utils/api_pricing.py::log_api_usage()`, priced from `knowledge/model_pricing.yaml` (labeled
placeholder rates, VERIFY against anthropic.com/pricing before relying on this financially —
`_call_haiku()`'s callers aren't email-attributed, since threading email through council.py's
whole call graph wasn't worth the diff for a metric that isn't an `ASSESSMENT_CALL_SITES`
entry anyway). `utils/crm.py::compute_cltv()` nets a real
`compute_average_cost_per_assessment()` against explicit, labeled assumptions
(`knowledge/cltv_assumptions.yaml`) — every result carries a `confidence_note` flagging
whether real cost data backs it yet. `compute_cltv_by_segment()` feeds C5.

**C5 — Admin RBAC + analytical dashboard.** `users.is_admin` (migration `0027`) is a real,
DB-backed role — `app.py::_render_admin_view()` now requires BOTH the unchanged
`ADMIN_PASSPHRASE` AND being logged in as an `is_admin = true` account
(`app._is_authorized_admin()`). Bootstrap the first admin manually:
`update users set is_admin = true where email = '...'` — there's no self-service grant UI.
`_render_admin_crm_behavioral_dashboard()` (segment distribution, transitions, churn + CLTV by
segment, revenue concentration, cost-to-serve by segment, cohort retention curves, plus C7's
cross-sell candidates list) is built directly on `customer_profiles`/`customer_segment_history`/
`payments`/`api_usage_log` — the "star schema" a future Ch.6 pass might introduce doesn't exist
yet and isn't a prerequisite.

**C6 — Lifecycle triggers.** `lifecycle_triggers_log` (migration `0028`) plus
`utils/lifecycle_triggers.py`'s `TRIGGERS` config (each individually enabled/disabled, with its
own cooldown). Four fire live from Python, checked once per page load
(`app._render_lifecycle_triggers()`, called from `main()`) against the *current* user's own
`customer_profiles` row: `first_assessment_no_engagement`, `org_emergent_detected` (also pings
the founder via `notify_founder("org_emergent_lead", ...)` — a founder-led-sales moment, not an
email sequence), `payment_recovery` (surfaces the grace period that already existed —
`invoice.payment_failed` sets `subscription_status='attention'` without revoking `is_paid`),
and `testimonial_ask` (checked separately at the revision-delta-strip call site, since it needs
the just-computed score delta). The 5th, `at_risk_reengagement`, can't fire from Python at all
— by definition the affected account isn't currently visiting — so it's the one deliberate
exception to "assembly logic lives in Python only": the `customer-profile-refresh` Edge
Function duplicates ONE narrow boolean condition (reporting month + 30+ days quiet + real
history) and sends a Resend email directly. `REPORTING_MONTHS` in that function must be kept
in sync by hand with `knowledge/mel_calendar.yaml` if it changes.

**C7 — Cross-sell logging.** `cross_sell_recommendations` (migration `0029`) +
`utils/cross_sell.py::recommend()` — behaviour-only, never demographic: `embedded` segment with
real revision activity → `upgrade_to_subscription`; `org_emergent` → `upgrade_to_org_plan`; a
systemic weak-criterion streak (reuses `utils.assessment_links.detect_systemic_gap_streak()`
from the Ch.12 work) → `training_or_template_product`, a demand signal for a not-yet-built
product. `record_outcome_for_plan_label()` is wired into both `tier_change` crm-event call
sites in `app.py`, so a real upgrade automatically resolves any matching pending
recommendation as `converted` — "log every recommendation and its outcome so the logic can be
evaluated rather than believed." Surfaced primarily as a "who to call" list on C5's dashboard,
matching the build prompt's own note that founder-led sales beats automation at this volume;
the `upgrade_to_subscription` case additionally reuses the existing `_log_upgrade_prompt_crm`
event pipeline rather than a new user-facing surface.

## Personalization layer

A lightweight profile (`account_sector`, `primary_donors`, `country`, `profile_completed_at`,
`profile_skipped` — `supabase/migrations/0017`) captured once per account via a
`_render_profile_capture_banner()` prompt (same UX pattern as the outcome-feedback banner —
DB-truth-checked each render, not a session flag, so it survives a fresh tab; Save or Skip
both permanently clear it). Nothing in the app requires it — every personalized element below
falls back to today's exact generic behavior when the profile is absent.

`account_sector` (`ACCOUNT_SECTOR_OPTIONS`: Health/Agriculture/Education/WASH/Governance/Other,
no free text) is a deliberately different, coarser taxonomy than the existing per-submission
`SECTOR_OPTIONS` (14 entries, has free-text "Other", feeds the anonymized benchmark's
bucketing) — the two serve different purposes and are kept separate on purpose. Feeds three
things: (a) `_DEMO_SCENARIOS` — the "try with a sample" picker now has 5 scenarios (one per
sector except Other), preselected from the profile via `_ACCOUNT_SECTOR_TO_DEMO_SCENARIO`, and
`primary_donors`/`_DONOR_TO_FRAMEWORK` similarly preselect `donor_selected`/`donor_framework`;
(b) `evaluator.get_what_to_fix()`'s optional `account_sector` parameter (default `""`, fully
backward compatible) swaps the illustrative evidence-type examples in the Directness/
Measurement fix messages via `_SECTOR_EVIDENCE_EXAMPLES` — not a full per-sector rewrite of
all 8 fix triggers; (c) `evaluator.summarize_monthly_trend()` — a pure function (reuses
`compute_systemic_gaps()`, no Streamlit/file I/O, directly testable) that identifies the most
frequent failing dimension in the most recent calendar month of a user's saved evaluation
history (`app.py`'s already-correctly-email-scoped `_load_trend_history()`), shown as "Your
evidence quality trends" on Screen 3. "Monthly" describes the grouping, not a push schedule —
it's computed live on every visit, not emailed.

## AI call sites and models

All Claude calls read `ANTHROPIC_API_KEY` from `st.secrets` with an `os.environ` fallback, and
every call site has a graceful rule-based/manual fallback when the key is missing or the call
fails — the app must stay fully usable offline-from-API. Current model IDs in use:
`claude-sonnet-4-6` (Instant Report Check extraction, batch/portfolio extraction, Audit My
Report) and `claude-haiku-4-5-20251001` (Council Assessment, evidence-type debate, logframe
match, score-explanation chat). These are pinned, dated snapshots — check the current
recommended aliases before introducing a new call site.

Council Assessment's synthesis call (`upgraded_result_statement`/`upgraded_evidence_statement`)
retries up to `MAX_FABRICATION_RETRIES` (2) times if `utils/fabrication_guard.check_fabrication()`
catches a fabricated numeral/date/percentage — only on an actual guard hit, not on every
request. Still dirty after the final attempt degrades to a structural suggestion (never a
fabricated rewrite, never a bare empty string) — see `utils/fabrication_guard.py`'s module
docstring.

## Data foundations & quality (Laudon Ch.6) — Phase 1 + Phase 2 shipped and LIVE

Audited the full schema (all 30 migrations, `evaluator.py`'s actual scoring output shape) and
found the data that matters most — per-criterion scores, fired rules, evidence claims,
indicators — has never been a relational entity: it lives as dict keys inside a single
encrypted blob (`audits.evaluations_json`), and only for the minority of users who opt into
saving history. Migrations `0030`–`0037` (`organisations`, `assessments`, `criterion_scores`,
`rules_fired`, `evidence_claims`, `indicators`, `documents`, `quality_audits`) normalize this.
**Applied to production 2026-08-04** (via the Supabase MCP `apply_migration` tool) — all 8
tables are live with real RLS (`app_audits_rw` bypass, default-deny for every other role).

The new tables are **hash-keyed** (`user_hash`, `metrics.session_hash()`), not email-keyed —
same pattern as `assessment_links`/`outcome_feedback`/`rule_disputes` — and populated for
*every* scored assessment, not just opted-in saves. Only scores, enums, dates, and booleans are
ever stored; free text (result statements, evidence descriptions) stays exactly where it is
today: encrypted, inside `audits`, opt-in only. This is a deliberate choice so a future data
warehouse built on these tables satisfies "no PII in the warehouse" by construction, not a later
scrubbing step. Each migration file carries a `-- DOWN` rollback block as a comment (this repo
has no down-migration tooling — migrations are numbered files pasted into the SQL editor, not
an Alembic-style framework) — run those by hand if a rollback is ever needed.

`utils/assessment_facts.py::record_assessment_facts(email, submission, ev, ref_id)` is the
write path that actually populates these tables — wired into the exact same call site as
`utils.assessment_links.record_assessment()` (`app.py::render_screen_2()`'s per-slot scoring
loop), reusing the same synthetic `_asm_id` as a soft cross-reference between the two feature's
tables. Clarity-axis criteria (Definition/Measurement/Integrity/Scope/Governance) legitimately
get a null `criterion_scores.level` — they're computed from yes/no checklist counts, not a
single 0–5 level scale the way the 3 confidence-axis criteria are. `indicators.baseline_date`/
`endline_date` are left null on every insert today — the submission dict's logframe fields are
free-text *values* ("50 households"), not dates, and there's no separate "when was this
measured" field to parse a real date from; mapping an unrelated field into a date column would
violate the no-fabrication rule, so they stay null until a real source field exists. Verified
end-to-end against an in-memory SQLite engine (`test_assessment_facts.py`); now that `0030`–
`0037` are applied, this call actually writes on every scored assessment in production, not
just the opted-in minority.

`scripts/generate_data_dictionary.py` regenerates `docs/data_dictionary.md` from a live
schema's `information_schema` introspection merged with `knowledge/
data_dictionary_annotations.yaml` (plain-English definitions, transcribed from each table's own
migration-file comment, not invented) — a table/column with no annotation entry renders as
`TODO: needs annotation`, never a guessed description. `scripts/quality_audit.py` runs 5 of
Laudon's 7 data-quality dimensions (completeness/consistency/uniqueness/validity/timeliness)
against live tables and writes findings to `quality_audits`; the remaining two (accuracy,
accessibility) are documented as not automatable — no ground truth or end-user survey exists to
check against — rather than silently skipped. **Both scripts require a real Postgres
connection** (`SUPABASE_DB_URL`) — `information_schema` doesn't exist in SQLite, so neither can
run against this repo's usual in-memory test fixtures; their internal logic (rendering,
`Finding` construction) was smoke-tested with fake data instead, not run against a live schema.

**Phase 2 (C4–C8), also shipped and live, 2026-08-04:**
- **C8** (`evaluator.check_data_quality_flags()`) — cleansing-on-ingest, flag-never-correct:
  baseline≡achievement duplicates, evidence descriptions that mirror the result statement,
  10x+ target/achievement magnitude mismatches. Purely additive to `evaluate_submission()`'s
  return dict; never touches `confidence_score`/`clarity_score`.
- **C6** (`evaluator.detect_hedge_language()`) — deterministic epistemic-hedge-phrase detection
  ("may have," "it is believed," "arguably," …) in the result/evidence text, count-based risk
  banding. Distinct from Directness/Measurement's existing checks: this flags *how* confidently
  something was stated, not *what* was claimed.
- **C4** (migration `0055`: `dim_donor`/`dim_sector`/`dim_org_type`/`dim_date`/`fact_assessment`)
  — a Kimball star schema on top of `assessments`/`criterion_scores`, populated by
  `scripts/populate_warehouse.py` (idempotent, get-or-create dimensions, one fact row per
  assessment with a derived criteria pass/fail count). Applied to production alongside
  `0030`-`0037`. Unlike `quality_audit.py`/`generate_data_dictionary.py`, this script does plain
  inserts, not `information_schema` introspection, so `test_populate_warehouse.py` runs it
  against real in-memory SQLite, not just smoke-tests it.
- **C5** (`utils/warehouse.py::slice_by()`) — read-only OLAP slice/dice over `fact_assessment`,
  grouped by donor/sector/org_type/quarter, buckets below `MIN_SLICE_SAMPLE` (10) withheld (same
  near-empty-sample convention as the benchmark feature). Surfaced as a new panel on the Agency
  Dashboard's DSS tab, clearly distinct from that tab's existing per-account criterion × client
  pivot (Ch.12) — this one draws from every scored assessment across all accounts.
- **C7, register half** (`utils/indicator_stewardship.py::find_indicator_inconsistencies()`) —
  flags an account's own indicator names reused across assessments with a different recorded
  target/baseline, scoped by `user_hash` so accounts never see each other's indicator usage.
  Surfaced on Screen 3's Trends section.
- **C7, policy-generator half** (`utils/policy_generator.py::generate_information_policy_draft()`)
  — a pure, template-filled Markdown draft of a data/information policy for the *customer's own*
  organisation (distinct from `docs/privacy_notice.md`/`docs/compliance/*.md`, which describe
  ImpactProof's own practices). Never LLM-generated: every slot is filled only from the account's
  personalization profile (`account_sector`/`primary_donors`/`country`); anything unsupplied
  renders as an explicit `[Add: ...]` placeholder, never a guessed value. Download button next to
  the stewardship register on Screen 3.

This closes out Ch.6 in full — both phases shipped, tested, and live.

## Ethics framework (Laudon Ch.4)

`docs/ethics_framework.md` maps Laudon's five moral dimensions of information systems
(information rights, property rights, accountability/liability/control, system quality,
quality of life) onto controls already built for other reasons across the Ch.6/Ch.8/Ch.11/
Ch.12 passes — the fabrication guard, the compliance hard-gate, the org-type-aware
thresholds, RLS/encryption, `quality_audit.py` — rather than introducing new mechanisms.
Documentation only, no code changes: the audit's finding was that the underlying controls
mostly already existed, scattered, and what was missing was the connecting document, not the
mechanism. Includes a worked 5-step ethical analysis (Laudon's own process) of the org-type
threshold design as a concrete example, and names four honest open gaps rather than claiming
completeness. `docs/responsible_ai_statement.md` is the shorter, customer/investor-facing
distillation of the same material for pitch use.

## Revenue model & unit economics (Laudon Ch.10, §10-1/§10-2)

ImpactProof runs freemium (3 free checks) + transaction-fee (GHS 5/use) + subscription
(GHS 50/mo Professional, GHS 200/mo Agency) simultaneously — a combination Laudon's Ch.10
digital-goods framing (marginal cost ≈ 0) explicitly warns against, since every AI-assisted
assessment costs real Anthropic API money. **C1** extends `utils/api_pricing.py` (the Ch.9
CLTV pass's real per-call cost logging) with `compute_p95_cost_per_assessment()`,
`compute_cost_by_document_length_bucket()`, and `compute_subscription_breakeven_assessments()`
— no schema change; the two call sites that already gate a scored assessment
(`irc_extraction`/`batch_extraction`) already satisfy "measured and stored, not estimated."
`docs/unit_economics.md` documents the real (n=6 as of 2026-08-04, explicitly flagged as too
small to price on) numbers this produces, and what's deliberately *not* measured (a literal
`assessment_id`-linked cost table, wall-clock duration, storage/compute overhead) and why.

**C2/C6** (`scripts/pricing_model.py`) is a scenario-comparison script, never a UI, and never
touches a live price constant or Paystack Plan object — compares the current split against a
subscription+fair-use-cap+overage model, credit packs, and a limited free tier (both a
cached-demo and a live-scored variant), reading real cost from C1's functions (falling back
to a clearly-labeled SYNTHETIC EXAMPLE distribution otherwise) and pricing *assumptions* (not
live prices) from `knowledge/cltv_assumptions.yaml`. C6 adds differential/concessional
pricing by organisational capacity plus an explicit `check_cannibalization()` — which
correctly flags that a naive CBO/Government discount undercuts Agency pricing per-assessment,
meaning any real concessional tier needs a real eligibility check, not a self-reported
dropdown.

**C3**: `check_access()` gained `ai_features_allowed` (paid-only), splitting it from the
existing free-checks-based `allowed`. Council Assessment and Score Chat were previously
gated on the same free-checks counter as basic scoring — meaning a free-tier account with
checks remaining could run genuinely AI-powered (real marginal cost) features, contradicting
the product's own "3 free checks" framing. Core scoring (`evaluator.py`, zero marginal cost
by construction) stays on the unchanged `allowed` gate and remains unlimited.

**C4**: `utils/paystack.py` now sends Paystack's `channels` param, mobile-money-first
(`["mobile_money", "card", "bank", "ussd"]`) — previously unset entirely, meaning channel
ordering was 100% merchant-dashboard-controlled despite mobile money being the dominant rail
in Ghana. `utils/receipts.py::build_receipt_html()` gives the billing page's previously-bare
payment-history dataframe a real downloadable receipt (PDF via the existing
`_html_to_pdf_bytes()`, HTML fallback) — something an M&E officer can attach to a donor grant
line, which didn't exist before. Live mobile-money channel *availability* per network and
end-to-end failed-payment UX aren't verifiable without a live Paystack test account — flagged
as a manual post-merge check, not code.

**C5**: `utils/account_export.py::build_account_export()` — a full JSON export (audits with
full decrypted content, Logframe Library + items, clients, payment history), composed
entirely from existing ownership-checked read functions, mirroring
`purge_account_audit_content()`'s scope plus payment history. Surfaced on My Audits right
before the Danger Zone. No live Paystack account or price change involved anywhere in this
arc — same explicit boundary as the original Ch.10 brief: this pass produces numbers and
tooling, not a pricing decision.

## Impact-Linked Readiness Module

`utils/impact_linked_readiness.py` — a distinct product surface from the rest of the app:
whether ONE contractual indicator (the kind impact-linked loans/SIINC deals condition
financial terms on, e.g. "3,000 farmers onboarded, verified") is defensible enough to put
real money on, not whether a donor report reads well. Higher stakes than donor reporting —
money consequences, not reputation — so the assurance bar is "agreed-upon procedures against
pre-defined criteria," not a quality score; deliberately fully deterministic, no AI/LLM call
anywhere in this module, since AI-judgment scoring would be unacceptable in a financially
contractual context. Never invoked inside `evaluate_submission()` and never reads/returns
`confidence_score`/`clarity_score` — a structurally separate module, not an extension of the
donor-report scoring engine, run only on-click via a new expander on Screen 2's existing
per-indicator report card ("🏦 Check funder-readiness for this indicator").

Three checks, all reusing existing per-indicator data (no new UI fields, no migration):
**`check_indicator_contractibility()`** flags ambiguous/absent units, no disaggregation rule,
no confirmed collection tool/method, and a target with no baseline — reusing
`_extract_leading_number`-style unit detection, the existing `disaggregation_status` dropdown,
and the `provenance_checklist.collection_tool_named` answer already collected on Screen 1.
**`trace_evidence_chain()`** is a structured 5-link trace (definition → collection instrument
→ sampling approach → raw records → aggregation method) built from the SAME
`provenance_checklist` dict `get_provenance_adjustment()` already reads — `aggregation_method`
is *always* `present: False`, an honest MVP gap (no field anywhere captures it) rather than a
guess, matching the same "ship the gap, don't fabricate a value" convention as
`indicators.baseline_date`/`endline_date` shipping always-null. **`assess_verification_readiness()`**
reuses the `auditor_traceable` checklist answer, explicitly labeled `"signal": "self_declared"`
— a policy invariant asserted directly in tests — since no custody-location/collector-identity/
retention-duration schema exists to check independently.

`generate_readiness_certificate()` assembles all three into red/amber/green traffic lights
(deliberately not numeric, to avoid false comparability with the 0-5 confidence/clarity axes),
a flattened named-gaps list, and a disclaimer ("pre-verification diagnostic, not a
verified-impact claim, not independent assurance") — ImpactProof is explicitly not positioned
as the independent verifier itself (that needs a human with liability); this is the diagnostic
layer that makes that human review cheaper. Deliberately not built this pass: any new schema
for custody/collector/retention tracking, a new UI field for aggregation method, baseline-
integrity (timing/collector of the baseline itself) and target-plausibility checks, or a
standalone/exportable certificate artifact — inline-on-Screen-2 was the user-confirmed v1
scope. Planned via the full Explore→Plan→Review plan-mode workflow (2 parallel Explore agents
audited existing indicator/logframe-scoring and audit-trail/consent infrastructure, 1 Plan
agent designed the implementation, 2 product judgment calls put back to the user via
AskUserQuestion before finalizing) — the originating "mostly reconfiguration" premise from the
strategy discussion that proposed this feature turned out directionally right but optimistic;
real new logic was needed, though no per-report→per-indicator refactor was, since a
`submission` dict already models exactly one indicator.

## Strategic positioning (Laudon Ch.3)

`docs/strategy/` — seven documents (`five_forces.md`, `competitive_strategy.md`,
`value_chain.md`, `network_effects.md`, `ecosystem_map.md`, `resistance_analysis.md`,
`pitch_spine.md`), prepared for the Execute Africa AI Challenge pitch (ALX Tech Hub Accra,
September 2026) and impact-linked finance conversations. Documentation only, no code — the
last item on the Laudon prompt-pack roadmap. Grounded in three parallel Explore-agent research
passes against the live codebase and one live Supabase query (4 production accounts as of
2026-08-04/05), not generic startup-strategy prose; every claim is tagged Confirmed/
Assumption/Research-needed and cross-referenced across documents so the pack reads as one
argument rather than seven independent essays.

Reuses real, already-shipped internal language rather than inventing new positioning: the
**DRCA** framework (Deterministic/Reproducible/Comparable/Auditable) from `council.py`'s
admin-only `debate_competitive_position()` tool becomes the differentiation argument in
`competitive_strategy.md`; the org-type thresholds' real calibration to STAR-Ghana and
District Assembly grants (`evaluator.py`, the Fairness expander) becomes the concrete
Ghana-specificity evidence in the same document and in `pitch_spine.md`.

Required "uncomfortable findings" are each owned by exactly one document, not scattered or
duplicated: `five_forces.md` names the direct-LLM substitute as the sharpest competitive
threat and answers it on technical merit (the fabrication guard, `evaluator.py`'s
zero-API-call determinism) rather than dismissing it; `competitive_strategy.md` states
low-cost leadership is not available; `value_chain.md` confirms ImpactProof sits at
reporting — the latest, weakest intervention point — with the Impact-Linked Readiness Module
named as a real but only partial upstream exception; `network_effects.md` states plainly that
real usage volume (6 logged API-cost events, every one of the codebase's own `MIN_*_SAMPLE=10`
gates) is too sparse for any network-effect claim to be more than "correctly built, not yet
proven"; `ecosystem_map.md` states no relationship exists with any named donor or
impact-linked-finance organisation, and names the validator relationship as the single most
consequential open item; `resistance_analysis.md` states its own gain-not-loss reframe is a
design intention read from the architecture, not validated user feedback. `pitch_spine.md`
compresses all six into a five-slide, ~770-word argument that introduces zero new facts.

## Testing

Twenty-three plain-`assert` golden-test files, no pytest, no network calls, no mocking framework
(API-calling functions are tested by temporarily swapping `council._call_haiku`, or
`utils.paystack.requests`/`utils.db._get_client`/`utils.auth._get_client`, for a fake;
`test_audits.py`/`test_crm.py`/`test_outcomes.py`/`test_verification.py`/
`test_assessment_links.py`/`test_rule_disputes.py`/`test_customer_profiles.py` swap
`utils.audits._get_engine`/`utils.crm._get_engine`/`utils.outcomes._get_engine`/
`utils.verification._get_engine`/`utils.assessment_links._get_engine`/
`utils.rule_disputes._get_engine`/`utils.customer_profiles._get_engine` for an in-memory
SQLite engine instead, since the same
SQLAlchemy models work unchanged against either dialect — note SQLite doesn't enforce foreign
keys by default unlike Postgres, so that fixture explicitly enables `PRAGMA foreign_keys=ON`
to exercise cascade-delete behavior correctly; `test_i18n.py` swaps
`utils.exchange_rates._fetch_rates_from_api_uncached`/`utils.geoip._visitor_ip` for fakes;
`test_security.py` imports `app.py` itself in Streamlit's "bare mode," where `st.session_state`
still behaves as a plain dict within one process):

```powershell
python test_app.py              # evaluator.py + diagnostics.py scoring behaviour
python test_council.py          # fabrication guard + logframe match
python test_metrics.py          # metrics event logging/summarization
python test_billing.py          # auth token lifecycle, metering, Paystack subscriptions/webhook sig;
                                 # Ch.10 C3: ai_features_allowed paid-only gate; Ch.10 C4: mobile-money-
                                 # first channel ordering
python test_audits.py           # saved audits, logframe library, benchmark, access log, encryption, deletion
python test_crm.py              # crm events, agency-ready detection, account segmentation, purge;
                                 # Ch.9 behavioural segmentation (all 7 segments), MEL-calendar-aware
                                 # churn (behavioural + revenue), time-to-second-assessment
python test_outcomes.py         # outcome feedback scheduling, hash-based ownership, acceptance-rate stats
python test_verification.py     # export reference-ID hashing, recording, and ?verify= lookup
python test_assessment_links.py # Ch.12 revision-linking: record/list/delta, hash isolation, no-DB degradation
python test_inference.py        # Ch.11 expert-system rule base: YAML loads, condition parser, firing-trace
                                 # agreement with get_what_to_fix(), deterministic wiring, graceful degradation
python test_extraction_schema.py # Ch.11 extraction schema validation + per-field uncertainty flagging
python test_fabrication_guard.py # Ch.11 red-team fixtures + council.py's retry-then-degrade flow
python test_rule_disputes.py    # Ch.11 dispute logging: record/count round-trip, hash isolation, no-DB degradation
python test_taxonomy.py         # Ch.11 MEL taxonomy: knowledge/taxonomy.yaml loads, OECD-DAC criterion mapping,
                                 # graceful degradation on a missing file
python test_interrogator.py     # Ch.11 Donor Interrogator: question selection over
                                 # knowledge/donor_questions.yaml, graceful decline for uncovered pairs and
                                 # uncertain fields, never raises on an unknown donor
python test_customer_profiles.py # Ch.9 CRM: customer_profiles read path (get/list), no-engine
                                 # degradation -- refresh_customer_profiles() itself is a Postgres-only
                                 # SQL function, not exercised by this offline suite
python test_mel_calendar.py     # Ch.9 CRM: knowledge/mel_calendar.yaml loads, reporting-month check,
                                 # graceful degradation on a missing file
python test_api_pricing.py      # Ch.9 CRM (C4): model_pricing.yaml loads, per-model cost computation,
                                 # assessment-only usage averaging for CLTV's cost floor; Ch.10 C1: p95,
                                 # cost-by-document-length bucketing, subscription break-even
python test_lifecycle_triggers.py # Ch.9 CRM (C6): trigger eligibility conditions, cooldown/dedup,
                                 # individually-disableable triggers, fail-open no-engine degradation
python test_cross_sell.py       # Ch.9 CRM (C7): behaviour-only recommendation selection, dedup,
                                 # outcome/conversion tracking
python test_assessment_facts.py # Ch.6 C1 write path: assessments/criterion_scores/rules_fired/
                                 # evidence_claims/indicators content, no free-text columns,
                                 # date parsing, no-op degradation with no engine/empty email
python test_populate_warehouse.py # Ch.6 Phase 2 C4: star-schema ETL -- fact row content, get-or-create
                                 # dimensions, idempotent re-runs, null-degradation on missing fields
python test_warehouse.py        # Ch.6 Phase 2 C5: OLAP slice_by() aggregates, MIN_SLICE_SAMPLE gate,
                                 # graceful degradation with no engine/missing tables
python test_indicator_stewardship.py # Ch.6 Phase 2 C7 (register): inconsistent target/baseline
                                 # detection, single-use exemption, per-account hash isolation
python test_policy_generator.py # Ch.6 Phase 2 C7 (policy): known fields fill correctly, unknown
                                 # fields always placeholder (never fabricate), disclaimer always present
python test_pricing_model.py    # Ch.10 C2/C6: scenario math (current split, fair-use cap,
                                 # credit packs, limited free tier), concessional-tier
                                 # cannibalization detection, synthetic-fallback and main() smoke test
python test_receipts.py         # Ch.10 C4: receipt HTML renders all fields, non-success status
                                 # class, missing-field placeholders, no external assets
python test_account_export.py   # Ch.10 C5: full bundle composition, empty-account degradation,
                                 # cross-account isolation, no-engine degradation
python test_impact_linked_readiness.py # Impact-Linked Readiness Module: contractibility flags,
                                 # 5-link evidence chain (aggregation_method always missing by
                                 # design), self-declared verification signal, certificate never
                                 # touches confidence_score/clarity_score
python test_i18n.py             # currency conversion, geoIP routing, ROI copy, Paystack checkout routing
python test_security.py         # app.py-level regression tests (user_email overwrite guard, portfolio
                                 # heatmap sample gate, Readiness Card crosswalk tags, verify landing page,
                                 # Agency Dashboard MIS/DSS/ESS views, Ch.9 C5 admin RBAC gate + the
                                 # behavioural CRM dashboard's render-without-raising)
```

All must pass before pushing a change that touches scoring, AI post-processing, metrics,
billing/auth, or audit persistence. When you intentionally change scoring behavior, re-baseline
`test_app.py`'s golden values in the same commit — a scoring change that leaves the golden values
stale silently breaks the safety net for the next change.

## Deployment

Streamlit Cloud auto-deploys `app.py` on push to `main` — but it cannot host a custom inbound
HTTP route or a background/scheduled job, so four features live as separate Supabase Edge
Functions, deployed independently via the Supabase CLI: two inbound webhooks (WhatsApp, Paystack)
and two `pg_cron`-scheduled functions (the onboarding email drip; the Ch.9 CRM customer-profile
refresh, which also sends the `at_risk_reengagement` lifecycle trigger's email):

```powershell
supabase functions deploy whatsapp-webhook
supabase functions deploy paystack-webhook
supabase functions deploy onboarding-drip
supabase functions deploy customer-profile-refresh
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

### Dependency pinning: `requirements.txt` vs `requirements-lock.txt`

Two files, two jobs. `requirements.txt` is hand-maintained — the direct packages this app
actually imports, exact-pinned with a rationale comment per package (Laudon Ch.8, C7).
`requirements-lock.txt` is machine-generated — the full transitive closure (every package
`requirements.txt`'s own dependencies pull in, pinned too), frozen from a real,
verified-working install rather than typed by hand. **Docker (`Dockerfile`) and CI
(`.github/workflows/ci.yml`) install from `requirements-lock.txt`, not `requirements.txt`** —
that's the one that actually makes a build reproducible.

This distinction exists because of a real production outage (2026-08-05): `requirements.txt`
pinned `streamlit==1.58.0` exactly, but Streamlit's own declared dependency on `starlette` is
only floor-pinned upstream (`>=0.40.0`, no ceiling) — so even with every line in
`requirements.txt` exact, a fresh `pip install` could still silently resolve a new,
incompatible major version of a *transitive* package. That's exactly what happened on a cold
Docker rebuild (triggered by an unrelated upstream base-image digest change, which invalidated
the cached `pip install` layer): `pip` picked up starlette's new `1.x` line, which added a
required constructor argument to an internal class Streamlit's own vendored gzip middleware
calls without it — crashing every single request. Fixed short-term by pinning
`starlette==0.52.1` directly; fixed structurally by adding `requirements-lock.txt` so this
entire class of drift (any unlisted transitive dependency, not just starlette) can't recur.

To regenerate after changing `requirements.txt`: install into an environment that matches
production — the droplet itself (`docker compose exec app pip freeze`) or a container built
from this repo's own `Dockerfile`, **not** a bare local venv, which can resolve different
platform-specific wheels than the Linux container actually runs — then replace
`requirements-lock.txt`'s contents with that freeze output. Full test suite must still pass
against the regenerated lock file before committing.

## Working conventions

- Rules are the source of truth for scores; AI narrates and interrogates around them — never
  let an AI call touch `compute_confidence`/`compute_clarity`/governance scoring/the diagnostic
  classifier/banding thresholds.
- One feature per commit, each independently revertable.
- New AI-assisted UI (buttons, expanders) must hide/disable cleanly when no API key is
  configured, leaving the manual/rule-based path fully functional.
- `_irc_widget()` (app.py) is the pattern for any field an AI feature pre-fills: write the
  plain session_state key, bump `st.session_state["_irc_fill_version"]`, then `st.rerun()`.
