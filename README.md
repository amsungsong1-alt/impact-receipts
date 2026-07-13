# ImpactProof

Upload your donor report. Score every result. Submit with confidence.

## What it does

Evaluates one result claim across **two axes** (each 0–5.0), using eight sub-dimensions:

**Confidence axis** — how much should we trust the evidence?
- Directness — how directly does the evidence link activities to the result?
- Verification — how independently has the evidence been reviewed?
- Recency — how current is the evidence relative to the reporting period?

**Clarity axis** — can someone else interpret this result the same way?
- Definition — is the unit, timeframe, and target group specified?
- Measurement — is the collection method and sampling approach disclosed?
- Integrity — is the data complete with a clear audit trail?
- Scope — does the coverage match the geographic and demographic claim?
- Governance — is there a named owner and stated decision use?

You receive a dual-axis score, a 7-state diagnostic verdict (STRONG / NEEDS REFINEMENT / MISLEADING / UNDEREVIDENCED / FUNDAMENTALLY WEAK / INCOMPLETE / INVALID INPUT), a prioritised fix list, and a downloadable report. This is a heuristic pre-submission check, not an expert audit — your donor reviewer makes the final determination.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Environment variables

Copy `.env.example` to `.env` and fill in your key if you enable the Claude API evaluator:

```
ANTHROPIC_API_KEY=your_key_here
```

On Streamlit Community Cloud, add this key under **Settings → Secrets**.


## Environment Variables

Set in `.streamlit/secrets.toml` (local) or Streamlit Cloud **App settings → Secrets**:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for Instant Report Check |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anon/public key |
| `PAYSTACK_SECRET_KEY` | Yes | Paystack secret key (payments) |
| `PAYSTACK_PUBLIC_KEY` | Yes | Paystack public key |
| `PAYSTACK_PLAN_PROFESSIONAL_MONTHLY` | No | Professional monthly Plan code from `scripts/setup_paystack_plans.py`. Subscribe buttons fall back to a one-off charge if unset. |
| `PAYSTACK_PLAN_PROFESSIONAL_ANNUAL` | No | Professional annual Plan code, same script. |
| `PAYSTACK_PLAN_AGENCY_MONTHLY` | No | Agency monthly Plan code, same script. |
| `APP_BASE_URL` | Yes | Your deployed app URL (used for Paystack callback, magic-link login emails) |
| `RESEND_API_KEY` | No | Enables magic-link/OTP login emails and results/welcome emails via Resend. Login falls back to unverified email entry if unset. |
| `RESEND_FROM` | No | From: address for those emails, e.g. `ImpactProof <you@yourdomain.com>`. |
| `ADMIN_PASSPHRASE` | No | Enables the hidden `?admin=1` usage-metrics view. Leave unset to disable it entirely. |

### Supabase Setup

Apply the migration files in `supabase/migrations/` in order — either `supabase db push`
(recommended; requires the [Supabase CLI](https://supabase.com/docs/guides/cli) linked to your
project), or paste each file's SQL into the Supabase SQL editor by hand, oldest first. This
creates/extends the `users`, `examples`, `wa_conversations`, `login_tokens`, `sessions`, and
`payments` tables plus the `increment_free_checks` function. Do not hand-write new `ALTER TABLE`
statements against a running project — add a new numbered file to `supabase/migrations/` instead,
so the schema stays reproducible from a clean project.

### Webhook setup

Two Supabase Edge Functions need their own deploy step, separate from Streamlit Cloud's
auto-deploy-on-push:

```bash
supabase functions deploy whatsapp-webhook
supabase functions deploy paystack-webhook
```

Each function reads its own secrets via `supabase secrets set KEY=value` — **not** the same
store as Streamlit's `st.secrets`/App settings, even when a value (e.g. `PAYSTACK_SECRET_KEY`)
is the same key duplicated into both places. After deploying, register each function's URL with
its provider:

- WhatsApp: Meta developer portal → your app → Webhooks →
  `https://<PROJECT_REF>.supabase.co/functions/v1/whatsapp-webhook`
- Paystack: Dashboard → Settings → API Keys & Webhooks →
  `https://<PROJECT_REF>.supabase.co/functions/v1/paystack-webhook`

Deploy and register `paystack-webhook` *before* pasting real `PAYSTACK_PLAN_*` codes into
Streamlit secrets — otherwise a subscription's renewal/failure/cancellation events have nowhere
to land until the webhook exists.

## Run Locally

```bash
streamlit run app.py
```
