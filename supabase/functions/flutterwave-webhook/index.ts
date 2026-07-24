/**
 * supabase/functions/flutterwave-webhook/index.ts
 *
 * Supabase Edge Function — Flutterwave Webhook
 *
 * Handles the USD/GBP/EUR checkout lifecycle for Flutterwave, structurally
 * parallel to paystack-webhook/index.ts (which remains the sole handler
 * for GHS, and the GHS-fallback charge for NGN/KES/ZAR). Shares its
 * payments/users/crm_events write helpers via ../_shared/db.ts.
 *
 * Handles:
 *   charge.completed   every charge, one-off or recurring -- data.status
 *                        is "successful" or "failed" (Flutterwave doesn't
 *                        emit a separate invoice.payment_failed/
 *                        subscription.deleted event the way Stripe does;
 *                        a failed renewal charge just arrives as
 *                        charge.completed with status="failed", and
 *                        Flutterwave's own dunning retries happen before
 *                        it gives up -- VERIFY this against a live test
 *                        webhook delivery before relying on it in
 *                        production, same caveat as paystack-webhook's).
 *
 * POST-only. Verifies the `verif-hash` header against
 * FLUTTERWAVE_WEBHOOK_SECRET_HASH (a shared-secret string you set in both
 * the Flutterwave dashboard's webhook settings and this function's env --
 * NOT an HMAC-over-body scheme like Paystack/Stripe's, just a
 * constant-time string match) before processing anything.
 *
 * Environment variables (set via `supabase secrets set`, NOT the same
 * store as Streamlit's own secrets):
 *   FLUTTERWAVE_SECRET_KEY          Same key used by utils/flutterwave_payments.py
 *   FLUTTERWAVE_WEBHOOK_SECRET_HASH The secret hash configured in the
 *                                    Flutterwave dashboard's webhook settings
 *   SUPABASE_URL                    Auto-available in Edge Functions
 *   SUPABASE_SERVICE_ROLE_KEY       Service role key for DB writes
 *
 * Register this URL in the Flutterwave dashboard (Settings -> Webhooks):
 *   https://<PROJECT_REF>.supabase.co/functions/v1/flutterwave-webhook
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { timingSafeEqual } from "https://deno.land/std@0.177.0/crypto/timing_safe_equal.ts";
import { upsertPayment, updateUser, insertCrmEvent, labelToTier } from "../_shared/db.ts";

function safeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  return timingSafeEqual(enc.encode(a), enc.encode(b));
}

serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const secretHash = Deno.env.get("FLUTTERWAVE_WEBHOOK_SECRET_HASH") ?? "";
  const signature = req.headers.get("verif-hash") ?? "";

  if (!secretHash || !signature || !safeEqual(secretHash, signature)) {
    return new Response("Forbidden", { status: 401 });
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(await req.text());
  } catch {
    return new Response("Bad Request", { status: 400 });
  }

  const event = (payload.event as string) ?? "";
  const data = (payload.data as Record<string, unknown>) ?? {};

  if (event === "charge.completed") {
    const customer = (data.customer as Record<string, unknown>) ?? {};
    const email = (customer.email as string) ?? "";
    const reference = (data.tx_ref as string) ?? (data.flw_ref as string) ?? "";
    // Flutterwave's amount is in major units (see utils/flutterwave_payments.py's
    // module docstring) -- store as minor units for consistency with the
    // payments table's Paystack-originated amount_pesewas convention.
    const amountMajor = (data.amount as number) ?? 0;
    const amount = Math.round(amountMajor * 100);
    const currency = ((data.currency as string) ?? "").toUpperCase();
    const status = (data.status as string) ?? "";
    const meta = (data.meta as Record<string, unknown>) ?? {};
    const plan = (meta.plan as string) ?? "per_use";
    // A payment-plan-tied charge (subscription) has data.payment_plan
    // populated -- VERIFY this field name against a live payload; a plain
    // one-off transaction (pay-per-use) does not have it.
    const isSubscription = Boolean(data.payment_plan);

    if (reference) {
      await upsertPayment({
        paystack_reference: reference, email, amount_pesewas: amount,
        currency, displayed_currency: currency, plan: status === "successful" ? plan : null,
        status: status === "successful" ? "success" : "failed",
        source: "webhook", paystack_event: event,
      });
    }
    if (status === "successful" && email) {
      await updateUser(email, {
        plan: labelToTier(plan),
        subscription_status: isSubscription ? "active" : undefined,
      });
      await insertCrmEvent(email, "tier_change", { plan_label: plan, source: "webhook_flutterwave_charge" });
    } else if (status !== "successful" && email && isSubscription) {
      // Do NOT revoke access here -- Flutterwave retries a failed renewal
      // (dunning) before giving up, same tolerant semantics as
      // paystack-webhook's invoice.payment_failed handling.
      await updateUser(email, { subscription_status: "attention" });
    }
  }
  // Any other event type: acknowledge and ignore, same as paystack-webhook's
  // convention -- acknowledging avoids needless webhook redelivery retries.

  return new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
