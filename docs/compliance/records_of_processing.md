# Records of Processing Activities

*Last reviewed: 2026-08-03, as part of the Laudon Ch.8 hardening pass. This
is the working register both Act 843 and the NDPA expect a controller to
be able to produce. Keep it in sync with `docs/privacy_notice.md` (the
customer-facing summary of the same facts) whenever either changes.*

| # | Data category | Why processed (purpose) | Lawful basis | Where stored | Who can access | Retention | Cross-border transfer |
|---|---|---|---|---|---|---|---|
| 1 | Account email | Login (magic link + OTP), billing, transactional email | Contract necessity (providing the service the account signed up for) | Supabase Postgres (`users`) | App backend (email-scoped queries); admin dashboard (role-gated + 2FA) | Until account deletion request (no self-service account deletion exists yet — open item, row 12) | Supabase (hosted outside Ghana/Nigeria; region `eu-west-1`, confirmed via live project lookup 2026-08-03) |
| 2 | Uploaded document content | Extracting structured fields for scoring convenience | Consent (upload is opt-in; manual entry is always available) | **Nowhere — in-memory only, enforced by `test_document_retention.py`** | The extraction request itself, transiently; Anthropic API (see row 6) if the AI extraction path is used | None — discarded when extraction finishes or the session ends | Transient only, during the extraction call itself, to Anthropic (if used) |
| 3 | Assessment submissions/evaluations (if saved) | Score history, re-download, benchmark comparison | Consent (explicit "save to my account" checkbox, opt-in per audit) | Supabase Postgres (`audits.submissions_json`/`evaluations_json`), Fernet-encrypted at rest | App backend (email-scoped); account owner via My Audits; not admin-readable without the decryption key and a specific reason | User-controlled — deletable anytime via "Danger Zone" (immediate, irreversible); no automatic expiry today (see row 13) | Same as row 1 |
| 4 | Logframe Library indicator text | Reusable indicator templates across an account's future reports | Consent (user-created content) | Supabase Postgres (`logframe_library_items`), 5 free-text fields Fernet-encrypted | Same as row 3 | Deletable per-library by the account owner | Same as row 1 |
| 5 | Payment records | Billing, receipts, tax/accounting | Contract necessity + legal obligation (accounting retention) | Supabase Postgres (`payments`), written by the Paystack webhook Edge Function | App backend; Paystack (payment processor) | Retained indefinitely — "independent tax/accounting retention" (documented in `CLAUDE.md`, no specific period cited — **open item, row 14**) | Paystack (payment processor, transfer terms governed by Paystack's own agreement, not audited as part of this pass) |
| 6 | Document text / submission text sent to the Anthropic API | AI-assisted extraction and optional narrative generation | Consent (AI-assisted features are opt-in; deterministic scoring never requires this) | Not stored by ImpactProof; Anthropic's own retention policy applies on their side (see `docs/privacy_notice.md` — **verify current terms before citing to a customer's compliance officer, open item row 15**) | Anthropic (data processor role, per their Commercial Terms of Service) | Governed by Anthropic's own policy, not ImpactProof's | Anthropic API infrastructure (jurisdiction per Anthropic's own terms) |
| 7 | WhatsApp conversation logs | Auto-reply support routing (result-review, pricing, payment support triage) | Legitimate interest (customer support) | Supabase Postgres (`wa_conversations`) | App backend; WhatsApp Cloud API (Meta) as the transport | User-deletable via `delete_wa_conversations()` (part of the account purge flow) | WhatsApp Cloud API (Meta infrastructure) |
| 8 | CRM/behavioral events, customer segments | Product analytics, lifecycle email triggers, churn/segment dashboards | Legitimate interest | Supabase Postgres (`crm_events`, `customer_profiles`, `customer_segment_history`) | App backend; admin dashboard (role-gated) | User-deletable via `purge_account_crm_events()` | Same as row 1 |
| 9 | Access/audit log | Security monitoring, incident investigation, abuse/rate-limit enforcement | Legitimate interest (security) | Supabase Postgres (`access_log`), append-only + hash-chained (`0051_access_log_hash_chain.sql`) | `app_audits_rw` role only (insert-only grant); no UI exposes raw rows | Not currently purged — **open item, row 16** | Same as row 1 |
| 10 | TOTP 2FA secret (internal staff only) | Admin dashboard 2FA | Contract/legitimate interest (protecting customer data admin can access) | Supabase Postgres (`users.totp_secret`), Fernet-encrypted | App backend only, decrypted only at verification time | Until 2FA is disabled/account role changes | Same as row 1 |
| 11 | Onboarding/lifecycle email history | Drip campaigns, re-engagement triggers | Legitimate interest | Supabase Postgres (`users.day3_email_sent_at`/`day7_email_sent_at`), `lifecycle_triggers_log` | App backend, Supabase Edge Functions (own secret store) | Same lifecycle as the account | Resend (email delivery provider) |

## Open items

| # | Item | Owner | Target date |
|---|---|---|---|
| 12 | No self-service full account deletion (only content purge exists — `users` row itself and `payments`/`sessions`/`login_tokens` are explicitly out of scope of today's purge) | Founder | Not yet scheduled |
| 13 | No automatic retention/expiry period for saved `audits`/`logframe_libraries` — deletion is user-initiated only | Founder | Not yet scheduled |
| 14 | No specific retention *period* documented for `payments` beyond "accounting purposes" | Founder | Not yet scheduled |
| 15 | Anthropic's exact current Commercial Terms/DPA language not re-verified against a signed agreement — `docs/privacy_notice.md`'s summary should be checked against Anthropic's live terms before being cited to a customer's compliance officer, and a formal DPA/Zero Data Retention agreement considered | Founder | Not yet scheduled |
| 16 | No retention/purge policy for `access_log` itself (grows indefinitely) | Founder | Not yet scheduled |
| 17 | Ghana DPC registration status | Founder | **Not yet registered — confirm requirement and register** |
| 18 | Nigeria NDPA (NDPC) registration status | Founder | **Not yet registered — confirm requirement and register** |
| 19 | `pg_net` extension installed in the `public` schema (Supabase advisor finding, 2026-08-03) — needs a call-site audit before relocating, not fixed in this pass (see `0052_harden_function_grants.sql`'s own comment) | Founder | Not yet scheduled |
| 20 | Backup/PITR configuration not yet verified against the live project's actual plan tier; no restore has been performed (see `docs/disaster_recovery.md`) | Founder | **Blocking the DR acceptance criterion — see that document's "Next action"** |

Rows 17 and 18 are the two items most directly required by the source
material for this hardening pass (Act 843 / NDPA registration) and are
recorded here, unresolved, rather than assumed complete.
