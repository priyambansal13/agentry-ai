"""Daily inbox digest: once a day, at each client's chosen local hour, email the owners a summary of what needs them.

An hourly schedule checks every client; the workflow ID digest-<org>-<local date> makes each day's digest run once,
even if the schedule fires twice or the worker restarts.
"""
import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text

from agentry.automations.inbox_triage.config import TriageConfig
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.notify.alerts import recipient_emails
from agentry.notify.email import send_email


async def build_digest(org_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        by_cat = dict((await conn.execute(text("""
            select metadata #>> '{triage,category}', count(*) from app.messages
            where metadata ? 'triage' and created_at > now() - interval '24 hours' group by 1"""))).all())
        urgent_open = (await conn.execute(text("""
            select c.subject, m.metadata->>'from' as sender from app.messages m join app.conversations c on c.id = m.conversation_id
            where (m.metadata #>> '{triage,urgent}')::boolean and m.created_at > now() - interval '48 hours'
              and not exists (select 1 from app.messages o where o.conversation_id = c.id and o.direction = 'out'
                              and o.created_at > m.created_at)
            order by m.created_at desc limit 10"""))).mappings().all()
        pending = (await conn.execute(text("select count(*) from app.approvals where status = 'pending'"))).scalar_one()
        new_leads = (await conn.execute(text(
            "select count(*) from app.leads where created_at > now() - interval '24 hours'"))).scalar_one()
    return {"by_category": by_cat, "urgent_open": [dict(u) for u in urgent_open], "pending_approvals": pending,
            "new_leads": new_leads}


def render_digest(business: str, d: dict) -> tuple[str, str]:
    total = sum(d["by_category"].values())
    lines = [f"Good morning! Here's your inbox from the last 24 hours at {business}.", "",
             f"{total} emails sorted: " + ", ".join(f"{n} {c}" for c, n in sorted(d["by_category"].items(), key=lambda x: -x[1]))
             if total else "No new email in the last 24 hours."]
    if d["urgent_open"]:
        lines += ["", "Urgent and still unanswered:"] + [f"  • {u['subject']} ({u['sender']})" for u in d["urgent_open"]]
    if d["pending_approvals"]:
        lines += ["", f"{d['pending_approvals']} reply drafts are waiting for you: {settings.dashboard_url}/needs-you"]
    if d["new_leads"]:
        lines += ["", f"{d['new_leads']} new enquiries came in."]
    subject = f"Your inbox: {len(d['urgent_open'])} urgent, {d['pending_approvals']} to approve" if total or d["pending_approvals"] \
        else "Your inbox: all quiet"
    return subject, "\n".join(lines)


@DBOS.step()
async def send_digest_step(org_id: str) -> int:
    async with system_session() as conn:
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one()
    subject, body = render_digest(business, await build_digest(org_id))
    recipients = await recipient_emails(org_id, "digest")
    for to in recipients:
        await asyncio.to_thread(send_email, to, subject, body)
    return len(recipients)


@DBOS.workflow()
async def send_digest(org_id: str) -> None:
    await send_digest_step(org_id)


@DBOS.step()
async def orgs_due_now() -> list[dict]:
    async with system_session() as conn:
        rows = (await conn.execute(text("""
            select s.org_id, s.timezone, a.config from app.automation_instances a join app.org_settings s using (org_id)
            where a.template_key = 'inbox_triage' and a.status in ('live', 'approval_mode')"""))).mappings().all()
    due = []
    for r in rows:
        local = datetime.now(ZoneInfo(r["timezone"]))
        if local.hour == TriageConfig(**(r["config"] or {})).digest_hour:
            due.append({"org_id": r["org_id"], "date": local.date().isoformat()})
    return due


@DBOS.workflow()
async def schedule_digests(scheduled_time: datetime, context: Any) -> None:
    for d in await orgs_due_now():
        with SetWorkflowID(f"digest-{d['org_id']}-{d['date']}"):
            await DBOS.start_workflow_async(send_digest, d["org_id"])
