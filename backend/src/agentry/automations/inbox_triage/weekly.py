"""The Monday summary (#19): last week in numbers, to the people who get "weekly" alerts (owners by default), on
WhatsApp when they chose it (and the client's number can carry alerts), otherwise by email."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.automations.inbox_triage.insights import FIRST_REPLY_SQL, _median_minutes
from agentry.db import system_session, tenant_session
from agentry.notify.alerts import send_owner_alert


def _mins(m: float | None) -> str:
    if m is None:
        return "no replies yet"
    return f"{round(m)} min" if m < 90 else f"{m / 60:.1f} h"


async def week_numbers(org_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select
              count(*) filter (where m.metadata ? 'triage') as sorted,
              count(*) filter (where (m.metadata->'triage'->>'urgent')::boolean) as urgent,
              count(*) filter (where (m.metadata->'triage'->>'suspicious')::boolean) as suspicious,
              count(*) filter (where m.metadata->'triage'->>'category' = 'Lead') as leads
            from app.messages m join app.conversations c on c.id = m.conversation_id
            where c.automation_key = 'inbox_triage' and m.direction = 'in' and m.created_at > now() - interval '7 days'"""))).mappings().one()
        sent = (await conn.execute(text("""select count(*) from app.approvals where automation_key = 'inbox_triage' and kind = 'reply_draft'
            and status in ('approved', 'edited') and decided_at > now() - interval '7 days'"""))).scalar_one()
        now = datetime.now(UTC)
        replies = (await conn.execute(text(FIRST_REPLY_SQL), {"a": now - timedelta(days=7), "b": now})).all()
    return dict(row) | {"drafts_sent": sent, "first_reply": _median_minutes(replies), "hours_saved": round(row["sorted"] * 2 / 60, 1)}


async def send_week(org_id: str) -> str:
    n = await week_numbers(org_id)
    if not n["sorted"]:
        return "quiet week"
    subject = f"Your week with Agentry: {n['sorted']} emails sorted, about {n['hours_saved']} h saved"
    body = (f"Emails sorted: {n['sorted']}\nUrgent caught: {n['urgent']}\nNew leads: {n['leads']}\nReplies sent from drafts: {n['drafts_sent']}\n"
            f"Typical first reply: {_mins(n['first_reply'])}" + (f"\nPossible fraud flagged: {n['suspicious']}" if n["suspicious"] else ""))
    return await send_owner_alert(org_id, subject, body, kind="weekly")


async def run_weekly() -> int:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'inbox_triage'
            and status in ('live', 'approval_mode')"""))).scalars())
    return sum([(await send_week(o)) not in ("quiet week", "none") for o in orgs])
