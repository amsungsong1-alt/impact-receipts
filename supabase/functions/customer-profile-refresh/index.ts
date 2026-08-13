/**
 * supabase/functions/customer-profile-refresh/index.ts
 *
 * Supabase Edge Function — Laudon Ch.9 CRM, C1 + C6: hourly refresh of the
 * customer_profiles materialized table, plus the one lifecycle trigger that
 * can't fire from Python: at_risk_reengagement.
 *
 * Invoked on a schedule by pg_cron/pg_net (see
 * supabase/migrations/0025_customer_profile_refresh_cron.sql), same pattern
 * as the existing onboarding-drip function -- Streamlit Cloud and the
 * self-hosted VPS both have no built-in job scheduler, so this lives
 * entirely in Supabase.
 *
 * Step 1 (C1) is deliberately thin: all the actual touch-point consolidation
 * logic (joining crm_events/payments/wa_conversations/users, computing
 * per-account aggregates) lives in ONE place -- the refresh_customer_profiles()
 * SQL function created by migration 0024. This function only checks auth and
 * invokes that RPC.
 *
 * Step 2 (C6, at_risk_reengagement) is the ONE deliberate exception to
 * "assembly logic lives in Python only" (utils/lifecycle_triggers.py's
 * module docstring explains why: the other 4 lifecycle triggers fire live
 * during a page load; this one, by definition, needs to reach an account
 * that ISN'T currently visiting). It duplicates exactly ONE narrow boolean
 * condition from utils/crm.py::compute_behavioral_segment()'s at_risk
 * branch -- not the full 7-segment engine -- and REPORTING_MONTHS below
 * MUST be kept in sync by hand with knowledge/mel_calendar.yaml if that
 * file changes (same trade-off already accepted for onboarding-drip's
 * hand-duplicated HTML templates).
 *
 * Environment variables (set via `supabase secrets set`):
 *   CRON_SECRET                 Shared secret checked against the
 *                                Authorization header -- must match the
 *                                value passed by 0025's cron.schedule() call.
 *   SUPABASE_URL                 Auto-available in Edge Functions.
 *   SUPABASE_SERVICE_ROLE_KEY    Service role key -- bypasses RLS/grants,
 *                                 same as every other Edge Function in this
 *                                 directory.
 *   RESEND_API_KEY / RESEND_FROM Same Resend account as onboarding-drip,
 *                                 duplicated into this function's own secret
 *                                 store (separate from Streamlit's and from
 *                                 onboarding-drip's own secrets).
 *   APP_BASE_URL                 Canonical app URL for the email's link.
 *
 * Deploy: `supabase functions deploy customer-profile-refresh`, then apply
 * 0025 (with <PROJECT_REF>/<CRON_SECRET> substituted) to schedule it.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

// KEEP IN SYNC BY HAND with knowledge/mel_calendar.yaml's reporting_months --
// see this file's module docstring for why this one narrow duplication exists.
const REPORTING_MONTHS = [3, 6, 9, 12, 1];
const AT_RISK_QUIET_DAYS = 30;
const AT_RISK_MIN_ASSESSMENTS = 2;
const TRIGGER_COOLDOWN_DAYS = 30;

async function refreshCustomerProfiles(url: string, key: string): Promise<{ ok: boolean; detail: unknown }> {
  const resp = await fetch(`${url}/rest/v1/rpc/refresh_customer_profiles`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({}),
  }).catch(() => null);
  if (!resp || !resp.ok) {
    return { ok: false, detail: resp ? await resp.text().catch(() => "") : "fetch failed" };
  }
  return { ok: true, detail: await resp.json().catch(() => null) };
}

async function fetchAtRiskCandidates(url: string, key: string): Promise<Array<{ email: string }>> {
  const cutoff = new Date(Date.now() - AT_RISK_QUIET_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const qs = new URLSearchParams({
    total_assessments: `gte.${AT_RISK_MIN_ASSESSMENTS}`,
    last_active_at: `lte.${cutoff}`,
    select: "email",
  });
  const resp = await fetch(`${url}/rest/v1/customer_profiles?${qs.toString()}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
  }).catch(() => null);
  if (!resp || !resp.ok) return [];
  return await resp.json().catch(() => []);
}

async function fetchRecentlyTriggered(url: string, key: string): Promise<Set<string>> {
  const cutoff = new Date(Date.now() - TRIGGER_COOLDOWN_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const qs = new URLSearchParams({
    trigger_name: "eq.at_risk_reengagement",
    fired_at: `gte.${cutoff}`,
    select: "email",
  });
  const resp = await fetch(`${url}/rest/v1/lifecycle_triggers_log?${qs.toString()}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
  }).catch(() => null);
  if (!resp || !resp.ok) return new Set();
  const rows: Array<{ email: string }> = await resp.json().catch(() => []);
  return new Set(rows.map((r) => r.email));
}

async function recordTriggerFired(url: string, key: string, email: string): Promise<void> {
  await fetch(`${url}/rest/v1/lifecycle_triggers_log`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json", Prefer: "return=minimal" },
    body: JSON.stringify({ email, trigger_name: "at_risk_reengagement" }),
  }).catch(() => {/* non-blocking -- a failed log write just risks one extra resend next hour */});
}

