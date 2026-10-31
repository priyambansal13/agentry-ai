"""Notification Center in the worker: every catalogued event is planned (rules -> people) and sent; held and digest
notifications go out when their time comes; cards waiting too long raise approval.waiting_long."""
from datetime import datetime
from typing import Any

from dbos import DBOS
from sqlalchemy import text

from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.notify import center
from agentry.worker.handlers import on

WAITING_HOURS = 4


@DBOS.step()
async def plan_step(event: dict) -> list[int]:
    return await center.plan(event)


@DBOS.step()
async def deliver_step(org_id: str, ids: list[int]) -> dict:
    return await center.deliver(org_id, ids)


@DBOS.workflow()
async def notify_event(event: dict) -> None:
    ids = await plan_step(event)
    if ids:
        await deliver_step(event["org_id"], ids)


for _event_type in center.CATALOGUE:
    on(_event_type)(notify_event)


@DBOS.step()
async def release_step() -> int:
    return await center.release_due()


@DBOS.workflow()
async def release_notifications(scheduled_time: datetime, context: Any) -> None:
    await release_step()


@DBOS.step()
async def waiting_step() -> int:
    """Cards pending for WAITING_HOURS (not snoozed) raise approval.waiting_long once."""
    async with system_session() as conn:
        rows = (await conn.execute(text(f"""select org_id, id::text, extract(epoch from now() - created_at) / 3600 as hours from app.approvals
            where status = 'pending' and created_at < now() - interval '{WAITING_HOURS} hours'
              and (snoozed_until is null or snoozed_until <= now()) and not (payload ? 'waiting_alerted')"""))).all()
    for org_id, aid, hours in rows:
        async with tenant_session(org_id) as conn:
            await conn.execute(text("update app.approvals set payload = payload || '{\"waiting_alerted\": true}' where id = cast(:i as uuid)"), {"i": aid})
            await emit(conn, org_id, "approval.waiting_long", {"approval_id": aid, "hours": round(float(hours))})
    return len(rows)


@DBOS.workflow()
async def cards_waiting(scheduled_time: datetime, context: Any) -> None:
    await waiting_step()


@DBOS.step()
async def pulse_step() -> int:
    """Briefs due this hour (each business's own timezone and chosen hour), once a day; Mondays add the week."""
    from datetime import UTC
    from zoneinfo import ZoneInfo

    from agentry import pulse
    n = 0
    now = datetime.now(UTC)
    for org_id, period in await pulse.due(now):
        await pulse.send(org_id, period, now)
        async with tenant_session(org_id) as conn:
            tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one()
        await pulse.mark_sent(org_id, period, now.astimezone(ZoneInfo(tz or "Asia/Kolkata")).date())
        n += 1
    return n


@DBOS.workflow()
async def send_pulses(scheduled_time: datetime, context: Any) -> None:
    await pulse_step()
