"""
utils/policy_generator.py — Laudon Ch.6 Phase 2, C7 (the "draft information
policy generator" half, deferred from the earlier C7 pass).

Drafts a starting-point data/information policy for the CUSTOMER'S OWN
organisation -- entirely distinct from docs/privacy_notice.md and the other
docs/compliance/*.md files, which describe ImpactProof's own practices, not
the customer's. Template-filled, never LLM-generated: every section is
fixed boilerplate with slots filled ONLY from fields the account actually
supplied (account_sector/primary_donors/country -- the personalization
profile from migration 0017). A slot with no source data renders as an
explicit "[Add: ...]" placeholder, never a guessed value -- the same
flag-never-fabricate contract as every other AI-adjacent feature in this
app, even though this path makes no AI call at all and is fully
deterministic. Explicitly labeled a draft/starting point, not legal advice,
mirroring the disclaimer already used in docs/compliance/act843_mapping.md.
"""
from __future__ import annotations
from datetime import date

_PLACEHOLDER = "[Add: {0}]"


def _slot(value, what: str) -> str:
    """Returns value if present, else an explicit fill-in-the-blank
    placeholder -- never a guessed default."""
    if value and str(value).strip():
        return str(value).strip()
    return _PLACEHOLDER.format(what)


def generate_information_policy_draft(profile: dict, today: date | None = None) -> str:
    """profile: {"account_sector", "primary_donors" (list[str]), "country",
    "org_name"} -- any key may be missing/empty; each becomes an explicit
    placeholder rather than an invented value. `today` is injectable for
    deterministic testing; defaults to date.today(). Returns Markdown text.
    Pure function -- no I/O, no API calls, same "same inputs, same output"
    contract as evaluator.py."""
    profile = profile or {}
    today = today or date.today()

    org_name = _slot(profile.get("org_name"), "your organisation's name")
    sector = _slot(profile.get("account_sector"), "your sector (e.g. Health, WASH)")
    country = _slot(profile.get("country"), "your country of operation")
    donors = profile.get("primary_donors") or []
    donors_text = ", ".join(donors) if donors else _PLACEHOLDER.format("your primary donors")

    return f"""# {org_name} — Data & Information Policy (DRAFT)

*This is an automatically generated STARTING POINT, not a finished policy
and not legal advice. Every section must be reviewed and completed by
{org_name} before use — sections marked "{_PLACEHOLDER.format('...')}" have
no source data and were never guessed. Generated {today.isoformat()}.*

## 1. Purpose

This policy sets out how {org_name} collects, uses, stores, and protects
information relating to programme participants, staff, and partners in its
{sector} programming in {country}.

## 2. What we collect

{_PLACEHOLDER.format(
    "the specific categories of personal/programme data your organisation "
    "collects — e.g. beneficiary names, contact details, survey responses, "
    "health status, biometric data. This cannot be pre-filled from your "
    "ImpactProof account."
)}

## 3. Why we collect it

{_PLACEHOLDER.format(
    "the lawful basis and specific purpose for each category above — e.g. "
    "consent, contractual necessity, legitimate interest, legal obligation."
)}

## 4. Who we share it with

Primary donors/funders this organisation reports to: {donors_text}.

{_PLACEHOLDER.format(
    "any other third parties data is shared with — implementing partners, "
    "government ministries, evaluators."
)}

## 5. Storage and retention

{_PLACEHOLDER.format(
    "where data is stored (paper files, a database, a donor's system), how "
    "long it is retained, and when/how it is destroyed."
)}

## 6. Data subject rights

{_PLACEHOLDER.format(
    "how a beneficiary or staff member can ask to see, correct, or request "
    "deletion of their own data, and who handles that request."
)}

## 7. Cross-border transfer

{_PLACEHOLDER.format(
    f"if data leaves {country} — e.g. to a donor's head office, a cloud "
    "provider, or a regional office — state the destination and the "
    "safeguard relied on."
)}

## 8. Breach response

{_PLACEHOLDER.format(
    "who is notified internally, and within what timeframe, if data is "
    "lost, stolen, or improperly disclosed."
)}

## 9. Review

This policy should be reviewed at least annually and whenever data
practices materially change.

---
*Drafted with ImpactProof. Every "{_PLACEHOLDER.format('...')}" section
requires input from {org_name} — nothing in those sections was inferred or
invented.*
"""
