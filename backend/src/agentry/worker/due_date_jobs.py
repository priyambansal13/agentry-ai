"""Statutory due-date changes (automations/ca/due_dates.py): the daily check of official sources, and "check now"."""
from dbos import DBOS

from agentry.automations.ca import due_dates
from agentry.worker.handlers import on


@DBOS.step()
async def due_date_sync_step(sync_id: str | None, trigger: str) -> dict:
    return await due_dates.run_sync(sync_id, trigger)


@on("due_dates.sync_requested")
@DBOS.workflow()
async def on_due_date_sync(event: dict) -> None:
    await due_date_sync_step(event["payload"]["sync_id"], "requested")


@DBOS.workflow()
async def due_dates_daily(scheduled_time, context) -> None:
    await due_date_sync_step(None, "daily")


# ---------- MSME 45-day cards (automations/invoice_follow_up/msme.py) ----------

@DBOS.step()
async def msme_cards_step() -> int:
    from sqlalchemy import text

    from agentry import official_rules
    from agentry.automations.invoice_follow_up import msme
    from agentry.db import system_session
    await official_rules.fresh()
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select s.org_id from app.org_settings s join app.automation_instances a on a.org_id = s.org_id
            and a.template_key = 'invoice_follow_up' and a.status in ('live','approval_mode') where coalesce((s.msme->>'enabled')::boolean, false)"""))).scalars())
    return sum([await msme.cards(o) for o in orgs])


@DBOS.workflow()
async def msme_daily(scheduled_time, context) -> None:
    await msme_cards_step()
