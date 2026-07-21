/**
 * supabase/functions/stripe-webhook/index.ts
 *
 * Supabase Edge Function — Stripe Webhook
 *
 * Handles the USD/GBP/EUR checkout lifecycle for Stripe, structurally
 * parallel to paystack-webhook/index.ts (which remains the sole handler
 * for GHS, and the GHS-fallback charge for NGN/KES/ZAR). Shares its
 * payments/users/crm_events write helpers via ../_shared/db.ts.
 *
 * Handles:
 *   checkout.session.completed   one-off charge OR first subscription charge
 *   invoice.payment_failed       a subscription renewal failed (Stripe's own
 *                                 dunning retries happen before cancellation)
 *   customer.subscription.deleted  subscription cancelled / dunning exhausted
 *
 * POST-only. Verifies the Stripe-Signature header via the Stripe SDK's
 * async webhook-construction helper (Deno-compatible) before processing
 * anything -- unlike paystack-webhook's hand-rolled HMAC, Stripe's SDK
 * handles this natively.
 *
 * Environment variables (set via `supabase secrets set`, NOT the same store
 * as Streamlit's own secrets):
 *   STRIPE_SECRET_KEY             Same key used by utils/stripe_payments.py
 *   STRIPE_WEBHOOK_SIGNING_SECRET whsec_... from the Stripe Dashboard's
 *                                  webhook registration
 *   SUPABASE_URL                  Auto-available in Edge Functions
 *   SUPABASE_SERVICE_ROLE_KEY     Service role key for DB writes
 *
 * Register this URL in the Stripe Dashboard (Developers -> Webhooks):
 *   https://<PROJECT_REF>.supabase.co/functions/v1/stripe-webhook
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import Stripe from "https://esm.sh/stripe@14?target=deno";
import {
  upsertPayment, updateUser, insertCrmEvent, labelToTier,
} from "../_shared/db.ts";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2023-10-16",
  httpClient: Stripe.createFetchHttpClient(),
});
const cryptoProvider = Stripe.createSubtleCryptoProvider();

// Subscriptions created via utils/stripe_payments.py's inline price_data
// have no Stripe Price/Product id to key off of -- our own `plan` label
// travels in session/subscription metadata instead (set at checkout-session
// creation time), exactly like Paystack's metadata.plan.
async function getEmailByStripeCustomerId(customerId: string): Promise<string> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key || !customerId) return "";
  try {
    const res = await fetch(
      `${url}/rest/v1/users?stripe_customer_id=eq.${encodeURIComponent(customerId)}&select=email`,
      { headers: { apikey: key, Authorization: `Bearer ${key}` } },
    );
    const rows = await res.json();
    return Array.isArray(rows) && rows[0]?.email ? String(rows[0].email) : "";
  } catch {
    return "";
  }
}

serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const signature = req.headers.get("Stripe-Signature") ?? "";
  const endpointSecret = Deno.env.get("STRIPE_WEBHOOK_SIGNING_SECRET") ?? "";

  // Read the raw body as text FIRST -- signature verification needs the
  // exact original bytes, same requirement as paystack-webhook's HMAC check.
  const rawBody = await req.text();

  if (!signature || !endpointSecret) {
    return new Response("Forbidden", { status: 401 });
  }

  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(
      rawBody, signature, endpointSecret, undefined, cryptoProvider,
    );
  } catch {
    return new Response("Forbidden", { status: 401 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    const email = session.customer_email || session.customer_details?.email || "";
    const reference = session.id;
    const amount = session.amount_total ?? 0;
    const currency = (session.currency ?? "").toUpperCase();
    const plan = (session.metadata?.plan as string) ?? "per_use";
    const isSubscription = session.mode === "subscription";
    const customerId = typeof session.customer === "string" ? session.customer : "";

    if (reference) {
      await upsertPayment({
        paystack_reference: reference, email, amount_pesewas: amount,
        currency, displayed_currency: currency, plan, status: "success",
        source: "webhook", paystack_event: event.type,
      });
    }
    if (email) {
      await updateUser(email, {
        plan: labelToTier(plan),
        subscription_status: isSubscription ? "active" : undefined,
        stripe_customer_id: customerId || undefined,
        stripe_subscription_id: typeof session.subscription === "string" ? session.subscription : undefined,
      });
      await insertCrmEvent(email, "tier_change", { plan_label: plan, source: "webhook_stripe_checkout" });
    }
  } else if (event.type === "invoice.payment_failed") {
    const invoice = event.data.object as Stripe.Invoice;
    const email = invoice.customer_email || "";
    const reference = invoice.id;
    const amount = invoice.amount_due ?? 0;
    const currency = (invoice.currency ?? "").toUpperCase();

    if (reference) {
      await upsertPayment({
        paystack_reference: reference, email, amount_pesewas: amount,
        currency, displayed_currency: currency, plan: null, status: "failed",
        source: "webhook", paystack_event: event.type,
      });
    }
    // Do NOT revoke access here -- Stripe retries a failed renewal (dunning)
    // before giving up, same tolerant semantics as paystack-webhook.
    if (email) {
      await updateUser(email, { subscription_status: "attention" });
    }
  } else if (event.type === "customer.subscription.deleted") {
    const subscription = event.data.object as Stripe.Subscription;
    const customerId = typeof subscription.customer === "string" ? subscription.customer : "";
    const email = await getEmailByStripeCustomerId(customerId);
    if (email) {
      await updateUser(email, { subscription_status: "cancelled" });
      await insertCrmEvent(email, "tier_change", { plan_label: "cancelled", source: "webhook_stripe_disable" });
    }
  }
  // Any other event type: acknowledge and ignore, same as paystack-webhook's
  // convention -- acknowledging avoids needless webhook redelivery retries.

  return new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
