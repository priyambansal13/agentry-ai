"""The monthly results report, emailed on the 2nd of each month to the people who want it (Account & notifications).

Same numbers as the portal's Reports page (billing.month_report). Clients that book or recover money see their ROI;
clients on inbox triage alone see the time given back.
"""
import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from agentry import billing
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.features import enabled_automations
from agentry.notify.alerts import recipient_emails
from agentry.notify.email import send_email

BOOKING = {"website_chat", "whatsapp_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"}
MINUTES_PER_EMAIL = 2


def _money(v: float, currency: str) -> str:
    return f"₹{v:,.0f}" if currency == "INR" else f"{currency} {v:,.2f}"


def render(business: str, r: dict, automations: list[str]) -> tuple[str, str]:
    month = datetime.strptime(r["month"], "%Y-%m").strftime("%B %Y")
    lines = [f"Here's what your Agentry agents did for {business} in {month}.", ""]
    if BOOKING & set(automations):
        lines.append(f"• Appointments booked: {r['appointments']} (worth {_money(r['appointments_value'], r['currency'])})")
    if "invoice_follow_up" in automations:
        lines.append(f"• Overdue money recovered: {_money(r['recovered'], r['currency'])} ({r['invoices_recovered']} invoices)")
    if "inbox_triage" in automations:
        hours = round(r["emails_triaged"] * MINUTES_PER_EMAIL / 60)
        lines.append(f"• Emails sorted: {r['emails_triaged']} (about {hours} hour{"" if hours == 1 else "s"} given back)")
    if set(automations) & {"invoice_follow_up", "lead_reactivation", "speed_to_lead", "whatsapp_assistant"}:
        lines.append(f"• Messages sent for you: {r['messages']}")
    if "content_repurposing" in automations and (c := r.get("content")) and c["generated"]:
        quality = f", {c['approved_as_written_pct']}% approved as written" if c["approved_as_written_pct"] is not None else ""
        lines.append(f"• Posts: {c['generated']} written from {c['videos']} recording{'' if c['videos'] == 1 else 's'}, "
                     f"{c['published']} published{quality}")
    if r["roi_multiple"] is not None:
        lines += ["", (f"Return on what you paid: {r['roi_multiple']}× ({_money(r['value_delivered'], r['currency'])} delivered "
                      f"for {_money(r['fee'], r['currency'])}).")]
    lines += ["", f"The full report, with the evidence behind every number: {settings.dashboard_url}/reports?month={r['month']}",
              "", "You get this on the 2nd of each month. Change it under Account & notifications."]
    subject = f"Your {month} results from Agentry"
    if r["roi_multiple"] is not None:
        subject += f": {r['roi_multiple']}× return"
    return subject, "\n".join(lines)


async def send_monthly(org_id: str, today: date | None = None) -> int:
    """Email last month's report to this client's opted-in people. Returns how many emails went out."""
    first = (today or datetime.now(UTC).date()).replace(day=1)
    start, end = billing.month_bounds(first - timedelta(days=1))
    async with tenant_session(org_id) as conn:
        r = await billing.month_report(conn, start, end)
        automations = await enabled_automations(conn)
        business = (await conn.execute(text("select o.name from auth.organization o where o.id = :o"), {"o": org_id})).scalar_one()
    to = await recipient_emails(org_id, "reports")
    subject, body = render(business, r, automations)
    for addr in to:
        await asyncio.to_thread(send_email, addr, subject, body)
    return len(to)


async def live_clients() -> list[str]:
    async with system_session() as conn:
        return list((await conn.execute(text("select org_id from app.org_settings where status = 'live'"))).scalars())
