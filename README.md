# Impact-Receipts

A pre-submission confidence checker for MEL (Monitoring, Evaluation & Learning) managers. Stress-test a reported result before submitting it.

## What it does

Evaluates one result claim across three dimensions:

- **Clarity of Claim** — Does it specify a measurable unit, timeframe, and target group?
- **Strength of Evidence** — Is the evidence direct, recent, and verifiable?
- **Independent Review** — Has it been peer-reviewed internally or externally?

You receive a confidence label (**Strong / Moderate / Weak / Incomplete**) plus a specific checklist of what to fix before submission, and a downloadable markdown report.

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
