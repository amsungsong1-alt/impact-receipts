# ImpactProof Unit Economics (Laudon Ch.10, C1)

*Laudon Ch.10 pass, reviewed 2026-08-04. Internal document. Numbers below are computed
directly from production `api_usage_log` (the Ch.9 CLTV pass's real per-call cost logging,
`utils/api_pricing.py`), not estimated or assumed — except where explicitly marked
"assumption" or "insufficient data," per this project's flag-never-guess convention.*

## Why this document exists

ImpactProof runs freemium (3 free checks), transaction-fee (GHS 5/use), and subscription
(GHS 50/mo Professional, GHS 200/mo Agency) revenue models simultaneously — a combination
Laudon's Ch.10 digital-goods framing (marginal cost ≈ 0) explicitly warns against, because
this product's marginal cost is *not* near zero: every AI-assisted assessment costs real
Anthropic API money. This document is the actual measurement that combination needs to be
priced responsibly, not a restatement of the theory.

## The honest headline: sample size is currently too small to price on

As of 2026-08-04, `api_usage_log` has exactly **6 rows** tagged to a call site that gates a
scored assessment (`irc_extraction`, `batch_extraction` — see `ASSESSMENT_CALL_SITES` in
`utils/api_pricing.py`). The numbers below are real, not synthetic — but 6 data points is not
a decision-grade sample. Treat everything in this section as **directionally informative,
not something to set a price from**, and recompute once volume grows. This document should
be regenerated periodically, not treated as a one-time artifact.

## Current real numbers (n=6, as of 2026-08-04)

| Metric | Value | Function |
|---|---|---|
| Mean cost per assessment | 153.09 pesewas (**GHS 1.53**) | `compute_average_cost_per_assessment()` |
| p95 cost per assessment | 252.46 pesewas (**GHS 2.52**) | `compute_p95_cost_per_assessment()` |
| Cheapest observed | 96.49 pesewas | — |
| Most expensive observed | 252.46 pesewas | — |

The mean/p95 gap (GHS 1.53 vs GHS 2.52) is mostly explained by call-site mix, not document
length: `irc_extraction` runs average ~103 pesewas (4 rows), `batch_extraction` runs average
~249 pesewas (2 rows) — batch extraction is a structurally different, pricier operation, not
just "longer documents." This means the p95 figure right now reflects *which feature was
used* more than *how long the document was* — worth re-examining once each call site has
enough of its own volume to be judged separately rather than pooled.

### Cost by document length (bucketed by `input_tokens`)

`compute_cost_by_document_length_bucket()`'s thresholds (`_DOC_LENGTH_SHORT_MAX_TOKENS=2000`,
`_DOC_LENGTH_MEDIUM_MAX_TOKENS=8000`) were a **plausible guess written before any real data
existed**. Running it against the actual 6 rows today: **all 6 fall into "long"** (every
observed `input_tokens` value is 11,825–14,773) — meaning `short`/`medium` currently see zero
real traffic in this data, not because they don't happen, but because the guessed thresholds
turned out too low for what a real donor-report document actually contains. **This threshold
needs recalibrating once there's a real distribution to derive it from — flagged, not fixed
in this pass**, since "recalibrate a threshold from 6 points" would just be a different
guess, not a measurement.

## Subscription break-even

`compute_subscription_breakeven_assessments(monthly_price_pesewas, cost_per_assessment_pesewas)`
= `monthly_price_pesewas / cost_per_assessment_pesewas`. Using the current all-accounts mean
(GHS 1.53/assessment) as the cost floor:

| Tier | Monthly price | Break-even assessments/month |
|---|---|---|
| Professional | GHS 50.00 | **~33 assessments/month** |
| Agency | GHS 200.00 | **~131 assessments/month** |

For context, `knowledge/cltv_assumptions.yaml`'s own placeholder assumption is
`expected_assessments_per_cycle: 3` — meaning at today's measured cost, a Professional
subscriber would need to run roughly **11× the currently-assumed usage rate** before the
subscription itself becomes margin-negative on AI cost alone. This is genuinely reassuring
given how sparse the underlying sample is, but should not be read as "pricing is safely
correct" — it should be read as "pricing is not obviously broken at n=6." Revisit with real
subscriber-cohort volume.

**Known scoping gap:** this break-even figure uses the **all-accounts mean**, not a
subscriber-only mean — `utils/api_pricing.py` has no `users.plan`-filtered query today. There
isn't yet enough subscriber-specific volume for that distinction to be more than noise.
**TODO:** add a `plan`-scoped variant of `compute_average_cost_per_assessment()` once there's
real Professional/Agency usage history to filter on.

## Deliberately not measured, and why

- **A literal per-assessment cost stored on the `assessments` row itself.** `assessments` is
  insert-only by design (migration `0031`'s own comment: "a point-in-time fact, never edited
  after insert") — a cost only known after an AI feature completes doesn't fit that contract
  without either a schema/grants change or a separate child table. The two call sites that
  currently gate a scored assessment (`irc_extraction`/`batch_extraction`) already produce a
  real, stored, queryable cost via `api_usage_log` — satisfying "measured and stored, not
  estimated" without a new migration. A true `assessment_id`-FK-linked cost table was
  designed and would only ever cover Score Chat (Council Assessment's own code already
  rejected identifier-threading for a comparable metric — see `council.py`'s comment near its
  `log_api_usage` call; IRC fires before the assessment row exists). **TODO**, not built this
  pass — the migration for it is not written, since one call site isn't worth a schema change
  yet.
- **Wall-clock duration as a stored field.** Anthropic bills per token, not per second —
  latency doesn't move any margin number. Not stored anywhere; the IRC screen's in-memory
  elapsed-time display remains UI-only, as it already was.
- **Storage/compute overhead as a computed number.** No infra cost-allocation mechanism
  exists (Streamlit Cloud/Supabase billing isn't queryable per-assessment). Treated as an
  explicit, reasoned assumption — **negligible relative to LLM API cost, not measured** —
  rather than a fabricated line item.

## Where these numbers come from

`utils/api_pricing.py`: `compute_average_cost_per_assessment()`,
`compute_p95_cost_per_assessment()`, `compute_cost_by_document_length_bucket()`,
`compute_subscription_breakeven_assessments()` — all read `api_usage_log`, all return `None`
(or an explicitly empty shape) rather than a guessed number when data is missing. Pricing
*assumptions* (not measurements) live in `knowledge/cltv_assumptions.yaml`, labeled as
placeholders per that file's own header. `scripts/pricing_model.py` (Laudon Ch.10, C2/C6)
builds pricing-scenario comparisons on top of these real numbers — see that file for gross
margin modeling; **this document is measurement, that script is modeling, and neither one
changes a live price.**
