/**
 * supabase/functions/onboarding-drip/index.ts
 *
 * Supabase Edge Function — Onboarding email drip (day-3 case study, day-7
 * upgrade offer)
 *
 * Invoked on a schedule by pg_cron/pg_net (see
 * supabase/migrations/0014_pg_cron_onboarding_drip.sql), not by an external
 * webhook provider like the other two functions in this directory. This is
 * the only scheduling mechanism in this stack that reaches signups from
 * BOTH deployment paths (Streamlit Cloud and the self-hosted VPS), since it
 * lives entirely in Supabase rather than a host crontab tied to one
 * deployment (compare README.md's TLS-renewal crontab, which is VPS-only).
 *
 * Each run: queries users table for accounts that crossed the 3-day or
 * 7-day mark since signup and haven't been sent that stage's email yet
 * (day3_email_sent_at/day7_email_sent_at is null), sends via Resend, and
 * marks the column on success. Deliberately at-least-once, not exactly-
 * once: a failed send leaves the column null so the next hourly run
 * retries -- different from utils/email_otp.py's single-attempt convention
 * (a user-facing synchronous action), because this is a background job
 * with a natural periodic retry.
 *
 * The HTML templates below are TypeScript string-literal copies of
 * utils/email_otp.py's send_case_study_email()/send_upgrade_offer_email()
 * -- Deno can't import that Python module, and this codebase has no shared
 * templating layer (matches its existing per-function inline-HTML
 * convention rather than introducing one). Keep both files' copy in sync
 * by hand if it changes.
 *
 * Environment variables (set via `supabase secrets set`, NOT the same store
 * as Streamlit's own secrets):
 *   CRON_SECRET                Shared secret this function checks against
 *                              the Authorization header -- see 0014's
 *                              cron.schedule() call, which must pass the
 *                              same value.
 *   RESEND_API_KEY             Same key used by utils/email_otp.py, but
 *   RESEND_FROM                  duplicated into this function's own secret
 *                                 store (separate from Streamlit's).
 *   APP_BASE_URL                Canonical app URL for links in the emails.
 *   SUPABASE_URL                Auto-available in Edge Functions
 *   SUPABASE_SERVICE_ROLE_KEY   Service role key for DB reads/writes
 *
 * Deploy: `supabase functions deploy onboarding-drip`, then apply 0014 (with
 * <PROJECT_REF>/<CRON_SECRET> substituted) to schedule it.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

const APP_NAME = "ImpactProof";

// ---------------------------------------------------------------------------
// Supabase REST helpers
// ---------------------------------------------------------------------------

async function fetchDueUsers(column: "day3_email_sent_at" | "day7_email_sent_at", days: number)
  : Promise<Array<{ email: string; unsubscribe_token: string }>> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) return [];
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const qs = new URLSearchParams({
    [column]: "is.null",
    created_at: `lte.${cutoff}`,
    marketing_opt_out: "eq.false",
    select: "email,unsubscribe_token",
  });
  const resp = await fetch(`${url}/rest/v1/users?${qs.toString()}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
  }).catch(() => null);
  if (!resp || !resp.ok) return [];
  return await resp.json().catch(() => []);
}

async function markSent(email: string, column: "day3_email_sent_at" | "day7_email_sent_at"): Promise<void> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key || !email) return;
  await fetch(`${url}/rest/v1/users?email=eq.${encodeURIComponent(email)}`, {
    method: "PATCH",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({ [column]: new Date().toISOString() }),
  }).catch(() => {/* non-blocking -- leaving the column null means the next run retries */});
}

// ---------------------------------------------------------------------------
// Resend send
// ---------------------------------------------------------------------------

function fromAddress(): string {
  const raw = Deno.env.get("RESEND_FROM") ?? "";
  if (!raw) return `${APP_NAME} <onboarding@resend.dev>`;
  const m = raw.match(/<([^>]+)>/);
  const emailPart = m ? m[1] : raw.trim();
  return `${APP_NAME} <${emailPart}>`;
}

function unsubscribeFooter(appUrl: string, token: string): string {
  if (!token) return "";
  const unsubUrl = `${appUrl}/?unsubscribe=${token}`;
  return `<p style='color:#9e9e9e;font-size:0.75rem;margin-top:16px;'>` +
    `<a href='${unsubUrl}' style='color:#9e9e9e;'>Unsubscribe from these emails</a></p>`;
}

