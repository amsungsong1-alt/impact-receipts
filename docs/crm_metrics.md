# CRM metrics — baselines (Laudon Ch.9, C8)

Laudon's §9-4 finding: enterprise applications fail when the firm can't measure whether they
worked. This records, for each metric Phase 1 (C1–C3) introduces, the baseline before it
shipped, the target, and a review date — so a later "did this help" question has something to
compare against.

**Status as of this document's creation: baselines are NOT yet filled in.** Migrations `0024`
and `0025` are written but not applied to production, and the `customer-profile-refresh` Edge
Function is not yet deployed — `customer_profiles` has no real rows to compute a baseline from
yet. Filling in the table below with invented numbers would violate this project's own
no-fabrication rule applied to metrics, not just AI drafts. **Fill in the "Baseline" column
the first time `refresh_customer_profiles()` has run against live data and produced a
non-trivial sample** (see each function's `MIN_CHURN_SAMPLE = 10` gate — a rate computed below
that threshold is `None`, not a number, and shouldn't be recorded as a baseline either).

| Metric | How it's computed | Baseline | Target | Review date |
|---|---|---|---|---|
| Behavioural segment distribution | `utils.crm.build_behavioral_segments()` — count per segment (trial/episodic/embedded/org_emergent/dormant_seasonal/at_risk/lapsed) | _fill in_ | n/a — descriptive, not a target metric | _fill in_ |
| Behavioural churn rate | `utils.crm.compute_behavioral_churn_rate()` — `None` if the historically-active cohort is below `MIN_CHURN_SAMPLE` (10) | _fill in, or "insufficient sample"_ | _fill in once a baseline exists_ | _fill in_ |
| Revenue churn rate | `utils.crm.compute_revenue_churn_rate()` — derived from `payments` history; `None` below `MIN_CHURN_SAMPLE` ever-subscribed accounts | _fill in, or "insufficient sample"_ | _fill in once a baseline exists_ | _fill in_ |
| Time-to-second-assessment (distribution) | `utils.crm.time_to_second_assessment_distribution()` — days between an account's 1st and 2nd `audit_run` event, across every qualifying account | _fill in (e.g. median/mean days)_ | _fill in once a baseline exists_ | _fill in_ |

## Why these four and not more

C4 (CLTV), C5 (the analytical dashboard these numbers would otherwise render on), C6
(lifecycle triggers), and C7 (cross-sell logging) are explicitly deferred out of this phase —
see the phase plan. This table only covers what Phase 1 actually built, per C8's own framing:
a CRM whose dashboards nobody can act on, or whose baselines were never recorded, is exactly
the enterprise-application failure mode §9-4 describes (p. 361). Extend this table rather than
starting a second one when C4–C7 ship.

## How to fill this in once live

1. Apply migrations `0024`/`0025` to production and deploy the `customer-profile-refresh`
   Edge Function (`supabase functions deploy customer-profile-refresh`).
2. Let it run at least one full hourly cycle (or invoke it once manually) so
   `customer_profiles` is populated.
3. From a Python shell with `SUPABASE_DB_URL` configured:
   ```python
   from utils.crm import (
       build_behavioral_segments, compute_behavioral_churn_rate,
       compute_revenue_churn_rate, time_to_second_assessment_distribution,
   )
   {k: len(v) for k, v in build_behavioral_segments().items()}
   compute_behavioral_churn_rate()
   compute_revenue_churn_rate()
   time_to_second_assessment_distribution()
   ```
4. Record the actual output above, with today's date as the review date (pick a review
   cadence — e.g. quarterly, matching the MEL reporting calendar this same phase introduced).
