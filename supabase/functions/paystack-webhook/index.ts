/**
 * supabase/functions/paystack-webhook/index.ts
 *
 * Supabase Edge Function — Paystack Webhook
 *
 * Handles subscription lifecycle events pushed server-to-server by Paystack:
 *   charge.success          initial charge AND recurring renewal charges
 *   subscription.create     a subscription was created (may arrive alongside
 *                            the first charge.success, not instead of it)
 *   invoice.payment_failed   a renewal charge failed (Paystack's own dunning
 *                            retries happen before subscription.disable)
 *   subscription.disable     subscription cancelled / dunning exhausted
 *
 * POST-only. Verifies the x-paystack-signature header (HMAC-SHA512 of the
 * raw request body, using PAYSTACK_SECRET_KEY) before processing anything.
 *
 * Environment variables (set via `supabase secrets set`, NOT the same store
 * as Streamlit's own secrets):
 *   PAYSTACK_SECRET_KEY                 Same key used by utils/paystack.py
 *   PAYSTACK_PLAN_PROFESSIONAL_MONTHLY  Plan codes from
 *   PAYSTACK_PLAN_PROFESSIONAL_ANNUAL     scripts/setup_paystack_plans.py
 *   PAYSTACK_PLAN_AGENCY_MONTHLY
 *   SUPABASE_URL                        Auto-available in Edge Functions
 *   SUPABASE_SERVICE_ROLE_KEY           Service role key for DB writes
 *
 * Register this URL in the Paystack dashboard (Settings -> API Keys & Webhooks):
 *   https://<PROJECT_REF>.supabase.co/functions/v1/paystack-webhook
 *
 * IMPORTANT: several exact event names and payload field paths below are the
 * most likely current values based on Paystack's documented event taxonomy
 * at the time this was written, NOT verified against a live payload. VERIFY
 * against current Paystack docs -- and ideally a real test webhook delivery
 * from the Paystack dashboard -- before relying on this in production.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

// ---------------------------------------------------------------------------
// Supabase REST helpers (mirrors the pattern in whatsapp-webhook/index.ts's
// logToSupabase, extended with an upsert-on-conflict and a filtered PATCH)
// ---------------------------------------------------------------------------

async function upsertPayment(row: Record<string, unknown>): Promise<void> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key || !row.paystack_reference) return;
  await fetch(`${url}/rest/v1/payments?on_conflict=paystack_reference`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal",
    },
    body: JSON.stringify(row),
  }).catch(() => {/* non-blocking -- a failed history write shouldn't break webhook processing */});
}

async function updateUser(email: string, fields: Record<string, unknown>): Promise<void> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const clean = Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== undefined && v !== ""));
  if (!url || !key || !email || Object.keys(clean).length === 0) return;
  await fetch(`${url}/rest/v1/users?email=eq.${encodeURIComponent(email)}`, {
    method: "PATCH",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify(clean),
  }).catch(() => {/* non-blocking */});
}

// insertCrmEvent: mirrors utils/crm.py's log_event() on the Python side --
// this is the only writer of tier_change events for subscription-driven
// plan changes (renewals/cancellations), since utils/audits.py's Python
// mark_paid() call sites only ever see pay-per-use payments. Both writers
// feed the same crm_events table (see supabase/migrations/0012).
async function insertCrmEvent(email: string, eventType: string, metadata: Record<string, unknown>): Promise<void> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key || !email) return;
  await fetch(`${url}/rest/v1/crm_events`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({ email, event_type: eventType, metadata }),
  }).catch(() => {/* non-blocking -- a failed event write shouldn't break webhook processing */});
}

function addDaysIsoDate(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10); // date only -- matches users.paid_until (date column)
}

// planCodeToLabel: maps a Paystack Plan code back to our own plan label
// ("monthly" | "annual" | "agency"), since Paystack's webhook payload
// identifies the plan by its own opaque code, not our label.
function planCodeToLabel(planCode: string): string {
  if (planCode && planCode === Deno.env.get("PAYSTACK_PLAN_AGENCY_MONTHLY")) return "agency";
  if (planCode && planCode === Deno.env.get("PAYSTACK_PLAN_PROFESSIONAL_ANNUAL")) return "annual";
  if (planCode && planCode === Deno.env.get("PAYSTACK_PLAN_PROFESSIONAL_MONTHLY")) return "monthly";
  return "monthly"; // best-effort default for an unrecognized plan_code
}

function labelToPeriodDays(label: string): number {
  if (label === "annual") return 365;
  if (label === "monthly" || label === "agency") return 30;
  return 1; // "per_use" or unknown
}

