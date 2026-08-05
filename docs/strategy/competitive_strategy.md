# Competitive Strategy — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Evidence status: **Confirmed** / **Assumption** / **Research
needed**, as in `five_forces.md`.*

## Testing all four generic strategies before landing on one

Laudon's four generic strategies enabled by information systems: low-cost leadership, product
differentiation, focus on a market niche, customer/supplier intimacy. Each is tested against
ImpactProof's actual position, in order, and three are explicitly rejected rather than quietly
skipped.

### Low-cost leadership — rejected

**Confirmed, stated plainly:** not available, and pretending otherwise would weaken this
pitch. GHS 5.00 per check (`app.py:251-254`) is already close to marginal cost at current real
volume — `docs/unit_economics.md` puts the measured mean cost per assessment at GHS 1.53, on a
sample of 6 logged events, explicitly flagged there as too small to price on. There is no
scale economics story to tell yet, and no data-driven cost advantage to defend against a
donor or an established platform giving an equivalent feature away free. A pitch built on
"we're cheaper" would lose to the first well-funded entrant who decides to subsidize.

### Customer intimacy — present, but subordinate

The org-type-aware threshold system (below) is a genuine form of customer intimacy — the
product adapts its own pass bar to who's using it. But this is a *design choice inside* a
differentiation strategy, not a standalone strategy on its own. It doesn't survive as a
primary strategy in isolation.

### Supplier intimacy — not applicable

No meaningful supply chain in the traditional sense; the closest analogue (the Anthropic API
dependency) is a risk to manage (see `five_forces.md`), not an intimacy relationship to build
a strategy on.

### Broad differentiation — rejected in favor of focus

The product is calibrated too specifically to credibly claim broad-market differentiation: GHS/
Paystack mobile-money-first payment ordering (built specifically because mobile money is "the
dominant rail in Ghana" — `utils/paystack.py`), Ghana Data Protection Act 843 mapping
(`docs/compliance/act843_mapping.md`), and org-type thresholds calibrated to named Ghana
funding mechanisms (below). A broad claim ("evidence quality scoring for any NGO anywhere")
would have to walk past all of this specificity or dilute it.

## The winning strategy: focused differentiation

**Niche:** MEL evidence quality for African-context donor reporting — not "MEL software," not
"grant management," not a general nonprofit tool.

**Differentiation axis:** auditable, rule-based scoring with a code-level fabrication guard.

This is not invented pitch language — it's the same self-assessment framework already shipped
inside the product itself. `council.py`'s `debate_competitive_position()` (an admin-only tool,
lines 843-990) scores the product's own positioning against four pillars it calls **DRCA**:
**D**eterministic, **R**eproducible, **C**omparable, **A**uditable (`council.py:928-931`, `971`
— confirmed by direct read). Reusing this framing here rather than coining new positioning
language:

- **Deterministic** — `evaluator.py` never calls an API; the same submission always produces
  the same score.
- **Reproducible** — a second reviewer, or the same reviewer a year later, gets the same
  number from the same inputs.
- **Comparable** — org-type-aware thresholds (below) mean two reports on the same track are
  measured against the same bar, not an ad hoc judgment call.
- **Auditable** — every score carries a firing trace (`knowledge/rules/*.yaml`) explaining
  *why* it landed where it did, and every export carries a checkable `Ref: IMP-...` ID (see
  `network_effects.md`).

## Evidence the niche is real

The org-type threshold system (`evaluator.py:1872-1882`) sets three tiers, not one:

```
CBO / Government department  → threshold 3.5  ("community standard")
National NGO                 → threshold 3.75 ("national standard")
International NGO (default)  → threshold 4.0  ("INGO standard")
```

**Confirmed:** these tiers are calibrated to real, named funding mechanisms, per the in-app
Fairness expander (`app.py:9784-9810`). The INGO track is calibrated to USAID, FCDO, GIZ, and
Mastercard Foundation bilateral reporting requirements. The community/national track is
calibrated to **STAR-Ghana, District Assembly grants, and national government reporting** — a
real Ghana civil-society funding mechanism and Ghana's actual local-government funding
structure, respectively. This is the single most concrete Ghana-specific product-design fact
in the codebase, and it's structural, not cosmetic: the community track also recognizes
non-formal evidence types (community elder council / ward committee verification, village
books, PRA outputs, Executive Director/board review in place of a dedicated MEL Officer) and
exempts these from a ×0.6 non-numeric-evidence penalty multiplier that otherwise applies.

## Evidence the differentiation axis is real

Same facts as `five_forces.md`'s substitute-response section, reframed here as strategy rather
than defense: the fabrication guard (`utils/fabrication_guard.py::check_fabrication()`) and
the deterministic engine are not features bolted onto a generic AI product — they are the
entire reason the product can make a claim ("this is the same score every time, and it will
never show you a number you didn't provide") that a general-purpose LLM structurally cannot
match.

## What the niche is not

- Not a general MEL platform (no data collection, no case management, no grant tracking).
- Not a data-collection tool — it scores evidence that already exists; it does not help
  collect that evidence.
- Not, today, a donor-facing product — donors are not yet a direct user or customer of
  ImpactProof (see `ecosystem_map.md`'s validator gap).

## Residual honesty check

Even the differentiation claim has a disclosed limit. The same Fairness expander that
establishes the equity rationale for the tiered thresholds also states the limitation
directly, in the product's own words: *"Provenance bonuses... still reward formal sampling
documentation, independent enumerators, and auditor-retrievable records. Community
organisations with informal but legitimate data collection may reach 3.5 without maximising
provenance."* In plain terms: the lower-threshold track is a real equity design, not a perfect
one — it still structurally rewards organisations that can produce formal documentation over
those that can't, just less severely than a single universal bar would. Stating this here,
inside the document arguing for the strategy, is deliberate — the differentiation claim should
survive its own honesty check, not just look good until someone reads the fine print.

**Assumption, not yet tested:** that focused differentiation is the right strategy for the
*long term*, not just the current stage. If a genuine validator relationship materializes (see
`ecosystem_map.md`), the strategic center of gravity could shift from "a tool NGOs use" to "a
signal donors rely on" — a meaningfully different, broader positioning. This document argues
for focus *now*, not forever.
