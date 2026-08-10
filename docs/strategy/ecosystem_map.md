# Ecosystem Map — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Evidence status: **Confirmed** / **Assumption** / **Research
needed**, as in `five_forces.md`. This document is a target map, not a partnerships page —
stated once here so it does not need repeating in every section below: no relationship
described here currently exists with any named organisation.*

## Three ecosystems, one table

| Ecosystem | What they need | What ImpactProof offers today | Possible relationship |
|---|---|---|---|
| Impact-linked finance (Roots of Impact, iGravity, Swiss SDC, comparable actors) | A defensible, auditable evidence signal they don't have to build or verify themselves | A deterministic, DRCA-framed score plus the Impact-Linked Readiness Module's indicator-contractibility check | Customer or validator — untested |
| Donor ecosystem (World Bank, FCDO, GIZ, USAID successors) | Confidence that a report's claims hold up to their own standard, without a full manual DQA every time | Citation-anchored scoring calibrated to their own published standards (`donor_templates.py`) | Validator (highest value) or channel |
| MEL practitioner ecosystem (independent consultants, in-house M&E officers) | A faster, defensible starting point for their own review work | A scored, gap-flagged report they can review instead of starting from scratch | Customer today; potential channel; also a potential resistance source (see `resistance_analysis.md`) |

## Impact-linked finance ecosystem

These actors condition a portion of an enterprise's or programme's financial terms — an
interest-rate step-down, a SIINC premium — on independently verified outcomes. What they need,
by the nature of that model, is evidence they can trust *without* having to build their own
verification infrastructure for every deal.

**Assumption, not a relationship claim:** ImpactProof's deterministic, DRCA-framed score
(`competitive_strategy.md`) and the Impact-Linked Readiness Module's per-indicator
contractibility check (`utils/impact_linked_readiness.py`, built 2026-08-05) are a plausible
fit for this need — the module's own design explicitly targets exactly this use case (checking
whether one contractual indicator is defensible enough to put money on). But this is a
market-fit hypothesis read from the product's own architecture, not a tested one.
**Confirmed:** no relationship, contact, or expressed interest from Roots of Impact, iGravity,
Swiss SDC, or any comparable organisation exists anywhere in this codebase or research. This
should be presented to a judge as a target ecosystem, not a partnership in progress.

## Donor ecosystem

**Confirmed, real product calibration:** `donor_templates.py` covers 12 donors total. Five
carry citation-anchored guidance to a specific named instrument — USAID (ADS 201.3.5.7), FCDO
(Evaluation Policy January 2025, EQuALS 2), GIZ (Results-Based Monitoring), World Bank
(PDO-level results, IEG RAP standards), and Mastercard Foundation (Young Africa Works'
6-month employment tracer-survey standard, ≥60% coverage). The remaining seven (RVO, AfDB,
EU/EuropeAid, KOICA, SIDA, SDC, Global Fund) carry correct but more general guidance, since no
section-numbered public citation was found for them at write time. This relationship is real
but **one-directional**: ImpactProof reads and encodes donor standards; no donor currently
reads ImpactProof's output back, or has endorsed it in any way.

This is the validator gap, and it deserves to be named plainly rather than implied away: the
single most consequential relationship ImpactProof could form is a donor, or an impact-linked
finance actor, treating an ImpactProof score as a real signal — something that changes how
they read a report, or (in the impact-linked case) something a financial term is actually
conditioned on. That is what would convert `network_effects.md`'s dormant donor-verification
mechanism into an active one. Nothing in the current product or research indicates this
relationship exists in any stage of formation. **Research needed:** any outreach, interest, or
pilot conversation with a named donor organisation.

## MEL practitioner ecosystem

Today, MEL consultants and in-house M&E officers are primarily **users** of ImpactProof, and —
per `five_forces.md` — a consultant's own judgment is one of the product's direct substitutes.
This is a real tension worth naming rather than glossing: the same actor can be read as a
potential channel partner (a consultant who recommends ImpactProof to their client
organisations) or a competitive threat (a consultant whose judgment work the product partially
automates), depending entirely on how the relationship is designed. `resistance_analysis.md`
addresses the internal-adoption side of exactly this tension — read that document for how the
product is designed so a consultant gains from ImpactProof's existence rather than being
displaced by it.

## The validator argument, made explicit

Why "validator" is the highest-value relationship type, more valuable than "customer": a
customer relationship means an organisation pays to use the tool on itself — real revenue, but
it doesn't change what a third party thinks a score means. A **validator** relationship — a
donor or funder whose endorsement or reliance on ImpactProof output is visible to others — is
the only relationship type that converts a self-reported score into a third-party-recognized
signal. That is the precondition for the donor-verification network effect (`network_effects.md`)
to actually activate, and for the value-chain move into "renewal" (`value_chain.md`) to mean
anything to a funder deciding whether to fund again.

**What would need to be true for this to happen** — named as a target, not a fact: a pilot
relationship with one funder, plausibly surfaced through exposure at the Execute Africa AI
Challenge itself, where a scored report or an Impact-Linked Readiness certificate is put in
front of an actual funder and they choose to rely on it for a real decision. This has not
happened. It is the single most important open item in this entire document pack.

## What ImpactProof is not yet positioned for

Stated plainly, once, to close this document: ImpactProof has no current standard-setter role
in any of these three ecosystems, and no signed or informal relationship with any named
organisation listed above. Every entry in the table at the top of this document describes
"what could be," not "what is."
