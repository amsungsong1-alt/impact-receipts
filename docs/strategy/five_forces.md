# Five Forces Analysis — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Prepared for the Execute Africa AI Challenge pitch (ALX Tech
Hub Accra, September 2026) and impact-linked finance conversations. Evidence status is marked
inline: **Confirmed** (from the codebase or a live query this session), **Assumption** (a
stated position, not yet validated), **Research needed** (explicitly unanswered — not
invented).*

## Framing

ImpactProof scores the evidence quality of a completed NGO/MEL donor report against
deterministic, citation-anchored criteria. The question this document answers honestly: what
actually stops someone from not using it, or from building it themselves? The uncomfortable
answer is that the strongest force here isn't a competing product — it's every free thing an
M&E officer already has open in another browser tab.

## 1. Threat of substitutes (the force that matters most)

Four real substitutes, ranked by how good they already are:

1. **A donor's own review process.** This is the actual "no sale" outcome for most reports
   today — the donor reads the report and forms their own judgment regardless of any tool.
   ImpactProof's pitch has to be "catch this before the donor does," not "replace the donor."
2. **A MEL consultant's judgment.** Expensive, inconsistent across consultants, and
   effectively unavailable to organisations below INGO budget size — which is precisely the
   community/national-track user ImpactProof's org-type thresholds are calibrated for (see
   `competitive_strategy.md`).
3. **A Word/Excel template.** Free, zero rigor, but genuinely "good enough" for an
   organisation that has never been challenged by a donor before.
4. **A general-purpose LLM used directly by the M&E officer.** *(Confirmed — this is the
   sharpest substitute and the one a technical judge will ask about first.)* An officer can
   already paste a result statement into ChatGPT or Claude and ask "does this look
   donor-ready?" This is free, immediate, and requires no new tool relationship.

**Answering the LLM substitute directly, on technical merit, not on marketing:**

- A raw LLM session will draft *confidently* on numbers it wasn't given — it has no mechanism
  to know which numerals in its own output came from the user versus its own inference.
  ImpactProof's `utils/fabrication_guard.py::check_fabrication()` extracts every numeral from
  an AI-drafted statement and verifies each one appears somewhere in the user's own raw
  submission fields; anything that doesn't is withheld, not shown, with a literal message
  saying so. A raw LLM chat has no equivalent check — it cannot refuse its own hallucination
  because it has no ground truth to check itself against.
- A raw LLM session gives a *different* answer to the same report on a different day, or in a
  different conversation, or to a different officer at the same NGO. `evaluator.py`'s own
  module docstring states the design constraint directly: *"Fully deterministic — same inputs
  always produce the same outputs. No API calls."* The score itself never touches a language
  model at all — confirmed by grep, zero Anthropic imports in that file. A donor comparing two
  reports scored by ImpactProof is comparing against the same rubric both times; a donor
  comparing two ChatGPT sessions is not.
- This is a real, defensible, structural difference — not a claim that ImpactProof is "smarter"
  than a general LLM, which would be a losing argument. The claim is narrower and provable:
  reproducibility and refusal-to-fabricate are things a bare chat session structurally cannot
  offer, regardless of which model is used.

## 2. Threat of new entrants

Two realistic entrants: an established MEL/donor-reporting platform bolting on a scoring
layer, or a donor building this in-house (some already run internal DQA — Data Quality
Assessment — processes).

**Confirmed:** none of the actual mechanism (the rule engine, the fabrication guard, the
org-type thresholds) is patent-protected or technically hard to replicate. A well-resourced
team could rebuild the scoring logic in weeks.

