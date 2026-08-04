# Ghana Data Protection Act, 2012 (Act 843) — Control Mapping

*Last reviewed: 2026-08-03. This maps Act 843's general structure (as
publicly understood — not a substitute for reading the current statutory
text or taking Ghanaian legal advice) to what ImpactProof actually
implements. Where a principle has no corresponding control, that's recorded
as a gap, not glossed over.*

## Registration

Act 843 requires data controllers to register with Ghana's **Data
Protection Commission (DPC)** before processing personal data, subject to
exemptions for certain categories of controller.

**Status: not yet registered.** See
`docs/compliance/records_of_processing.md`, open item #17. This is the
single most important unresolved item this mapping surfaces — everything
below assumes registration has happened or is in progress; it has not been
confirmed as complete.

## Data protection principles → implementation

| Principle | What Act 843 asks for | ImpactProof's current control |
|---|---|---|
| Accountability | A controller is responsible for complying with the Act | `docs/security_policy.md` names an owner (currently the founder, holding all roles) |
| Lawfulness of processing | A lawful basis for each processing purpose | `docs/compliance/records_of_processing.md` records a basis per data category |
| Specification of purpose | Data collected for an explicit, specified purpose | Same register; `docs/privacy_notice.md` states purposes to the customer |
| Compatibility of further processing | Data not used for a materially different purpose without new basis | No known secondary-use case exists today; nothing to flag |
| Quality of information | Accurate, complete, up to date | Not independently audited as part of this pass — accuracy is largely user-entered (submission text) |
| Openness | The data subject can know what's processed about them | `docs/privacy_notice.md` |
| Data security safeguards | Appropriate technical/organizational measures | This entire hardening pass: encryption at rest (Fernet), TLS+HSTS in transit, RLS work in progress (see `docs/security_policy.md`), audit logging, 2FA for admin |
| Data subject participation | Access/correction rights | Users can view and delete their own saved history today (My Audits page); no formal "request a copy of everything" flow exists yet — **gap** |

## Cross-border transfer

Act 843 restricts transferring personal data outside Ghana unless the
receiving jurisdiction has adequate data protection law, or another
recognized safeguard applies (consent, contractual clauses, etc.).

ImpactProof's infrastructure (Supabase, hosted in `eu-west-1`; Streamlit
Cloud/VPS; the Anthropic API) is entirely outside Ghana. **This is a
transfer that needs an articulated legal basis**, not just a technical fact
— see `docs/privacy_notice.md`'s cross-border section and
`docs/compliance/records_of_processing.md` row 6 for what's transferred to
whom. This mapping does not itself establish that basis; it flags that one
is needed and should be documented (e.g., standard contractual clauses with
Supabase/Anthropic, or relying on their own adequacy/certification
status) before or alongside DPC registration.

## Breach notification

Act 843 requires notifying the DPC and affected individuals of a breach.
See `docs/incident_response_runbook.md` for the operational process — that
document treats Ghana's requirement as "without undue delay," using the
NDPA's explicit 72-hour figure as a practical internal target rather than
assuming Ghana's own deadline is identical (verify against current DPC
guidance at the time of an actual incident, this document is not a
substitute for that).

## Open items specific to Act 843

- DPC registration (not yet done — see above).
- A formal data-subject-access-request process (today: ad hoc, via support
  contact — functional but not a named, repeatable procedure).
- Legal basis documentation for the Ghana→EU/US-adjacent cross-border
  transfer chain (Supabase/Anthropic/Streamlit).
