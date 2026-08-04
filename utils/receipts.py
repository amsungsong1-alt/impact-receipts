"""
utils/receipts.py — Laudon Ch.10, C4: downloadable payment receipts.

render_billing_page() previously showed payment history as a bare
dataframe with no way to download anything -- nothing an M&E officer could
attach to a donor grant line as documentation. build_receipt_html() turns
one payments row into a simple, self-contained HTML receipt; app.py's
existing _html_to_pdf_bytes() (shared by every other PDF export in the
app) converts it to PDF, degrading to an HTML-only download if xhtml2pdf
isn't installed -- same contract as every other export in this app.

Pure string assembly, no DB access of its own -- the caller supplies the
already-fetched payment row and org context.
"""
from __future__ import annotations
from datetime import datetime, timezone


def build_receipt_html(payment: dict, org_context: dict | None = None) -> str:
    """payment: one row from utils.db.get_payment_history() (payments table
    shape -- paystack_reference, amount_pesewas, currency, plan, status,
    created_at). org_context: {"email", "account_sector", "primary_donors"}
    -- any key may be missing; renders as an em-dash placeholder rather
    than a guessed value. Returns self-contained HTML (no external assets,
    no network calls)."""
    payment = payment or {}
    org_context = org_context or {}

    reference = payment.get("paystack_reference") or "—"
    amount_ghs = round((payment.get("amount_pesewas") or 0) / 100, 2)
    currency = payment.get("currency") or "GHS"
    plan = (payment.get("plan") or "—").replace("_", " ").title()
    status = (payment.get("status") or "—").title()
    date_str = (payment.get("created_at") or "")[:10] or "—"
    email = org_context.get("email") or payment.get("email") or "—"
    donors = org_context.get("primary_donors") or []
    donors_text = ", ".join(donors) if donors else "—"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status_class = "status-success" if status.lower() == "success" else "status-other"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>ImpactProof Receipt {reference}</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; color: #222; padding: 24px; }}
h1 {{ font-size: 20px; margin-bottom: 4px; }}
.muted {{ color: #666; font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
td, th {{ text-align: left; padding: 8px 4px; border-bottom: 1px solid #ddd; font-size: 14px; }}
th {{ color: #666; font-weight: 600; width: 40%; }}
.status-success {{ color: #1B5E20; font-weight: 700; }}
.status-other {{ color: #B71C1C; font-weight: 700; }}
</style></head>
<body>
<h1>ImpactProof — Payment Receipt</h1>
<p class="muted">Generated {generated_at}</p>
<table>
<tr><th>Reference</th><td>{reference}</td></tr>
<tr><th>Date</th><td>{date_str}</td></tr>
<tr><th>Account</th><td>{email}</td></tr>
<tr><th>Plan</th><td>{plan}</td></tr>
<tr><th>Amount</th><td>{currency} {amount_ghs:.2f}</td></tr>
<tr><th>Status</th><td class="{status_class}">{status}</td></tr>
<tr><th>Primary donor(s) on file</th><td>{donors_text}</td></tr>
</table>
<p class="muted" style="margin-top:24px;">
This receipt reflects a payment made to ImpactProof for access to the evidence-scoring
platform. Retain for your organisation's accounting/donor-reporting records.
</p>
</body></html>"""
