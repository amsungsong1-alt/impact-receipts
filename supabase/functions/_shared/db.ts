/**
 * supabase/functions/_shared/db.ts
 *
 * Supabase REST helpers shared between paystack-webhook and
 * flutterwave-webhook. Both webhooks write to the same
 * `payments`/`users`/`crm_events` tables, so this extraction avoids a
 * second manually-synced copy of the same upsert/PATCH logic (the
 * signature-verification scheme is NOT shared here, since Paystack and
 * Flutterwave use genuinely different verification -- see each webhook's
 * own signature check).
 *
 * `payments.paystack_reference` is reused as the generic external-charge
 * reference for Flutterwave rows too (Flutterwave's tx_ref/flw_ref) rather
 * than adding a second reference column -- the column name is a naming
 * leftover from before a second processor existed, not worth a
 * migration+backfill just to rename.
 */

export async function upsertPayment(row: Record<string, unknown>): Promise<void> {
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

export async function updateUser(email: string, fields: Record<string, unknown>): Promise<void> {
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
// the webhooks are the only writers of tier_change events for
// subscription-driven plan changes (renewals/cancellations), since
// utils/audits.py's Python mark_paid() call sites only ever see
// pay-per-use payments. All writers feed the same crm_events table (see
// supabase/migrations/0012).
export async function insertCrmEvent(
  email: string,
  eventType: string,
  metadata: Record<string, unknown>,
): Promise<void> {
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

export function addDaysIsoDate(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10); // date only -- matches users.paid_until (date column)
}

export function labelToPeriodDays(label: string): number {
  if (label === "annual") return 365;
  if (label === "monthly" || label === "agency") return 30;
  return 1; // "per_use" or unknown
}

export function labelToTier(label: string): string | undefined {
  if (label === "agency") return "agency";
  if (label === "monthly" || label === "annual") return "professional";
  return undefined; // "per_use" doesn't change the account's subscription tier
}
