# Pitch Spine — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Five slides, two pages. Every claim below traces to
`five_forces.md` / `competitive_strategy.md` / `value_chain.md` / `network_effects.md` /
`ecosystem_map.md` / `resistance_analysis.md` — no new facts are introduced here. "(assumption)"
marks a stated position not yet validated; everything else is confirmed from the codebase or a
live query this session.*

## Slide 1 — The problem

Donor-report evidence quality is judged too late and too inconsistently to matter.

- ImpactProof inserts at **reporting** — the latest, weakest point of intervention in the
  donor-programme lifecycle (proposal → design → implementation → monitoring → evaluation →
  reporting → renewal). By the time the tool runs, the decisions that determine whether good
  evidence exists have already been made, for better or worse. *[value_chain.md]*
- The sharper form of the question a technical judge asks first — "why does this need to
  exist at all" — is that the real substitute isn't a competing product. It's a general-
  purpose LLM the M&E officer already has open in another tab. *[five_forces.md]*

## Slide 2 — Why now

Impact-linked finance is starting to condition real money on verified outcomes, and no
validator relationship yet exists to make a self-reported score trustworthy to that money.

- The single highest-value, least-built relationship: a donor or impact-linked funder whose
  reliance on an ImpactProof score converts it from self-reported to third-party-recognized.
  This does not exist yet — named here as the opportunity, not a partnership in progress.
  *[ecosystem_map.md]*
- Honest traction, stated plainly rather than implied: 6 logged real API-cost events and 4
  production accounts as of early August 2026 *(the account figure is session-sourced from a
  live database query, not a code artifact)*. This reads as "early, correctly built, provably
  real" — not scale. *[network_effects.md]*

## Slide 3 — Why this architecture

A deterministic score plus a code-level fabrication guard is the thing a raw LLM session
structurally cannot offer.

- `evaluator.py`: *"Fully deterministic — same inputs always produce the same outputs. No API
  calls."* Zero Anthropic imports in the scoring engine, confirmed by direct read.
- `utils/fabrication_guard.py::check_fabrication()` cross-checks every numeral in an AI draft
  against the user's own raw submission fields; anything unverifiable is withheld, not shown.
- Framed against the product's own internal positioning tool (`council.py`'s
  `debate_competitive_position()`): **DRCA** — Deterministic, Reproducible, Comparable,
  Auditable. This is shipped internal language, not pitch-deck invention. *[competitive_strategy.md]*
- This is the direct answer to Slide 1's substitute question: reproducibility and a structural
  refusal to fabricate are not things a bare LLM chat can match, regardless of which model
  it runs on.

## Slide 4 — Why this team, in this market

Ghana-specific calibration is real and load-bearing, not decorative.

- Org-type-aware thresholds (CBO/Government 3.5, National NGO 3.75, INGO 4.0) are *presented
  to users* as calibrated to named, real funding mechanisms: the INGO track to
  USAID/FCDO/GIZ/Mastercard Foundation; the community/national track to **STAR-Ghana and
  District Assembly grants** — a real Ghana civil-society funder and Ghana's actual
  local-government funding structure. The design intent is real and disclosed to users; the
  specific 3.5/3.75/4.0 numbers themselves are not traced to a source document from either
  program — **Assumption, not Confirmed** (see `five_forces.md`), on par with the rest of this
  calibration work rather than a specially-verified exception to it.
  *[competitive_strategy.md / value_chain.md]*
- Stated honestly, not omitted: the product itself discloses that the lower-threshold track
  still structurally favors organisations with formal documentation capacity — an equity
  design, not a perfectly equitable one. *[competitive_strategy.md]*
- Mobile-money-first payment ordering and Ghana Act 843 compliance mapping are additional real,
  shipped, country-specific product decisions — not aspirational roadmap items.

## Slide 5 — What unfair advantage compounds

Two real, data-owned network-effect mechanisms already exist, even though volume is thin — and
the moat is getting a validator to recognize one of them before a competitor builds the same
funder-calibration relationships.

- **Live today:** the anonymized benchmark (bucketed by donor/sector/org-type, auto-improves
  with every new saved audit above a 10-sample floor) and the `?verify=<ref_id>` mechanism
  (SHA-256-hashed, timestamped, checkable by anyone including a donor). Labeled honestly:
  *mechanism real, adoption not yet formed* — no scale is implied here. *[network_effects.md]*
- **The actual moat candidate:** funder-specific calibration (donor citations, Ghana funding-
  mechanism thresholds) is slow to replicate and requires domain access most software teams
  don't have — real but untested as a durable barrier *(assumption)*. Whichever team gets a
  validator to recognize their score first converts that head start into something much harder
  to copy. *[five_forces.md / ecosystem_map.md]*

---

*What this pitch deliberately does not claim: proven adoption psychology
(`resistance_analysis.md` — the "officer/manager/consultant gain, not lose" reframe is a
design intention, not validated user feedback), a named competitor landscape (none identified
in this research), or any existing relationship with Roots of Impact, iGravity, Swiss SDC, or
any named donor. These are the open items this pack recommends pursuing next, not gaps to
paper over on stage.*
