# Value Chain Positioning — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Evidence status: **Confirmed** / **Assumption** / **Research
needed**, as in `five_forces.md`.*

## The donor-funded programme value chain

```
proposal → design → implementation → monitoring → evaluation → reporting → renewal
```

A donor-funded programme moves through these stages roughly in order: an organisation
proposes a programme, designs its results framework (indicators, targets, baselines),
implements it, monitors and evaluates along the way, reports results to the donor, and — if
successful — seeks renewal or a next funding round on the strength of that reporting.

## Where ImpactProof sits today — confirmed

ImpactProof inserts at **reporting** — the latest and weakest point of intervention in that
chain. By the time the tool runs, the decisions that actually determine whether good evidence
exists have already been made, for better or worse.

This is confirmed by the product's own four-screen structure (`app.py`'s module docstring):
Screen 0 (landing), Screen 1 (result entry — enter/logframe/evidence/review tabs), Screen 2
(Confidence Snapshot & Next Steps — the score), Screen 3 (Portfolio/Framework Dashboard,
including "Audit My Report" document extraction). Every one of these screens operates on a
**result statement and evidence that already exist**:

- The Achievement field's own helper text presupposes the activity already happened
  ("*Actual delivered number*... *Must reconcile with your result statement above*").
- The Target field's help text treats the approved figure as an external, already-fixed fact
  from earlier in the lifecycle: *"The target as approved in the original Technical Proposal.
  Donors compare achievements against approved targets — not revised internal targets."*
  ImpactProof reads this fact; it never participates in setting it.

In plain terms: if an organisation collected the wrong evidence, or defined an unmeasurable
indicator, or never established a baseline, ImpactProof finds that out — it does not prevent
it. A tool that only diagnoses at reporting time is diagnosing after the point where the
outcome was still changeable.

## The upstream exception that already exists

**Confirmed, and very recent** (`utils/impact_linked_readiness.py`, commit `75f7fa3`,
2026-08-05 — built the same day as this document): the Impact-Linked Readiness Module is a
partial, genuine exception to the "reporting-only" pattern above.

Its `check_indicator_contractibility()` function only reads the indicator name, target,
baseline, and disaggregation status — it does **not** require a result statement or
achieved-value evidence. That means it can meaningfully assess whether an indicator is *well
enough defined to measure at all* before any data collection has happened. The form even has a
"data not yet available for this indicator" checkbox whose help text states the gap gets
disclosed in the report, not penalized — a structural acknowledgment that this check can run
on an incomplete, in-progress indicator.

**The honest limitation, stated in the same breath:** this capability is surfaced as an
expander bolted onto Screen 1's report-time review tab, not as a standalone design-stage
workflow a programme team would use *before* implementation starts. The mechanics already
point upstream; the product surface doesn't yet. A user has to be inside the report-time flow
to reach it.

## The downstream opportunity: renewal

**Not yet built — a roadmap direction, not a shipped capability.** A programme seeking a
second funding round needs to show a donor (or, per `ecosystem_map.md`, a validator like an
impact-linked lender) an evidence trail across an entire grant cycle, not a single scored
report. No feature in the codebase currently aggregates scored reports into a
renewal-readiness view. This is the natural downstream counterpart to the readiness module
above — where "design" asks "is this indicator defensible before we start," "renewal" would
ask "has this indicator actually held up, report after report, across the cycle."

## What this implies for the roadmap

Two concrete moves follow directly from the above, both labeled as proposed direction, not
committed delivery:

1. **Give the Readiness Module a design-stage entry point independent of Screen 1** — a user
   should be able to check an indicator's contractibility before a report exists at all, not
   only as a side-expander on an already-scored report.
2. **Build a renewal/evidence-trail view** that aggregates a programme's scored reports across
   a grant cycle into the kind of longitudinal evidence a funder deciding on renewal — or an
   impact-linked lender deciding on a rate step-down — would actually want to see.

**Research needed:** no effort estimate, timeline, or committed roadmap status exists for
either move. They are named here as the logical next step implied by the value-chain gap, not
as planned work with a delivery date.

## Scope correction: the Logframe Library is not a design-stage workflow

Worth stating explicitly so it doesn't get oversold elsewhere in this document pack: the
Logframe Library feature (`app.py`, `create_logframe_library`/`get_library_items`) lets a user
save and reload a set of indicators across submissions. It is a convenience cache — it saves
retyping — not an approval or design-review workflow. It should not be cited as evidence that
ImpactProof already operates at the design stage.

See `network_effects.md` for whether the Impact-Linked Readiness Module's upstream capability
creates any new network effect (it does not — it's an isolated, per-organisation check today),
and `ecosystem_map.md` for who a renewal-readiness view would actually serve.
