# Impact-Receipts

A pre-submission confidence checker for MEL (Monitoring, Evaluation & Learning) managers. Stress-test a reported result before submitting it.

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
| `APP_BASE_URL` | Yes | Your deployed app URL (used for Paystack callback) |

### Supabase Setup

Run this SQL in your Supabase SQL editor:

```sql
create table users (
  email text primary key,
  free_checks_used int default 0,
  is_paid bool default false,
  paid_until date,
  created_at timestamptz default now()
);

create table examples (
  id bigserial primary key,
  field_name text not null,
  sector text not null,
  value text not null,
  created_at timestamptz default now()
);
```

## Run Locally

```bash
streamlit run app.py
```
