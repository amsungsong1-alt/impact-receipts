# Organisational Resistance to Change — ImpactProof

*Laudon Ch.3 pass, 2026-08-05. Evidence status: **Confirmed** / **Assumption** / **Research
needed**, as in `five_forces.md`.*

## Why this document exists

Laudon's point on organisational resistance: new information systems disrupt established
power relationships, and people resist systems that threaten their authority, workload
security, or the value of their judgment — regardless of the system's technical merit. A
strategy pitch that only talks about external competitive positioning and never asks "who
inside the customer organisation loses when this arrives" has skipped the adoption question
that actually determines whether a sale survives contact with the people who have to live with
the tool day to day. This section is usually missing from pitches; its presence here is meant
to signal operational seriousness, not just theoretical completeness.

## Three named roles, and what each has to lose

### The M&E officer

**What they lose, if the product is framed wrong:** the person who compiled the report is now
the person whose work gets graded by a tool, potentially in front of their own manager or a
donor. Framed that way, the tool is a surveillance instrument pointed at them.

**How the product is actually designed, and why that reframe is plausible:** ImpactProof runs
*before* submission, in the officer's own hands, not after the fact by someone else. When a
check fails, the response is a structural nudge, not a bare rejection — e.g., the fabrication
guard's fallback message, cited in `five_forces.md`, explicitly tells the user what's missing
("This sentence needs a denominator — you have not provided one") rather than silently
producing a worse document or a public failing grade. The reframe: the officer gets defensible
ammunition in an internal argument, and catches a gap privately, while it's still fixable,
instead of being caught by a donor after submission when it no longer is.

### The programme manager

**What they lose, if framed wrong:** a claim they've been reporting gets challenged, possibly
in a moment (a donor review meeting) where being wrong is a real reputational or career cost.

**The reframe, by the same logic as above:** the same challenge happens earlier and privately —
inside the organisation, before the report goes anywhere — rather than in front of the funder.
The manager gets early warning before a donor finds the gap, which is a meaningfully different
experience than being contradicted by an outside party in real time.

### The consultant

**What they lose, if framed wrong:** the sense that a deterministic scoring engine is quietly
replacing the judgment they're paid for.

**The reframe, grounded in the actual architecture, not just a rhetorical answer:**
`evaluator.py` sets the score deterministically — that part genuinely is automated, and
pretending otherwise would be dishonest. But per `docs/responsible_ai_statement.md` and the
deterministic/AI split documented in `five_forces.md` and `competitive_strategy.md`: *"AI in
ImpactProof narrates, questions, and drafts around that score — it never sets it, and it never
gets to override it."* Council Assessment's five-persona debate, Score Chat, and the narrative/
remediation layer are still AI-assisted judgment work, not eliminated by the deterministic
score underneath them — and a consultant's actual paid work (interpreting a score for a client,
advising on what to fix and how, navigating a specific donor relationship) sits squarely in
that narrative layer, not in the arithmetic. The reframe: the tool makes a consultant's review
faster by doing the mechanical cross-checking first, leaving the judgment work — which is the
part clients actually pay a consultant for — untouched.

## Where the reframe is not yet proven

**Confirmed limitation, stated as the central honesty check of this document:** everything
above is a design intention read directly from the architecture — the fabrication guard's
fallback phrasing, the deterministic/AI split, the pre-submission timing of every screen. None
of it is a validated outcome. **Research needed:** no interview, survey, or pilot feedback
exists anywhere in this codebase or research confirming that any actual M&E officer, programme
manager, or consultant has experienced ImpactProof as a source of gain rather than threat. The
architecture supports the reframe; it does not prove it landed.

This is deliberately the sharpest gap named in this document pack for this section, because it
is the easiest one to quietly skip in a pitch — "the tool is designed to help you, not
replace you" sounds true and costs nothing to say. The honest version is narrower: it is
designed with that intention, and the design choices that support the intention are real and
citable, but nobody has yet confirmed a real user felt it that way.

## Product-design implications

Two concrete recommendations, both aimed at keeping the reframe true as the product grows
rather than accidentally drifting into the "grading authority" framing it's designed to avoid:

1. **Keep Council Assessment and the score-explanation layer internal and pre-submission by
   design.** If a future version exposes AI-generated commentary to a donor or external party
   directly, the M&E officer's "catches it privately first" advantage disappears, and the
   surveillance-instrument framing becomes accurate again.
2. **Any future donor-facing surface (per `ecosystem_map.md`'s validator relationship) needs a
   separate resistance analysis of its own** — a donor who can see an ImpactProof score
   directly changes the M&E officer's incentive structure again, potentially reintroducing the
   exact dynamic this document argues the current design avoids. This should be revisited, not
   assumed to still hold, if that relationship ever forms.

See `pitch_spine.md` for how much of this reframe can honestly be claimed on a two-page pitch
without overstating what's validated.
