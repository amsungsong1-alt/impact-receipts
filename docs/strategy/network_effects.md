# Network Effects — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Evidence status: **Confirmed** / **Assumption** / **Research
needed**, as in `five_forces.md`.*

## What counts as a real network effect here

Network economics, precisely: the marginal cost of adding one more participant approaches
zero, while the marginal value the *existing* participants get from that addition is larger
than zero — value grows with membership, not just revenue. Each candidate below is tested
against that definition rather than assumed to qualify because it sounds like one.

## Live and real today: the benchmark ("How you compare")

**Confirmed.** `utils/audits.py`'s anonymized benchmark buckets every opted-in saved audit by
exactly `(donor, sector, org_type)`. `MIN_BENCHMARK_SAMPLE = 10` — below 10 saved audits in a
given bucket, nothing is shown; `get_benchmark()` returns `None` rather than a percentile from
a near-empty sample. Every bucket auto-recomputes on every new save, with zero human
intervention.

This genuinely is a network effect by the definition above: one more organisation in Ghana's
`(USAID, Health, National NGO)` bucket, say, saving an audit, makes the percentile comparison
every *other* organisation in that same bucket sees measurably better, for free, without
ImpactProof doing anything.

**The real caveat:** it's bucketed, not global. Value only accrues to a user who happens to
land in a bucket that other users have also populated. Given the traction numbers below, it is
very likely that most buckets today are still below the 10-sample floor and are therefore
showing nothing to anyone. This is a real, live mechanism that is currently thin, not absent.

## Half-built: the rule base improving through disputes

**Confirmed, and deliberately not oversold.** `utils/rule_disputes.py`'s own module docstring
states the design choice directly: *"this module never auto-tunes or auto-disables a rule from
dispute volume — codified judgement stays human-owned."* What is live: every dispute is logged
(`record_dispute()`) and surfaced as a per-rule count ranking on the hidden admin view
(`get_dispute_counts()`). What is **not** live: nothing in this module reads or writes
`knowledge/rules/*.yaml`. A human — a MEL specialist — has to look at the ranking and hand-edit
the rule base for any actual improvement to happen.

So "the rule base improves through disputes" is accurate only as "the *signal to improve it*
is collected automatically" — the improvement loop itself is not closed, and calling it a
network effect today would overstate what's built. It's a real candidate for one, pending a
process (not a code) change: someone has to actually act on the dispute rankings on a
schedule.

## Real mechanism, demand-side unformed: donor verification

**Confirmed as a technical capability; unconfirmed as an actual network effect.** Every export
(Readiness Card, Audit My Report Excel, Framework Crosswalk, Portfolio Report) prints a
`Ref: IMP-...` style ID. `utils/verification.py`'s `record_export()` writes a SHA-256 content
hash and timestamp against that ID at export time; the live `?verify=<ref_id>` landing page
(`app.py`) lets **anyone** — including a donor who received the report — confirm that a given
score/band was genuinely produced by ImpactProof at a given time. This is real, shipped, and
checkable today, not a mockup.

This is the network effect the original strategy brief names as "the one that would actually
be defensible, and the hardest to get" — and the reason is visible in the mechanics
themselves: the value of this feature to any single user depends entirely on *donors actually
forming the habit of checking it*. Right now, nothing in the codebase or this research
indicates any donor has ever used the `?verify=` link. The technical foundation is real; the
demand-side network effect has not formed. **Research needed:** whether any donor has ever
actually followed a verification link in practice.

## Why current volume caps every one of these claims

Stated once here, plainly, as the canonical numbers this pack should cite consistently rather
than re-deriving elsewhere:

- **6** real logged API-cost events total in production (`api_usage_log`, per
  `docs/unit_economics.md`, dated 2026-08-04) — that document's own words: *"6 data points is
  not a decision-grade sample."*
- Every volume-gated feature in the codebase sits at or under its own statistical-significance
  gate: `MIN_BENCHMARK_SAMPLE = 10`, `MIN_CHURN_SAMPLE = 10`, `MIN_BAND_SAMPLE = 10` (donor-
  acceptance-rate by score band), `MIN_PORTFOLIO_SAMPLE = 10` (portfolio heatmap cells). All
  four thresholds are the same number, applied consistently as a "don't show a statistic from
  a near-empty sample" convention.
- `knowledge/cltv_assumptions.yaml`'s own header: *"THESE ARE LABELED PLACEHOLDER
  ASSUMPTIONS, NOT RESEARCHED FACT."*
- **4** real user accounts exist in production as of early August 2026. This figure comes from
  a live Supabase query run during this same working session — it is not written anywhere in
  a code comment or doc file, and is flagged here specifically because of that: it is
  first-hand, session-sourced knowledge, not a documented fact a future reader could
  independently re-verify from the repo alone. Treat it as current-as-of-query-time, not a
  permanent figure.

Put together: realistically, almost none of the volume-dependent features described above are
rendering meaningful live data for real users today, even though every one of them is
correctly built and wired.

## What this means for the pitch

The honest, and actually stronger, framing for a technical judge: the mechanisms are built
*ahead of* the data, not faked to look like they already work. A benchmark that correctly
withholds itself below 10 samples, rather than showing a misleading percentile from 3 data
points, is a sign of a team that understands what a false-positive statistic costs a user's
trust. Claiming these network effects are already delivering value at scale would be the
"confident invention" this whole document pack is built to avoid — the more defensible claim
is "correctly built, not yet proven," which is also the true one.

See `ecosystem_map.md` for how a validator relationship is the mechanism that would actually
turn the donor-verification effect from real-but-dormant into real-and-active, and `five_forces.md`
for why these data-owned assets (not the model vendor relationship) are what would actually
survive a change in AI supplier.
