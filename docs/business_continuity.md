# ImpactProof Business Continuity Plan

*Last reviewed: 2026-08-03. BC = keeping the business (a customer able to
get a usable assessment) running, distinct from DR (getting the systems
back) — see `docs/disaster_recovery.md`. A customer doesn't care whether
Supabase is technically "up" if they can't finish their assessment.*

## What happens to a customer mid-assessment

**If their browser tab or session drops:** Streamlit's own session-state
draft-restore mechanism (already present in `app.py`, referenced by
`test_security.py`'s session-restore checks) keeps an in-progress,
not-yet-submitted draft recoverable when they return — this is not new
work for this hardening pass, it already exists and already gets exercised
by the existing test suite. No customer-visible change from this document.

**If the Anthropic API is unreachable (the AI narrative feature is down):**
This is the concrete resilience argument for keeping the deterministic
rule engine and the AI narrative layer architecturally separate (the
"hybrid architecture," `evaluator.py` vs. `council.py`) — confirmed during
this hardening pass, not newly built:

- `evaluator.py` has zero network dependency (`import re` and
  `from datetime import datetime` are its only imports) and computes the
  full Confidence/Clarity score, "what to fix" guidance, and every
  deterministic output from the submission alone. This runs identically
  whether Anthropic's API is up, down, or has never existed.
- `council.py`'s optional AI narrative layer (persona verdicts, the
  "upgraded" rewritten evidence statement, the plain-English brief) is
  invoked at exactly one UI call site, gated behind a paid plan and an
  explicit button click — never automatically, never blocking the
  deterministic score above it.
- On an API failure, `council._call_haiku()` catches every exception and
  returns a `"[Council member unavailable: ...]"` sentinel per member
  rather than raising; `run_council_assessment()` always returns a
  well-formed result dict with an `"error"` field summarizing which
  members failed, never raises itself.
- The UI (`app.py`, the caption right after the council-assessment render
  call) shows: *"Note: some council members were unavailable (...)."* —
  this is the "UI says why the AI narrative is missing" acceptance
  criterion, and it was already true before this hardening pass. This
  document exists to confirm and record that fact, not to build it.

**Net effect:** a customer whose assessment happens to coincide with an
Anthropic outage still gets their full deterministic score, their "what to
fix" guidance, and can still save/export/download it — the only thing
missing is the optional AI-written narrative gloss on top, clearly labeled
as unavailable rather than silently absent or (worse) silently wrong.

## If Supabase itself is degraded (not fully down, but slow/erroring)

Every rate-limit check and access-log write in this codebase already fails
in a deliberately chosen direction per call site (see
`docs/security_policy.md`'s implementation-controls section and this
hardening pass's own fail-open/fail-closed split): ordinary features
(saving an audit, viewing history) fail open so a DB hiccup doesn't block a
customer from finishing their work; cost-bearing and authentication-guarding
checks (upload/extraction rate limits, OTP/admin-passphrase lockouts) fail
closed, so the same hiccup can't be used to bypass them. A customer's
in-progress, unsaved work in `st.session_state` is unaffected either way —
only the "save to my account" step would be delayed/retried.

## If Streamlit Cloud itself is down

See `docs/disaster_recovery.md`'s fallback section — the VPS/Docker path
exists for this, but isn't running by default. From a business-continuity
angle: during that window, no customer can use ImpactProof at all (there is
currently no secondary always-on hosting target) — this is an accepted gap
for a solo-founder operation, not a hidden one. If/when ImpactProof reaches
a scale where this gap is unacceptable, the next investment is keeping the
VPS fallback warm and DNS-failover-ready rather than provisioned on demand.

## Manual/degraded-mode paths, summarized

| Failure | Customer-facing impact | Automatic or manual? |
|---|---|---|
| Anthropic API down | AI narrative unavailable, clearly labeled; score unaffected | Automatic (already built) |
| Supabase slow/erroring | Ordinary features degrade gracefully; auth/cost guards fail closed | Automatic (already built) |
| Streamlit Cloud fully down | No access to ImpactProof at all | Manual — VPS fallback must be activated (`docs/disaster_recovery.md`) |
| Database data loss | Depends entirely on backup/PITR status | Manual — see the open item in `docs/disaster_recovery.md` |