**What isn't easily replicated, but is untested as a real moat (Assumption):** calibration to
specific funders and grant tiers. `donor_templates.py` covers 12 donors, five of them with
real, citation-anchored guidance (USAID ADS 201.3.5.7, FCDO Evaluation Policy January 2025 /
EQuALS 2, GIZ Results-Based Monitoring, World Bank PDO-level results / IEG RAP standards,
Mastercard Foundation's Young Africa Works tracer-survey standard); the org-type thresholds
are *presented to users* as calibrated to real Ghana funding mechanisms (STAR-Ghana, District
Assembly grants — see `competitive_strategy.md`), but no source document ties the specific
3.5/3.75/4.0 threshold values to either program — **this specific number-to-source link is
itself Assumption, not Confirmed**, distinct from the donor citations above which do trace to
a named instrument. This calibration work is slow and requires domain access most software
teams don't have. Whether that's a durable barrier or just a head-start has not been tested
against an actual competitor attempt — **research needed.**

The other candidate barrier is a future validator relationship (a funder whose endorsement
makes a score meaningful to third parties) — see `ecosystem_map.md`. This does not exist yet
and cannot be claimed as a current moat.

## 3. Rivalry among existing competitors

**Research needed.** No named direct competitor (a product that does the same thing —
deterministic, rule-based MEL evidence-quality scoring) was identified anywhere in this
research. This is stated plainly rather than asserted as "no competition" — the honest position
is that a competitive landscape search hasn't been done, not that one was done and came back
empty.

## 4. Bargaining power of customers (NGOs)

NGOs are grant-funded and budget-constrained. The person who experiences the product's value
(the M&E officer, catching a gap before a donor does) is frequently not the person who
approves the purchase (an Executive Director or Country Director) — a split-decision-maker
problem common to B2B tools sold into resource-constrained organisations.

**Confirmed mitigation, partial:** the pricing structure is built to absorb this — a low
per-check entry price (GHS 5.00), three free checks with no card required, before any
subscription commitment (`app.py:251-254`). This lowers the barrier for an officer to
demonstrate value *before* asking a director for budget, but does not solve the
split-decision-maker problem outright — that would need a director-facing value story this
pack doesn't yet make. **Research needed:** whether the free-tier-to-paid conversion path
actually reaches the budget-holder in practice.

## 5. Bargaining power of suppliers (the uncomfortable one)

**Confirmed:** ImpactProof depends on a single foundation-model vendor (Anthropic) for every
AI-touching feature. Five real call sites exist in the codebase: Instant Report Check
extraction, Score Chat, batch/portfolio document extraction, Portfolio Chat, and four
council.py features (Council Assessment's 5-persona debate, evidence-type debate, logframe-
indicator matching, and an admin-only competitive-position debate tool). This is genuine
supplier concentration risk — a price increase, API deprecation, or policy change at one
vendor touches every one of these features simultaneously.

**The mitigation, stated as substance, not a hand-wave:** the *score itself* — the thing a
donor actually reads and a funder would condition money on — never depends on the vendor
relationship at all. `evaluator.py` makes zero API calls. Every AI-touching feature has a
coded degrade path, not just a hoped-for one: Instant Report Check falls back to rule-based
extraction only with an explicit on-screen notice when no API key is configured; Score Chat
explicitly tells the user it's unavailable rather than failing silently. If the vendor
relationship broke entirely tomorrow, the core product — the deterministic score — would keep
working exactly as it does today.

**What this mitigation does *not* cover, stated honestly:** the narrative layer (Council
Assessment's synthesis, the fix-it drafting, the conversational explanation of a score) would
degrade or disappear along with the vendor relationship. That is a real product-quality loss,
not a cosmetic one — for a paying subscriber, "no more AI narrative" is a meaningfully worse
product, even though the number they're paying to trust survives intact.

## Synthesis

| Force | Verdict | Mitigation status |
|---|---|---|
| Substitutes (esp. direct LLM use) | **High** | Real, structural answer exists (fabrication guard + determinism) — see above |
| New entrants | Medium | Technical replication is easy; funder-calibration barrier is real but untested as durable |
| Rivalry | Unknown | No competitor landscape research done — flagged, not invented |
| Customer power | Medium-High | Pricing partially absorbs it; split-decision-maker problem unsolved |
| Supplier power | **High** | Score survives a vendor break; narrative/Council layer does not |

See `competitive_strategy.md` for how the deterministic-engine mitigation becomes the actual
strategic asset, not just a defensive answer, and `network_effects.md` for confirmation that
the benchmark/verification data assets are owned by ImpactProof, not the model vendor, and
survive the same supplier-power scenario.
