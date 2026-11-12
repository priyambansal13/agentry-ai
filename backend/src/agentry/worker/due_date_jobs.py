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
