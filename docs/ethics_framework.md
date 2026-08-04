# ImpactProof Ethics Framework (Laudon Ch.4)

*Laudon Ch.4 pass, reviewed 2026-08-04. Internal document mapping ImpactProof's existing
controls — most built for other reasons, across the Ch.6/Ch.8/Ch.11/Ch.12 passes — onto
Laudon & Laudon's five moral dimensions of information systems. Where a dimension has no
real control behind it, that's recorded as a gap, not glossed over. See
`docs/responsible_ai_statement.md` for the customer/investor-facing distillation of this,
and `docs/compliance/*.md` for the Act 843/NDPA-specific legal mapping (a narrower, adjacent
concern — legal compliance is not the same thing as ethical design, and this document is
about the latter).*

## Why this document exists

The user asked for this chapter to be done *before* shipping further AI features, not after —
the theoretical backbone for a rule already stated as non-negotiable in `CLAUDE.md`: **no AI
feature may invent, estimate, or impute a number, date, or fact the user didn't supply.**
That rule wasn't derived from this framework — it was written first, out of plain product
instinct. This document is the audit that confirms *why* it was the right instinct, in terms
Laudon's framework makes explicit, and what else the same reasoning implies.

## The five moral dimensions

### 1. Information rights and obligations

*Who has a right to know what, and who is obligated to protect it?*

| Control | Where |
|---|---|
| A beneficiary never has their identity, health status, or location typed into ImpactProof by ImpactProof itself — only by the NGO reporting on them, and the app actively discourages it | `docs/acceptable_use_policy.md`'s beneficiary-data redaction guidance; the Screen 1 upload warning |
| Free text (result statements, evidence descriptions) never lands in the warehouse — only scores, enums, dates, booleans do | `utils/assessment_facts.py` module docstring, Ch.6 |
| Documents are processed in memory only, never written to disk or a database | `test_document_retention.py` enforces this as a test, not just a claim |
| Encryption at rest for anything an account opts to save | `utils/crypto.py`, Fernet |
| Row-level security, real Supabase Auth identity | Ch.8 hardening (`0038`-`0054`) |
| A user can see and permanently delete their own saved history | My Audits "Danger Zone," `purge_account_audit_content()` |

**Gap:** no self-service "export everything about me" flow yet — today it's ad hoc via
support contact (already flagged in `docs/compliance/act843_mapping.md`'s open items, same
gap, not duplicated here).

### 2. Property rights and obligations

*Whose intellectual work is this, and is anyone's being used without right?*

ImpactProof's own scoring methodology (`evaluator.py`'s rubric) is cited, not claimed as
novel — it's explicitly anchored in named external standards (USAID ADS 201.3.5.7, OECD-DAC
2019, Bond Evidence Principles 2024, FCDO Evaluation Policy 2025, World Bank IEG Process
Tracing 2025, NESTA Standards of Evidence — see `framework_crosswalk.py`), not presented as
ImpactProof's own invention dressed up as authoritative.

The more direct property-rights question for this product: **does any AI feature ever
reproduce, in the improved version it hands back, that some property doesn't belong there?**
This is exactly what the fabrication guard prevents from the other direction — it stops the
AI from *adding* content that isn't the user's, which as a side effect also means it never
launders someone else's report language into a rewrite it presents as the user's own
improved draft. Not the guard's original purpose, but a real property-rights side benefit
worth naming.

**Gap:** no explicit policy on what happens if a user pastes another organisation's report
text into the form (plagiarism-adjacent, not currently detected or discouraged). Low
likelihood, not built — noted, not actioned this pass.

### 3. Accountability, liability, and control

*When the system is wrong, who is answerable, and is that traceable?*

This is where the most machinery already exists, because it's also where the product's core
trust claim lives — a wrong score is the whole failure mode.

| Control | Where |
|---|---|
| Every fabrication-guard trigger is logged as a real, queryable event, not silently swallowed | `metrics.log_event("draft_withheld_fabrication", ...)`, `council.py` |
| A withheld AI draft never silently becomes a blank field — it degrades to a structural, non-fabricated suggestion, and says so | `utils/fabrication_guard.py`'s retry-then-degrade, never a bare empty string |
| Scores are deterministic and rule-based, not AI-generated — `evaluator.py` never calls an API, so "the AI made a mistake" cannot be the explanation for a wrong score | `CLAUDE.md`'s "Rules are the source of truth for scores; AI narrates" |
| Every rule that fired to produce a score is traceable to a specific YAML rule with a citation | `knowledge/rules/*.yaml`, `rule_trace` in `evaluate_submission()`'s output |
| A user who disagrees with a rule can formally dispute it | `utils/rule_disputes.py` |
| Every export carries a verifiable reference ID a third party (a donor) can check | `utils/verification.py`, `?verify=` landing page |
| An append-only, hash-chained access log records who touched what | `access_log` (Ch.8, `0051`) |
| A named Security Officer / DPO role exists, even if one person holds both today | `docs/security_policy.md` |