function labelToTier(label: string): string | undefined {
  if (label === "agency") return "agency";
  if (label === "monthly" || label === "annual") return "professional";
  return undefined; // "per_use" doesn't change the account's subscription tier
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const secretKey = Deno.env.get("PAYSTACK_SECRET_KEY") ?? "";
  const signature = req.headers.get("x-paystack-signature") ?? "";

  // Read the raw body as text FIRST -- signature verification needs the
  // exact original bytes. Parsing/re-serializing JSON before verifying can
  // silently change byte content (key order, whitespace) and break the HMAC
  // check.
  const rawBody = await req.text();

  if (!secretKey || !signature) {
    return new Response("Forbidden", { status: 401 });
  }

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secretKey),
    { name: "HMAC", hash: "SHA-512" },
    false,
    ["sign"],
  );
  const sigBuffer = await crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(rawBody));
  const computed = Array.from(new Uint8Array(sigBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (computed !== signature) {
    return new Response("Forbidden", { status: 401 });
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response("Bad Request", { status: 400 });
  }

  const event = (payload.event as string) ?? "";
  const data = (payload.data as Record<string, unknown>) ?? {};

  if (event === "charge.success") {
    const customer = (data.customer as Record<string, unknown>) ?? {};
    const email = (customer.email as string) ?? "";
    const reference = (data.reference as string) ?? "";
    const amount = (data.amount as number) ?? 0;
    const metadata = (data.metadata as Record<string, unknown>) ?? {};
    // Same metadata.plan field the existing Python redirect-verify path reads
    // (see utils/paystack.verify_payment) -- present on every charge, whether
    // or not it's tied to a Plan.
    const metadataPlan = (metadata.plan as string) ?? "";
    const planObj = (data.plan as Record<string, unknown>) ?? {};
    const planCode = (planObj.plan_code as string) ?? "";
    const subObj = (data.subscription as Record<string, unknown>) ?? {};
    const subscriptionCode = (subObj.subscription_code as string) ?? "";
    const emailToken = (subObj.email_token as string) ?? "";

    // A subscription-tied charge has data.plan populated; a plain one-off
    // transaction (pay-per-use, always; or monthly/annual/agency before the
    // live Subscribe buttons were switched to plan-tied transactions) does
    // not -- fall back to the metadata label in that case.
    const isSubscription = Boolean(planCode);
    const label = isSubscription ? planCodeToLabel(planCode) : (metadataPlan || "per_use");

    if (reference) {
      await upsertPayment({
        email, paystack_reference: reference, amount_pesewas: amount,
        currency: "GHS", plan: label, status: "success",
        source: "webhook", paystack_event: event,
      });
    }
    if (email) {
      await updateUser(email, {
        plan: labelToTier(label),
        subscription_status: isSubscription ? "active" : undefined,
        paid_until: addDaysIsoDate(labelToPeriodDays(label)),
        paystack_subscription_code: subscriptionCode || undefined,
        paystack_email_token: emailToken || undefined,
      });
      await insertCrmEvent(email, "tier_change", { plan_label: label, source: "webhook_charge" });
    }
  } else if (event === "subscription.create") {
    // VERIFY: for this event, `data` is typically the subscription object
    // itself (subscription_code/email_token directly on data, not nested).
    const customer = (data.customer as Record<string, unknown>) ?? {};
    const email = (customer.email as string) ?? "";
    const subscriptionCode = (data.subscription_code as string) ?? "";
    const emailToken = (data.email_token as string) ?? "";
    if (email) {
      await updateUser(email, {
        subscription_status: "active",
        paystack_subscription_code: subscriptionCode || undefined,
        paystack_email_token: emailToken || undefined,
      });
    }
  } else if (event === "invoice.payment_failed") {
    // VERIFY exact event name (may be "invoice.update" with a failed status,
    // or similar) and field paths before relying on this in production.
    const customer = (data.customer as Record<string, unknown>) ?? {};
    const email = (customer.email as string) ?? "";
    const transaction = (data.transaction as Record<string, unknown>) ?? {};
    const reference = (transaction.reference as string) ?? (data.reference as string) ?? "";
    const amount = (transaction.amount as number) ?? (data.amount as number) ?? 0;

    if (reference) {
      await upsertPayment({
        email, paystack_reference: reference, amount_pesewas: amount,
        currency: "GHS", plan: null, status: "failed",
        source: "webhook", paystack_event: event,
      });
    }
    // Do NOT revoke access here -- Paystack retries a failed renewal
    // (dunning) before giving up. Only subscription.disable below actually
    // ends access.
    if (email) {
      await updateUser(email, { subscription_status: "attention" });
    }
  } else if (event === "subscription.disable") {
    // VERIFY: some Paystack accounts distinguish subscription.disable
    // (explicit cancellation) from subscription.not_renew (non-renewal) --
    // treat both the same way here unless testing reveals they need to
    // diverge.
    const customer = (data.customer as Record<string, unknown>) ?? {};
    const email = (customer.email as string) ?? "";
    if (email) {
      await updateUser(email, { subscription_status: "cancelled" });
      await insertCrmEvent(email, "tier_change", { plan_label: "cancelled", source: "webhook_disable" });
    }
  }
  // Any other event type: acknowledge and ignore, same as the WhatsApp
  // function's "non-message event" branch -- acknowledging avoids needless
  // webhook redelivery retries from Paystack.

  return new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