function caseStudyHtml(appUrl: string, token: string): string {
  return `
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>40+ hours of rework, avoidable</h2>
  <p style='font-size:0.9rem;'>
    A real African consultancy had their final donor report rejected 3 times in 2024 &mdash;
    because results weren't tied to logframe indicators. That's 40+ hours of rework,
    a missed deadline, and a donor relationship under strain.
  </p>
  <p style='font-size:0.9rem;'>
    The fix was small: catching the gap before submission, not after. That's exactly
    what ${APP_NAME}'s Confidence and Clarity scores are built to do &mdash; flag weak
    evidence and missing logframe links before your donor does.
  </p>
  <p style='margin-top:20px;'>
    <a href='${appUrl}/'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Run another check &rarr;
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;'>
    ${APP_NAME} &middot; Built in Accra for MEL teams across West Africa
  </p>
  ${unsubscribeFooter(appUrl, token)}
</div>`;
}

function upgradeOfferHtml(appUrl: string, token: string): string {
  return `
<div style='font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#212121;'>
  <h2 style='color:#1B5E20;margin-bottom:4px;'>Ready for unlimited checks?</h2>
  <p style='font-size:0.9rem;'>
    You've had a week with ${APP_NAME}. If your free checks are running low, or you're
    fixing gaps and want to re-score without limits, Professional removes the cap.
  </p>
  <p style='font-size:0.9rem;'>
    <strong>Professional</strong> &mdash; GHS 50/month: unlimited checks, re-score after every
    fix, and a downloadable Readiness Card PDF to share with your supervisor or donor.
  </p>
  <p style='font-size:0.85rem;color:#616161;'>
    The ROI is immediate: GHS 50/month vs. GHS 12,000&ndash;17,000 in rework costs from a
    donor-queried report.
  </p>
  <p style='margin-top:20px;'>
    <a href='${appUrl}/?billing=1'
       style='background:#1B5E20;color:white;padding:10px 20px;border-radius:8px;
              text-decoration:none;font-weight:700;display:inline-block;'>
      Upgrade to Professional &rarr;
    </a>
  </p>
  <p style='color:#424242;font-size:0.875rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;'>
    ${APP_NAME} &middot; Built in Accra for MEL teams across West Africa
  </p>
  ${unsubscribeFooter(appUrl, token)}
</div>`;
}

async function sendResendEmail(toEmail: string, subject: string, html: string): Promise<boolean> {
  const apiKey = Deno.env.get("RESEND_API_KEY");
  if (!apiKey) return false;
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from: fromAddress(), to: [toEmail], subject, html }),
  }).catch(() => null);
  return !!resp && (resp.status === 200 || resp.status === 201);
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const cronSecret = Deno.env.get("CRON_SECRET") ?? "";
  const auth = req.headers.get("Authorization") ?? "";
  if (!cronSecret || auth !== `Bearer ${cronSecret}`) {
    return new Response("Forbidden", { status: 401 });
  }

  const appUrl = (Deno.env.get("APP_BASE_URL") ?? "https://impact-integrity-diagnostic.streamlit.app")
    .replace(/\/$/, "");

  let day3Sent = 0, day7Sent = 0;

  const day3Due = await fetchDueUsers("day3_email_sent_at", 3);
  for (const u of day3Due) {
    const ok = await sendResendEmail(
      u.email,
      "What a rejected donor report actually costs",
      caseStudyHtml(appUrl, u.unsubscribe_token),
    );
    if (ok) {
      await markSent(u.email, "day3_email_sent_at");
      day3Sent++;
    }
  }

  const day7Due = await fetchDueUsers("day7_email_sent_at", 7);
  for (const u of day7Due) {
    const ok = await sendResendEmail(
      u.email,
      "Unlimited checks, re-scoring, and a PDF your supervisor can read",
      upgradeOfferHtml(appUrl, u.unsubscribe_token),
    );
    if (ok) {
      await markSent(u.email, "day7_email_sent_at");
      day7Sent++;
    }
  }

  return new Response(
    JSON.stringify({ status: "ok", day3_due: day3Due.length, day3_sent: day3Sent, day7_due: day7Due.length, day7_sent: day7Sent }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});
