/**
 * supabase/functions/customer-profile-refresh/index.ts
 *
 * Supabase Edge Function — Laudon Ch.9 CRM, C1: hourly refresh of the
 * customer_profiles materialized table.
 *
 * Invoked on a schedule by pg_cron/pg_net (see
 * supabase/migrations/0025_customer_profile_refresh_cron.sql), same pattern
 * as the existing onboarding-drip function -- Streamlit Cloud and the
 * self-hosted VPS both have no built-in job scheduler, so this lives
 * entirely in Supabase.
 *
 * Deliberately thin: all the actual touch-point consolidation logic (joining
 * crm_events/payments/wa_conversations/users, computing per-account
 * aggregates) lives in ONE place -- the refresh_customer_profiles() SQL
 * function created by migration 0024. This function only checks auth and
 * invokes that RPC. Unlike onboarding-drip (which has no equivalent and
 * duplicates its HTML templates in TypeScript by necessity), there is
 * nothing to keep in sync by hand here -- the SQL function is the single
 * assembly path.
 *
 * Environment variables (set via `supabase secrets set`):
 *   CRON_SECRET                 Shared secret checked against the
 *                                Authorization header -- must match the
 *                                value passed by 0025's cron.schedule() call.
 *   SUPABASE_URL                 Auto-available in Edge Functions.
 *   SUPABASE_SERVICE_ROLE_KEY    Service role key -- bypasses RLS/grants,
 *                                 same as every other Edge Function in this
 *                                 directory.
 *
 * Deploy: `supabase functions deploy customer-profile-refresh`, then apply
 * 0025 (with <PROJECT_REF>/<CRON_SECRET> substituted) to schedule it.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const cronSecret = Deno.env.get("CRON_SECRET") ?? "";
  const auth = req.headers.get("Authorization") ?? "";
  if (!cronSecret || auth !== `Bearer ${cronSecret}`) {
    return new Response("Forbidden", { status: 401 });
  }

  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) {
    return new Response(JSON.stringify({ status: "error", reason: "missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY" }),
      { status: 500, headers: { "Content-Type": "application/json" } });
  }

  const resp = await fetch(`${url}/rest/v1/rpc/refresh_customer_profiles`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({}),
  }).catch(() => null);

  if (!resp || !resp.ok) {
    const detail = resp ? await resp.text().catch(() => "") : "fetch failed";
    return new Response(JSON.stringify({ status: "error", detail }),
      { status: 502, headers: { "Content-Type": "application/json" } });
  }

  const rowsAffected = await resp.json().catch(() => null);
  return new Response(JSON.stringify({ status: "ok", rows_affected: rowsAffected }),
    { status: 200, headers: { "Content-Type": "application/json" } });
});
