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
