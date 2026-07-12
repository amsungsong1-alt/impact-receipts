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
- **`utils/`** — `db.py` (Supabase user/draft/example persistence), `paystack.py` (payments),
  `whatsapp.py` (WhatsApp Cloud API notifications/deep-links), `email_otp.py`, `anonymize.py`.

## AI call sites and models

All Claude calls read `ANTHROPIC_API_KEY` from `st.secrets` with an `os.environ` fallback, and
every call site has a graceful rule-based/manual fallback when the key is missing or the call
fails — the app must stay fully usable offline-from-API. Current model IDs in use:
`claude-sonnet-4-6` (Instant Report Check extraction, batch/portfolio extraction, Audit My
Report) and `claude-haiku-4-5-20251001` (Council Assessment, evidence-type debate, logframe
match, score-explanation chat). These are pinned, dated snapshots — check the current
recommended aliases before introducing a new call site.

## Testing

Three plain-`assert` golden-test files, no pytest, no network calls, no mocking framework
(API-calling functions are tested by temporarily swapping `council._call_haiku` for a fake):

```powershell
python test_app.py       # evaluator.py + diagnostics.py scoring behaviour
python test_council.py   # fabrication guard + logframe match
python test_metrics.py   # metrics event logging/summarization
```

All three must pass before pushing a change that touches scoring, AI post-processing, or
metrics. When you intentionally change scoring behavior, re-baseline `test_app.py`'s golden
values in the same commit — a scoring change that leaves the golden values stale silently
breaks the safety net for the next change.

## Working conventions

- Rules are the source of truth for scores; AI narrates and interrogates around them — never
  let an AI call touch `compute_confidence`/`compute_clarity`/governance scoring/the diagnostic
  classifier/banding thresholds.
- One feature per commit, each independently revertable.
- New AI-assisted UI (buttons, expanders) must hide/disable cleanly when no API key is
  configured, leaving the manual/rule-based path fully functional.
- `_irc_widget()` (app.py) is the pattern for any field an AI feature pre-fills: write the
  plain session_state key, bump `st.session_state["_irc_fill_version"]`, then `st.rerun()`.