function reengagementHtml(appUrl: string): string {
  return `
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>Still on track for this reporting cycle?</h2>
  <p style='font-size:0.9rem;'>
    It's been a while since your last ImpactProof check, and this looks like a reporting
    month for teams like yours. If a donor report is coming up, running a quick check now
    can catch evidence gaps before they cost you a rejection.
  </p>
  <p style='margin-top:20px;'>
    <a href='${appUrl}/'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Run a check &rarr;
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;'>
    ImpactProof &middot; Built in Accra, Ghana
  </p>
</div>`;
}

async function sendReengagementEmail(toEmail: string, appUrl: string): Promise<boolean> {
  const apiKey = Deno.env.get("RESEND_API_KEY");
  if (!apiKey) return false;
  const rawFrom = Deno.env.get("RESEND_FROM") ?? "";
  const m = rawFrom.match(/<([^>]+)>/);
  const fromAddress = `ImpactProof <${m ? m[1] : (rawFrom.trim() || "onboarding@resend.dev")}>`;
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: fromAddress, to: [toEmail],
      subject: "Still on track for this reporting cycle?",
      html: reengagementHtml(appUrl),
    }),
  }).catch(() => null);
  return !!resp && (resp.status === 200 || resp.status === 201);
}

serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  // .trim() -- the Dashboard's secret Value field is a multi-line textarea,
  // which can silently pick up a trailing newline/space on paste; trimming
  // both sides of the comparison makes this resilient to that without
  // requiring the secret to be re-entered with surgical precision.
  const cronSecret = (Deno.env.get("CRON_SECRET") ?? "").trim();
  const auth = (req.headers.get("Authorization") ?? "").trim();
  if (!cronSecret || auth !== `Bearer ${cronSecret}`) {
    return new Response("Forbidden", { status: 401 });
  }

  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) {
    return new Response(JSON.stringify({ status: "error", reason: "missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY" }),
      { status: 500, headers: { "Content-Type": "application/json" } });
  }

  const refreshResult = await refreshCustomerProfiles(url, key);
  if (!refreshResult.ok) {
    return new Response(JSON.stringify({ status: "error", detail: refreshResult.detail }),
      { status: 502, headers: { "Content-Type": "application/json" } });
  }

  // C6 -- at_risk_reengagement, only during a configured reporting month.
  let reengagementSent = 0;
  const currentMonth = new Date().getUTCMonth() + 1;
  if (REPORTING_MONTHS.includes(currentMonth)) {
    const appUrl = (Deno.env.get("APP_BASE_URL") ?? "https://impact-integrity-diagnostic.streamlit.app")
      .replace(/\/$/, "");
    const [candidates, alreadyTriggered] = await Promise.all([
      fetchAtRiskCandidates(url, key),
      fetchRecentlyTriggered(url, key),
    ]);
    for (const c of candidates) {
      if (alreadyTriggered.has(c.email)) continue;
      const ok = await sendReengagementEmail(c.email, appUrl);
      if (ok) {
        await recordTriggerFired(url, key, c.email);
        reengagementSent++;
      }
    }
  }

  return new Response(
    JSON.stringify({ status: "ok", rows_affected: refreshResult.detail, at_risk_reengagement_sent: reengagementSent }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});
