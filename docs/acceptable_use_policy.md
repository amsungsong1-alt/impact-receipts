# ImpactProof Acceptable Use Policy

*Last reviewed: 2026-08-03. This governs what you may upload or submit to
ImpactProof. See `docs/privacy_notice.md` for what happens to your data.*

## The short version

ImpactProof scores the **quality of your reporting** — how well an evidence
claim is defined, verified, and dated. It does not need, and you should not
provide, information that identifies an individual beneficiary.

## Do not upload beneficiary personal data without a lawful basis

Specifically, do not upload a document or type text into ImpactProof that
contains, for an identifiable individual:

- Full names, exact home addresses, phone numbers, or national ID numbers
- Health status, including HIV/AIDS status or any other stigmatized
  diagnosis
- Sexual orientation or gender identity, particularly where local law
  criminalizes it
- A survivor's account of gender-based violence, trafficking, or abuse
  linked to their identity
- Precise location data for someone in a conflict-affected area, where
  disclosure could expose them to physical risk
- Any other detail that could let a third party identify a specific person
  and infer something sensitive about them

**Why this matters, concretely.** ImpactProof's infrastructure (hosting,
database, the Anthropic API used for optional AI-assisted extraction) sits
outside Ghana and Nigeria. Under Ghana's Data Protection Act 843 and
Nigeria's NDPA, processing this kind of data — let alone transferring it
across a border — requires a lawful basis (typically informed consent from
the beneficiary, or another recognized ground) and, in many cases,
additional safeguards ImpactProof does not implement (this is not a
health-data or safeguarding-case-management system). If your report
contains beneficiary personal data and you upload it anyway, **you, not
ImpactProof, are the data controller responsible for that lawful basis** —
and for populations where disclosure carries physical risk (the examples
above), the consequence of getting this wrong is not just a compliance
finding, it is a real person's safety.

**What to do instead.** Aggregate: "47 women survivors of GBV received
counseling in Q2" is exactly the kind of evidence claim ImpactProof scores
well. Redact: replace a beneficiary's name with a case number your own
system tracks separately, offline, if you need individual-level detail for
your own records. Use manual entry: every scoring path in ImpactProof has a
manual-entry form that never requires uploading a source document at all.

## Other prohibited uses

- Do not use ImpactProof to generate false or fabricated evidence claims
  for a donor report. The scoring exists to reward genuine verification,
  not to help produce a more convincing but untrue narrative — and the
  fabrication guard is specifically designed to catch an AI-drafted
  narrative claiming a number that doesn't trace back to your own
  submission.
- Do not attempt to circumvent rate limits, upload size limits, or file-type
  restrictions (Laudon Ch.8, C1) — these exist to keep the service
  available and affordable for everyone, including you.
- Do not attempt to access another account's saved history, admin
  functionality, or the underlying infrastructure without authorization.
- Do not upload files containing macros, embedded executable content, or
  anything else designed to exploit the document-parsing pipeline.

## Enforcement

A violation of this policy may result in account suspension. Where the
violation involves beneficiary personal data uploaded without a lawful
basis, ImpactProof will delete the offending content on discovery and may
be required to notify you as the data controller, consistent with the
incident response runbook (`docs/incident_response_runbook.md`).

## Questions

If you're unsure whether something you want to upload crosses this line,
don't upload it — use manual entry, or contact the ImpactProof team first.
