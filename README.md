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
| `SUPABASE_DB_URL` | No | Direct Postgres connection string for `utils/audits.py`'s SQLAlchemy connection — a separate access path from `SUPABASE_URL`/`SUPABASE_ANON_KEY`'s REST API. **Use the `app_audits_rw` role's connection string, not the default `postgres` superuser one** — `app_audits_rw` is created by `supabase/migrations/0009_least_privilege_role.sql` and is scoped only to this module's own tables; a superuser bypasses every GRANT/REVOKE check, which silently defeats the `access_log` table's append-only guarantee. Dashboard → Project Settings → Database → Connection string, **Transaction pooler** mode recommended. Saved audit history, Logframe Library, and the comparison benchmark are unavailable if unset; nothing else is affected. |
| `AUDIT_ENCRYPTION_KEY` | No | Fernet key encrypting saved audit content and Logframe Library items at rest (`utils/crypto.py`). Generate once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Losing this key makes all encrypted content permanently unrecoverable** — back it up somewhere outside Supabase/Streamlit secrets. Saving an audit/library item fails closed (stores nothing) if unset. |
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
creates/extends the `users`, `examples`, `wa_conversations`, `login_tokens`, `sessions`,
`payments`, `audits`, `logframe_libraries`, `logframe_library_items`, `audit_aggregate_stats`,
and `access_log` tables, plus the `increment_free_checks` function and the least-privilege
`app_audits_rw` Postgres role. Do not hand-write new `ALTER TABLE` statements against a running
project — add a new numbered file to `supabase/migrations/` instead, so the schema stays
reproducible from a clean project.

`0009_least_privilege_role.sql` creates `app_audits_rw` but does **not** set its password (never
commit a password to this repo) — after applying it, set one by hand:

```sql
ALTER ROLE app_audits_rw WITH PASSWORD '<generate a strong random password>';
```

Then use that role's connection string for `SUPABASE_DB_URL`, not the default `postgres`
superuser one — see that row in the secrets table above for why this matters. If `CREATE ROLE`
is rejected on your project (some hosted Supabase plans restrict this to the dashboard), create
`app_audits_rw` via **Dashboard → Database → Roles** instead and skip straight to the `GRANT`
statements in that migration file.

### Webhook setup

Two Supabase Edge Functions need their own deploy step, separate from Streamlit Cloud's
auto-deploy-on-push:

```bash
supabase functions deploy whatsapp-webhook
supabase functions deploy paystack-webhook
supabase functions deploy onboarding-drip
```

Each function reads its own secrets via `supabase secrets set KEY=value` — **not** the same
store as Streamlit's `st.secrets`/App settings, even when a value (e.g. `PAYSTACK_SECRET_KEY`)
is the same key duplicated into both places. After deploying, register each function's URL with
its provider:

- WhatsApp: Meta developer portal → your app → Webhooks →
  `https://<PROJECT_REF>.supabase.co/functions/v1/whatsapp-webhook`
- Paystack: Dashboard → Settings → API Keys & Webhooks →
  `https://<PROJECT_REF>.supabase.co/functions/v1/paystack-webhook`
- `onboarding-drip` has no external provider to register with — it's invoked on a schedule
  (see "Scheduling" below), not by an inbound webhook.

Deploy and register `paystack-webhook` *before* pasting real `PAYSTACK_PLAN_*` codes into
Streamlit secrets — otherwise a subscription's renewal/failure/cancellation events have nowhere
to land until the webhook exists.

`onboarding-drip` needs its own secrets set (separate from Streamlit's, same caveat as above):

```bash
supabase secrets set CRON_SECRET=<generate a strong random value>
supabase secrets set RESEND_API_KEY=<same value as Streamlit's RESEND_API_KEY secret>
supabase secrets set RESEND_FROM=<same value as Streamlit's RESEND_FROM secret>
supabase secrets set APP_BASE_URL=<same value as Streamlit's APP_BASE_URL secret>
```

### Scheduling (pg_cron)

`supabase/migrations/0014_pg_cron_onboarding_drip.sql` schedules `onboarding-drip` to run
hourly via `pg_cron`/`pg_net`, checking for accounts due their day-3 or day-7 onboarding email.
This is the only scheduling mechanism in this stack that reaches signups from *both*
deployments (Streamlit Cloud and the self-hosted VPS), since it lives entirely in Supabase
rather than a host crontab tied to one deployment (compare the TLS-renewal crontab below,
which is VPS-only). Before applying `0014`, replace its `<PROJECT_REF>` and `<CRON_SECRET>`
placeholders by hand in the SQL editor with your real project ref and the same `CRON_SECRET`
value set above — never commit the real value to the migration file. If `pg_cron`/`pg_net`
enablement is rejected (some hosted plans restrict this), enable both extensions via
**Dashboard → Database → Extensions** first, then run just the `cron.schedule(...)` call.

### Docker / VPS deployment

An alternative to Streamlit Cloud's auto-deploy — both share the same Supabase backend and Edge
Functions unchanged, and every secret above works the same way, just supplied via `.env` instead
of Streamlit's Secrets UI.

1. **Copy `.env.example` to `.env`** and fill in every value (the script refuses to run with a
   missing `.env`, but won't validate individual values — blank Paystack Plan codes, for
   instance, just fall back to one-off charges rather than erroring).
2. **Point your domain's A record** at the VPS's IP address before continuing — Let's Encrypt
   needs this to succeed.
3. **First-ever TLS bootstrap** (two phases, since Nginx needs to already be serving the ACME
   challenge before certbot can obtain a certificate against it):
   ```bash
   # Phase 1: bring Nginx up HTTP-only (comment out the ssl_certificate lines
   # in nginx/conf.d/impactproof.conf first, or the container will fail to
   # start with no certificate yet on disk)
   docker compose up -d nginx

   # Phase 2: obtain the certificate, then uncomment the ssl_certificate
   # lines and reload
   docker compose run --rm --entrypoint certbot certbot certonly \
     --webroot -w /var/www/certbot -d YOUR_DOMAIN_HERE \
     --email you@example.com --agree-tos --no-eff-email
   docker compose exec nginx nginx -s reload
   ```
4. **Deploy**: `./scripts/deploy_vps.sh` — installs Docker if missing, builds, and starts
   everything with `restart: unless-stopped`.
5. **Certificate renewal** — `restart: unless-stopped` does not schedule anything on its own; add
   a host crontab entry (certbot's own recommended cadence is twice daily):
   ```bash
   0 3,15 * * * cd /path/to/impact-receipts && docker compose run --rm --entrypoint certbot certbot renew --webroot -w /var/www/certbot && docker compose exec nginx nginx -s reload
   ```

Replace `YOUR_DOMAIN_HERE` in `nginx/conf.d/impactproof.conf` (both server blocks) with your real
domain before step 3. OSS Nginx has no active upstream health check (that's an Nginx-Plus
feature) — recovery relies on the Dockerfile's `HEALTHCHECK` + `restart: unless-stopped`, so
Nginx may 502 for the short window while the `app` container restarts.

## Run Locally

```bash
streamlit run app.py
```