This is the dimension Laudon's framework makes explicit that the product's own README-level
pitch already assumes: *a deterministic rules engine you can point to beats an AI you have to
trust.* The accountability chain here is close to complete — the one real gap is procedural,
not technical: `docs/incident_response_runbook.md` covers security incidents, but there is no
equivalent "a rule was wrong for weeks and mis-scored real submissions" runbook. **Gap,
worth a short addendum, not built this pass.**

### 4. System quality

*Is the data the system runs on actually correct, and does the system fail safely when it
isn't?*

This dimension is what Ch.6 already operationalised in full: `scripts/quality_audit.py` runs
5 of Laudon's own 7 data-quality dimensions against live tables (completeness, consistency,
uniqueness, validity, timeliness), and says explicitly, rather than silently skipping, that
the remaining two (accuracy, accessibility) aren't automatable with what ImpactProof has
today. Ch.6 Phase 2's cleansing-on-ingest checks (`evaluator.check_data_quality_flags()`) are
the same instinct applied at the point of data entry rather than after the fact — flag,
never silently correct, because a silent correction is itself a system-quality failure
dressed up as a fix.

**No new gap here** — this dimension was already built out deliberately in Ch.6; this
document just names it as what it structurally is.

### 5. Quality of life

*Does the system's design advantage some people over others, or create dependence/harm it
doesn't have to?*

This is the dimension most likely to be invisible without deliberately looking for it,
because nothing forces you to notice a design choice that's merely *unequal*, as opposed to
*broken*. Two real design choices are worth naming explicitly:

**The org-type-aware threshold** (`evaluator.py`: CBO/Government = 3.5, National NGO = 3.75,
INGO = 4.0) is an equity design, not a discount. A community-based organisation with two
staff and no M&E department genuinely cannot produce the same evidence chain as an INGO with
a dedicated MEL unit — holding both to the INGO bar would systematically fail the
under-resourced organisations this product should be most useful to. Naming this explicitly
matters because the alternative reading — "the bar is lower for some orgs" — sounds like
grade inflation until you see the actual worked reasoning:

> *A worked ethical analysis (Laudon's 5-step process, applied here):*
> **Facts** — CBOs and INGOs both submit the same 8-criterion evaluation, but structurally
> differ in access to internal review capacity, external verification partners, and
> data-collection infrastructure. **The conflict** — a single universal threshold either
> (a) locks CBOs out of ever reaching "Submission-Ready," making the product useless to the
> organisations most in need of a rigor tool, or (b) if lowered for everyone, degrades the
> INGO-facing rigor claim the product's credibility depends on. **Stakeholders** — CBO/
> Government users, National NGO users, INGO users, and the donors reading everyone's output.
> **Options considered** — one universal bar; three separate bars (built); a single bar with
> a manual donor-facing "context" note instead of a structural threshold change (rejected —
> silently reduces the actual guarantee rather than being honest about what's being measured
> for whom). **Consequences of the option built** — a donor reading a CBO's "Submission-Ready"
> badge needs to know it was measured against the CBO/Government track, not silently against
> the INGO one — this is exactly what `track_label` in `evaluate_submission()`'s output and
> the Readiness Card's crosswalk tags surface today, not hidden.

The second: **the do-no-harm/child-safeguarding compliance gate** (`compute_compliance_layer()`,
hard-gates the diagnostic badge, cannot be scored around) exists because a technically
"Strong" result statement describing programming that put a vulnerable population at risk
should never read as donor-ready. This is Laudon's quality-of-life dimension applied to the
people the *reports themselves* are about, not just the people using the tool — the furthest
downstream stakeholder in this whole system, and the easiest one to forget.

**Gap:** no systematic check for whether the org-type-aware threshold itself, over time,
produces materially different *outcomes* (e.g., are CBO submissions disproportionately still
failing even at the lower bar, suggesting the gap is bigger than one threshold step can
close?) — this would need real usage data at a volume ImpactProof doesn't have yet. Flagged,
not actionable this pass.

## Candidate ethical principles this maps to

Laudon's textbook names several classical test principles for a hard case. The one that maps
most directly onto the fabrication guard's design is the **risk aversion principle**: of the
available options (fabricate confidently, stay silent, degrade honestly), choose the one with
the lowest-cost failure mode. A silently blank field costs a user a moment of confusion; a
confidently fabricated number costs a user's credibility with a donor. The guard is built to
fail toward the cheaper mistake, every time — this is the actual justification, not merely
"AI hallucination is bad," which is a symptom description, not a design principle.

## Summary of open items from this pass

1. No self-service full data export flow (same gap already tracked under Act 843).
2. No policy on pasted third-party report text (property rights, low likelihood, not built).
3. No "a rule was wrong for a period" runbook addendum (accountability, procedural gap).
4. No outcome-level check on whether the org-type threshold gap is calibrated correctly at
   real usage volume (quality of life, needs data ImpactProof doesn't have yet).

None of these are urgent; all are now named rather than invisible.
