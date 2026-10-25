"""Billing jobs: record outcomes as they happen; monthly draft statements; finalise after the dispute window."""
from datetime import UTC, datetime, timedelta
from typing import Any

from dbos import DBOS
from sqlalchemy import text

from agentry import billing
from agentry.db import system_session, tenant_session
from agentry.worker.handlers import on


@DBOS.step()
async def booking_outcome(org_id: str, payload: dict) -> None:
    async with tenant_session(org_id) as conn:
        await billing.record_booking(conn, org_id, payload)


@on("booking.created")
@DBOS.workflow()
async def on_booking(event: dict) -> None:
    await booking_outcome(event["org_id"], event["payload"])


@DBOS.step()
async def recovery_outcome(org_id: str, payload: dict) -> None:
    async with tenant_session(org_id) as conn:
        await billing.record_recovery(conn, org_id, payload)


@on("payment.received")
@DBOS.workflow()
async def on_payment(event: dict) -> None:
    await recovery_outcome(event["org_id"], event["payload"])


@DBOS.step()
async def statement_email(org_id: str, statement_id: str) -> int:
    """Tell the client's owners and finance people that a statement is ready (respects their notification settings)."""
    import asyncio

    from agentry.config import settings
    from agentry.notify.alerts import recipient_emails
    from agentry.notify.email import send_email
    async with tenant_session(org_id) as conn:
        st = (await conn.execute(text("""select number, period_start, currency, total, dispute_until, payment_link
            from app.statements where id = cast(:s as uuid)"""), {"s": statement_id})).mappings().one()
    month = f"{st['period_start']:%B %Y}"
    amount = f"{st['currency']} {st['total']:,.2f}"
    body = (f"Your Agentry statement {st['number']} for {month} is ready: {amount}.\n\n"
            f"See every line and the results behind it: {settings.dashboard_url}/billing/statements/{statement_id}\n")
    if st["dispute_until"]:
        body += f"If a line looks wrong, you can dispute it there until {st['dispute_until']:%d %B}.\n"
    if st["payment_link"]:
        body += f"\nPay online: {st['payment_link']}\n"
    to = await recipient_emails(org_id, "billing")
    for addr in to:
        await asyncio.to_thread(send_email, addr, f"Your Agentry statement for {month}", body)
    return len(to)


@on("statement.issued")
@DBOS.workflow()
async def on_statement_issued(event: dict) -> None:
    await statement_email(event["org_id"], event["payload"]["statement_id"])


@DBOS.step()
async def draft_last_month() -> int:
    """1st of the month: draft statements for every client with a plan, for staff to review and issue."""
    start, end = billing.month_bounds((datetime.now(UTC).replace(day=1) - timedelta(days=1)).date())
    async with system_session() as conn:
        orgs = (await conn.execute(text("select org_id from app.pricing_plans"))).scalars().all()
    for org_id in orgs:
        async with tenant_session(org_id) as conn:
            await billing.generate_statement(conn, org_id, start, end)
    return len(orgs)


@DBOS.workflow()
async def monthly_statements(scheduled_time: datetime, context: Any) -> None:
    await draft_last_month()


@DBOS.step()
async def finalize_step() -> int:
    async with system_session() as conn:
        return await billing.finalize_due(conn)


@DBOS.workflow()
async def finalize_statements(scheduled_time: datetime, context: Any) -> None:
    await finalize_step()


@DBOS.step()
async def report_step(org_id: str) -> int:
    from agentry.reports import send_monthly
    return await send_monthly(org_id)


@DBOS.workflow()
async def monthly_reports(scheduled_time: datetime, context: Any) -> None:
    """2nd of the month, 09:00 IST: last month's results report to every live client (one step per client, so a
    failure for one client doesn't resend to the others)."""
    for org_id in await _clients():
        await report_step(org_id)


@DBOS.step()
async def _clients() -> list[str]:
    from agentry.reports import live_clients
    return await live_clients()


@DBOS.step()
async def nudge_step() -> dict:
    from agentry.onboarding_nudges import run_daily
    return await run_daily()


@DBOS.workflow()
async def onboarding_nudges(scheduled_time: datetime, context: Any) -> None:
    """Daily 10:00 IST: remind clients that stalled during onboarding; tell ops who is stuck."""
    await nudge_step()


@DBOS.step()
async def purge_recordings_step() -> int:
    from agentry.voice.recordings import purge_expired
    return await purge_expired()


@DBOS.workflow()
async def purge_recordings(scheduled_time: datetime, context: Any) -> None:
    """Daily 03:30 IST: delete call recordings past each client's retention period (default 90 days)."""
    n = await purge_recordings_step()
    if n:
        DBOS.logger.info(f"deleted {n} expired call recordings")


@DBOS.step()
async def purge_email_text_step() -> int:
    from agentry.automations.inbox_triage.insights import purge_old_email_text
    return await purge_old_email_text()


@DBOS.workflow()
async def purge_email_text(scheduled_time: datetime, context: Any) -> None:
    """Daily 03:45 IST: remove the text of old emails (each client's keep_email_text_days); summaries and replies stay."""
    n = await purge_email_text_step()
    if n:
        DBOS.logger.info(f"removed the text of {n} old emails")


@DBOS.step()
async def follow_up_step() -> int:
    from agentry.automations.inbox_triage.nudges import run_daily
    return await run_daily()


@DBOS.workflow()
async def inbox_follow_ups(scheduled_time: datetime, context: Any) -> None:
    """Daily 10:30 IST: follow-up drafts for clients and leads who went quiet (inbox triage nudge_after_days)."""
    n = await follow_up_step()
    if n:
        DBOS.logger.info(f"suggested {n} follow-ups")


@DBOS.step()
async def weekly_summary_step() -> int:
    from agentry.automations.inbox_triage.weekly import run_weekly
    return await run_weekly()


@DBOS.workflow()
async def weekly_summaries(scheduled_time: datetime, context: Any) -> None:
    """Mondays 09:00 IST: last week in numbers, on WhatsApp or email (#19)."""
    await weekly_summary_step()
