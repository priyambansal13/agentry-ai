"""Urgent emails nobody has answered: alert again, to the owner.

After an urgent email's first alert, a durable workflow waits `escalate_after_minutes` and checks whether it was
handled. If not, the people who get "escalation" alerts (owners by default) hear about it. Quiet hours hold
everything until they end: an alert held overnight goes out when quiet hours end, and an escalation never fires at
night.

Handled means any of: a reply sent through Agentry or straight from Gmail after the email arrived, its draft approved,
edited, discarded, marked handled or snoozed (someone saw it and chose a time), or the conversation closed.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS
from sqlalchemy import text

from agentry.config import settings
from agentry.connectors.mailbox import mailbox_for
from agentry.db import tenant_session
from agentry.notify.alerts import send_owner_alert

MAX_SLEEP = 24 * 3600


def seconds_until_quiet_end(tz: str, quiet: list[str], now: datetime | None = None) -> float:
    """0 outside quiet hours, else the seconds until they end (local time)."""
    now = now or datetime.now(ZoneInfo(tz))
    start, end = quiet
    hm = now.strftime("%H:%M")
    inside = (start <= hm or hm < end) if start > end else (start <= hm < end)
    if not inside:
        return 0
    eh, em = map(int, end.split(":"))
    target = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


@DBOS.step()
async def is_handled(org_id: str, conversation_id: str, received_at: str) -> bool:
    since = datetime.fromisoformat(received_at)
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select c.status, exists(select 1 from app.approvals a where a.conversation_id = c.id
                and a.created_at >= :t and (a.status <> 'pending' or a.snoozed_until > now())) as decided
            from app.conversations c where c.id = cast(:c as uuid)"""), {"c": conversation_id, "t": since})).one()
    if row.decided or row.status == "closed":
        return True
    try:
        return await (await mailbox_for(org_id, conversation_id)).replied_since(org_id, conversation_id, since)
    except Exception:  # noqa: BLE001 - Gmail unreachable: treat as unanswered (a needless alert beats a missed one)
        return False


@DBOS.step()
async def quiet_wait(org_id: str) -> float:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select s.timezone, a.config from app.org_settings s
            left join app.automation_instances a on a.template_key = 'inbox_triage'"""))).one()
    from agentry.automations.inbox_triage.config import TriageConfig
    return seconds_until_quiet_end(row.timezone, list(TriageConfig(**(row.config or {})).quiet_hours))


@DBOS.step()
async def send_alert(org_id: str, email: dict, *, escalation: bool, minutes: int = 0) -> str:
    cfg = email["config"]
    link = f"{settings.dashboard_url}/conversations/{email['conversation_id']}"
    subject = (f"Still unanswered after {minutes} min: {email['subject'] or '(no subject)'}" if escalation
               else f"URGENT email: {email['subject'] or '(no subject)'}")
    body = f"From: {email['from']}\n{email.get('urgent_reason') or ''}\n\n{email.get('summary') or ''}\n\n"
    body += ("Nobody has replied yet. " if escalation else "") + f"Open in Agentry: {link}"
    first_excludes = ("owner",) if cfg["owner_alert"] == "if_unanswered" else ()
    channel = await send_owner_alert(org_id, subject, body, channel=cfg["alert_channel"], telegram_chat_id=cfg.get("telegram_chat_id"),
                                     kind="escalation" if escalation else "urgent", exclude_roles=() if escalation else first_excludes)
    if channel == "none" and not escalation and first_excludes:
        # nobody but the owner gets urgent alerts (e.g. a one-person team): never leave an urgent email unannounced
        channel = await send_owner_alert(org_id, subject, body, channel=cfg["alert_channel"], telegram_chat_id=cfg.get("telegram_chat_id"))
    from agentry import audit
    async with tenant_session(org_id) as conn:
        await audit.record(conn, org_id=org_id, actor_type="agent", action="alert.escalated" if escalation else "alert.sent",
                           target_type="conversation", target_id=email["conversation_id"], metadata={"channel": channel})
    return channel


@DBOS.workflow()
async def follow_up_urgent(org_id: str, email: dict, first_alert: str | None) -> str:
    """Runs on its own (it sleeps): deliver a held first alert after quiet hours, then escalate if still unanswered."""
    cfg = email["config"]
    if first_alert == "deferred_quiet_hours":
        await DBOS.sleep_async(min(await quiet_wait(org_id), MAX_SLEEP))
        if await is_handled(org_id, email["conversation_id"], email["received_at"]):
            return "handled overnight"
        await send_alert(org_id, email, escalation=False)
    minutes = cfg["escalate_after_minutes"]
    if not minutes:
        return "no escalation"
    await DBOS.sleep_async(minutes * 60)
    if wait := await quiet_wait(org_id):  # never escalate at night: check again when quiet hours end
        await DBOS.sleep_async(min(wait, MAX_SLEEP))
    if await is_handled(org_id, email["conversation_id"], email["received_at"]):
        return "handled"
    await send_alert(org_id, email, escalation=True, minutes=minutes)
    return "escalated"
