/**
 * supabase/functions/whatsapp-webhook/index.ts
 *
 * Supabase Edge Function — WhatsApp Cloud API Webhook
 *
 * Handles two request types from Meta:
 *   GET  — webhook verification challenge (one-time setup)
 *   POST — inbound message events → keyword detection → auto-reply template
 *
 * Environment variables (set in Supabase dashboard → Project Settings → Edge Functions):
 *   WHATSAPP_TOKEN            Meta permanent access token
 *   WHATSAPP_PHONE_NUMBER_ID  The phone number's ID from Meta developer portal
 *   WHATSAPP_VERIFY_TOKEN     Random string matching what you entered on Meta dashboard
 *   SUPABASE_URL              Your Supabase project URL (auto-available in Edge Functions)
 *   SUPABASE_SERVICE_ROLE_KEY Service role key for DB writes
 *
 * Register this URL with Meta:
 *   https://<PROJECT_REF>.supabase.co/functions/v1/whatsapp-webhook
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

const WA_API_BASE   = "https://graph.facebook.com/v20.0";
const WA_NUMBER     = "233503648195";

// ---------------------------------------------------------------------------
// Context keyword detection (mirrors utils/whatsapp.py)
// ---------------------------------------------------------------------------

const INBOUND_KEYWORDS: Record<string, string[]> = {
  weak_result_review: ["review", "score", "confidence", "clarity", "submission", "check"],
  agency_plan:        ["agency", "team", "seats", "multiple", "organisation", "organization"],
  payment_support:    ["payment", "charged", "paid", "unlock", "paystack", "momo", "visa"],
  error_support:      ["error", "bug", "crash", "broken", "issue", "problem"],
  pricing_questions:  ["price", "pricing", "cost", "plan", "professional", "subscription"],
  landing_review:     ["book", "free", "first review", "deadline", "submit"],
};

const ACK_MESSAGES: Record<string, string> = {
  weak_result_review: (
    "Your result review request is received! 📊\n\n" +
    "We'll look at your scores and reply here within 24 hours. " +
    "Feel free to share your result details if you haven't already.\n\n" +
    "👉 impact-proof.streamlit.app"
  ),
  agency_plan: (
    "Thanks for your interest in the ImpactProof Agency plan! 🏢\n\n" +
    "We'll be in touch about multi-seat pricing within 24 hours.\n\n" +
    "👉 impact-proof.streamlit.app"
  ),
  payment_support: (
    "Payment support acknowledged! 💳\n\n" +
    "We'll resolve your issue within 4 hours — " +
    "please send your Paystack transaction reference if you have one."
  ),
  error_support: (
    "App error received — we'll investigate and get back to you shortly. 🔧\n\n" +
    "Please describe what you were doing when the error occurred."
  ),
  pricing_questions: (
    "Thanks for your question! 💬\n\n" +
    "We'll reply here with pricing details within 24 hours.\n\n" +
    "👉 impact-proof.streamlit.app"
  ),
  landing_review: (
    "Your free review request is received! 👋\n\n" +
    "We'll reach out to discuss your submission deadline and evidence quality within 24 hours."
  ),
  _generic: (
    "Hi! Thanks for reaching out to ImpactProof. 👋\n\n" +
    "We'll get back to you on WhatsApp within 24 hours.\n\n" +
    "In the meantime: impact-proof.streamlit.app"
  ),
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function detectContext(body: string): string {
  const lower = body.toLowerCase();
  for (const [ctx, keywords] of Object.entries(INBOUND_KEYWORDS)) {
    if (keywords.some((kw) => lower.includes(kw))) return ctx;
  }
  return "_generic";
}

async function sendTemplate(
  to: string,
  templateName: string,
  params: string[],
  token: string,
  phoneNumberId: string,
): Promise<{ ok: boolean; body: unknown }> {
  const components =
    params.length > 0
      ? [
          {
            type: "body",
            parameters: params.map((p) => ({ type: "text", text: p.slice(0, 256) })),
          },
        ]
      : [];

  const payload = {
    messaging_product: "whatsapp",
    to,
    type: "template",
    template: {
      name: templateName,
      language: { code: "en_US" },
      components,
    },
  };

  const resp = await fetch(`${WA_API_BASE}/${phoneNumberId}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const respBody = await resp.json();
  return { ok: resp.ok, body: respBody };
}

async function logToSupabase(row: Record<string, unknown>): Promise<void> {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) return;

  await fetch(`${url}/rest/v1/wa_conversations`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify(row),
  }).catch(() => {/* non-blocking */});
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

serve(async (req: Request) => {
  const url    = new URL(req.url);
  const token  = Deno.env.get("WHATSAPP_TOKEN") ?? "";
  const pid    = Deno.env.get("WHATSAPP_PHONE_NUMBER_ID") ?? "";
  const verify = Deno.env.get("WHATSAPP_VERIFY_TOKEN") ?? "";

  // ── GET: webhook verification ──────────────────────────────────────────
  if (req.method === "GET") {
    const mode      = url.searchParams.get("hub.mode");
    const challenge = url.searchParams.get("hub.challenge");
    const vtoken    = url.searchParams.get("hub.verify_token");

    if (mode === "subscribe" && vtoken === verify) {
      return new Response(challenge ?? "", { status: 200 });
    }
    return new Response("Forbidden", { status: 403 });
  }

  // ── POST: inbound message event ────────────────────────────────────────
  if (req.method === "POST") {
    let payload: Record<string, unknown>;
    try {
      payload = await req.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    // Navigate the WhatsApp webhook event structure
    const entry    = (payload?.entry as unknown[])?.[0] as Record<string, unknown> | undefined;
    const change   = (entry?.changes as unknown[])?.[0] as Record<string, unknown> | undefined;
    const value    = change?.value as Record<string, unknown> | undefined;
    const messages = value?.messages as unknown[] | undefined;

    if (!messages || messages.length === 0) {
      // Status update or other non-message event — acknowledge and ignore
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    for (const msg of messages) {
      const message  = msg as Record<string, unknown>;
      const from     = message.from as string | undefined;
      const msgType  = message.type as string | undefined;

      if (!from || msgType !== "text") continue;

      const textBody = ((message.text as Record<string, unknown>)?.body as string) ?? "";
      const context  = detectContext(textBody);
      const ackMsg   = ACK_MESSAGES[context] ?? ACK_MESSAGES["_generic"];

      // Send auto-reply template
      const { ok, body: apiResp } = await sendTemplate(
        from,
        "impactproof_user_ack",
        [ackMsg],
        token,
        pid,
      );

      // Log to Supabase wa_conversations table
      await logToSupabase({
        context_id: context,
        user_email:  "",  // not known from inbound
        direction:   "inbound",
        phone:       from,
        body:        textBody.slice(0, 500),
        success:     true,
      });
      await logToSupabase({
        context_id: context,
        user_email:  "",
        direction:   "auto_reply",
        phone:       from,
        body:        ackMsg.slice(0, 500),
        success:     ok,
      });
    }

    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response("Method Not Allowed", { status: 405 });
});
