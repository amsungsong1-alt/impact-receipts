# Nigeria Data Protection Act, 2023 (NDPA) — Control Mapping

*Last reviewed: 2026-08-03. This maps the NDPA's general structure (as
publicly understood — not a substitute for reading the current statutory
text, NDPC regulations, or taking Nigerian legal advice) to what
ImpactProof actually implements. Where a requirement has no corresponding
control, that's recorded as a gap, not glossed over.*

## Registration

The NDPA requires data controllers/processors meeting certain thresholds
("data controllers or processors of major importance," per NDPC criteria —
often tied to the volume/sensitivity of data processed or sector) to
register with the **Nigeria Data Protection Commission (NDPC)**.

**Status: not yet registered, and threshold applicability not yet
formally assessed.** See `docs/compliance/records_of_processing.md`, open
item #18. Before or alongside registering, determine whether ImpactProof
currently meets the "major importance" threshold given its Nigerian user
base — this assessment has not been performed as part of this hardening
pass and needs Nigerian legal input.

## Lawful bases for processing

The NDPA recognizes several lawful bases (consent, contractual necessity,
legal obligation, vital interest, public interest/official function,
legitimate interest). ImpactProof's current bases per data category are
recorded in `docs/compliance/records_of_processing.md` — predominantly
consent (opt-in features: document upload, saving history) and contractual
necessity (account/billing).

## Data subject rights

| Right | NDPA | ImpactProof's current control |
|---|---|---|
| Access | Right to confirm what data is held and obtain a copy | Ad hoc via support contact — no formal self-service export yet (**gap**, same as the Act 843 mapping) |
| Rectification | Correct inaccurate data | Users can edit their own profile/account fields directly |
| Erasure | Delete personal data on request | "Danger Zone" purge (audits, libraries, drafts, CRM events, WhatsApp logs) — but not the `users` row itself, `payments`, or `sessions`/`login_tokens` (**gap**, see records-of-processing item #12) |
| Restriction of processing | Limit processing while a dispute is resolved | No formal mechanism — **gap** |
| Objection | Object to processing based on legitimate interest | No formal mechanism beyond account deletion — **gap** |
| Data portability | Receive data in a portable format | Saved audits are downloadable (PDF/Word export) — partial coverage, not a full structured-data export of everything held |

## Breach notification

The NDPA requires notifying the NDPC **within 72 hours** of becoming aware
of a breach likely to result in a risk to data subjects' rights, and
notifying affected individuals without undue delay where the risk is high.
This is the deadline `docs/incident_response_runbook.md` builds its
timeline around directly — verify the exact current regulatory text (this
summary is deliberately conservative, not a legal citation) before relying
on it during a real incident.

## Cross-border transfer

The NDPA restricts transferring personal data outside Nigeria unless the
receiving country/organization has an adequate level of protection, or
another recognized safeguard applies (consent, contractual clauses,
certification, etc. — mechanisms broadly similar in shape to the GDPR's,
though NDPC's specific adequacy list/guidance should be checked directly).
Same underlying transfer chain as Act 843's mapping (Supabase `eu-west-1`,
Anthropic, Streamlit Cloud/VPS) — same open item: an articulated legal
basis for the transfer needs to be documented, not just assumed from the
technical architecture.

## Open items specific to the NDPA

- "Major importance" threshold assessment (not yet performed).
- NDPC registration (not yet done, pending the above).
- A named DPO contact point specifically for Nigerian data subjects (today:
  the same single founder role as everywhere else in this document set —
  the NDPA may require a more formal DPO designation past a certain scale;
  reassess as the Nigerian user base grows).
- Data subject rights beyond access/erasure (restriction, objection,
  portability) have no dedicated mechanism yet.
