# ImpactProof Disaster Recovery Plan

*Last reviewed: 2026-08-03. DR = getting the systems back. See
`docs/business_continuity.md` for keeping the business running while that
happens — different document, different owner in a larger team, per
Laudon's own distinction between the two.*

## What's actually confirmed vs. still open

This section is written honestly rather than optimistically: some of it was
verified directly against the live project during this hardening pass
(via the Supabase MCP integration, read-only calls only); the rest is an
explicit open item, not a filled-in assumption.

**Confirmed (2026-08-03):**
- Production project: `amsungsong1-alt's Project` (ref `mikgzzsphsyveeaelpap`),
  region `eu-west-1`, status `ACTIVE_HEALTHY`, Postgres 17.6 (GA release
  channel).
- Only one migration is recorded in Supabase's own migration-history table
  (`export_verifications`, 2026-07-25) — every other schema change in this
  repo's `supabase/migrations/` was applied by hand via the SQL editor, not
  tracked by Supabase's migration system. **This means Supabase's own
  migration history is not a reliable record of current schema state** —
  `supabase/migrations/*.sql` in this repo is the actual source of truth,
  and should be treated as such (i.e., kept it in sync manually,
  since the platform won't do it for you).
- Confirmed via Supabase's own security advisor: RLS is disabled on every
  public table, matching this repo's own documented architecture (see
  `supabase/migrations/0005_disable_rls.sql`) — not a surprise, but useful
  independent confirmation the two pictures agree.

**Open items (need the account owner to check/decide, not verifiable via
the tools available during this pass):**
- **Backup/PITR configuration and retention window.** Check
  Supabase Dashboard → Project Settings → Database → Backups. Free-tier
  projects get daily backups with a short retention window and no
  point-in-time recovery; Pro-tier-and-up projects can enable PITR. Record
  whichever is actually configured here once checked — do not assume.
- **An actual restore has not yet been performed.** Supabase supports
  restoring an on-demand backup to a *new* project (safe — does not touch
  the live one) on paid plans, and PITR-to-a-branch on plans with branching
  enabled. Both cost money and were not attempted during this pass without
  first confirming the plan tier and getting explicit sign-off, per this
  project's normal practice of not taking cost-incurring or
  production-adjacent actions unilaterally. **This is the one item in the
  entire Ch.8 hardening effort that requires a human decision + a few
  minutes in the Supabase dashboard before it can be marked done** — see
  "Next action" below.
- **RTO/RPO targets** below are proposed, not yet tested against a real
  restore. Revise them once the first real restore's actual wall-clock time
  is known.

## Proposed RTO/RPO targets

| Metric | Target | Basis |
|---|---:|---|
| RPO (Recovery Point Objective) | ≤ 24 hours | Assumes daily backups at minimum; tighten to near-zero if PITR is confirmed enabled |
| RTO (Recovery Time Objective) | ≤ 4 hours | Restore-to-new-project + repoint `SUPABASE_URL`/`SUPABASE_DB_URL` in Streamlit Cloud secrets; no code deploy needed for a DB-only incident |

## Restore procedure (database)

1. In the Supabase Dashboard, restore the most recent backup (or a PITR
   point, if enabled) to a **new** project — never restore in place over
   production as the first step; verify the restored copy first.
2. Run the full local test suite (`python test_*.py`) against the restored
   copy's connection string to sanity-check schema integrity.
3. Run `scripts/verify_audit_chain.py` against the restored `access_log` to
   confirm the hash chain is intact through the restore point (a restore
   should never itself break the chain — if it does, the backup mechanism
   or restore process has a data-integrity bug worth escalating to
   Supabase support).
4. Update `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_DB_URL` in
   Streamlit Cloud's secrets (and the VPS `.env`, if that path is active)
   to point at the restored project.
5. Redeploy (Streamlit Cloud: push any trivial commit or use "Reboot app";
   VPS: `docker compose restart`).
6. Record the actual wall-clock time from step 1 to a verified-working app
   in step 5 — this is the real RTO, replacing the proposed target above.

## Streamlit Cloud outage fallback

The VPS/Docker path (`docker-compose.yml`, `nginx/`, `scripts/deploy_vps.sh`)
is the formal fallback if Streamlit Community Cloud itself is down or
unreachable, not just the database. It's already deployment-ready
(`Dockerfile` builds the same `app.py`) — the gap is that it isn't running
anywhere by default, so "activate the fallback" means: provision a VPS (if
one isn't already kept warm), point DNS at it, and run
`scripts/deploy_vps.sh`. Whether to keep a VPS warm and idle at all times
(faster failover, ongoing cost) versus provisioning on demand (slower
failover, zero idle cost) is a decision for the founder to make explicitly,
not a default this document should assume.

## Next action

Before this document can honestly claim the DR acceptance criterion is
met: check the Supabase Dashboard's Backups page for the current plan's
actual backup/PITR configuration, and — if on a plan that supports it —
perform one real restore-to-a-new-project following the procedure above,
recording the actual time taken. Update the "Confirmed" section above with
the result.
