"""Agentry worker: outbox dispatch + metric rollups, on DBOS (durable workflows stored in Postgres).

Run: uv run agentry worker
"""
import asyncio
from datetime import datetime
from typing import Any

from dbos import DBOS, DBOSConfig, SetWorkflowID
from sqlalchemy import text

from agentry.automations import load_all
from agentry.automations.cold_email.sending import send_cold_emails
from agentry.automations.inbox_triage.digest import schedule_digests
from agentry.config import settings
from agentry.db import system_session
from agentry.metrics import rollup, sync_definitions
from agentry.worker.billing_jobs import (
    finalize_statements,
    inbox_follow_ups,
    monthly_reports,
    monthly_statements,
    onboarding_nudges,
    purge_email_text,
    purge_recordings,
    weekly_summaries,
)
from agentry.worker.delivery import poll_gmail, poll_outlook, renew_gmail_watches
from agentry.worker.handlers import HANDLERS
from agentry.worker.sales_jobs import check_sales_inbox
from agentry.worker.sequence_handlers import sequence_watchdog

load_all()  # register every automation's event handlers before DBOS launches

EVENTS_QUEUE = "events"


@DBOS.step()
async def fetch_pending(limit: int = 100) -> list[dict]:
    async with system_session() as conn:
        rows = (await conn.execute(
            text("""select id, org_id, type, payload, occurred_at from app.events
                    where dispatched_at is null order by id limit :l"""),
            {"l": limit},
        )).mappings().all()
    return [dict(r) | {"occurred_at": r["occurred_at"].isoformat()} for r in rows]


@DBOS.step()
async def mark_dispatched(ids: list[int]) -> None:
    async with system_session() as conn:
        await conn.execute(
            text("update app.events set dispatched_at = now(), attempts = attempts + 1 where id = any(:ids)"),
            {"ids": ids},
        )


@DBOS.workflow()
async def dispatch_outbox(scheduled_time: datetime, context: Any) -> None:
    """Hand pending outbox events to their handlers, then mark them dispatched.

    Enqueueing uses a deterministic workflow ID per (event, handler), so it is idempotent: if this run fails
    before mark_dispatched, the next run re-enqueues the same events and DBOS returns the existing workflows
    instead of starting duplicates. An event is only marked dispatched after every handler was enqueued.
    """
    events = await fetch_pending()
    if not events:
        return
    queue = await DBOS.retrieve_queue_async(EVENTS_QUEUE)
    if queue is None:  # only possible in the instant between launch and queue registration
        raise RuntimeError(f"queue {EVENTS_QUEUE} not registered yet")
    for event in events:
        for handler in HANDLERS.get(event["type"], []):
            with SetWorkflowID(f"evt-{event['id']}-{handler.__name__}"):
                await queue.enqueue_async(handler, event)
    await mark_dispatched([e["id"] for e in events])


@DBOS.step()
async def rollup_step() -> int:
    async with system_session() as conn:
        return await rollup(conn)


@DBOS.workflow()
async def rollup_metrics(scheduled_time: datetime, context: Any) -> None:
    await rollup_step()


async def run() -> None:
    async with system_session() as conn:
        await sync_definitions(conn)
    DBOS(config=DBOSConfig(name="agentry", system_database_url=settings.dbos_database_url, dbos_system_schema="dbos"))
    DBOS.launch()
    await DBOS.register_queue_async(EVENTS_QUEUE, worker_concurrency=8)
    await DBOS.apply_schedules_async([
        {"schedule_name": "dispatch-outbox", "workflow_fn": dispatch_outbox, "schedule": "*/5 * * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
        {"schedule_name": "rollup-metrics", "workflow_fn": rollup_metrics, "schedule": "0 */5 * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
        {"schedule_name": "inbox-digests", "workflow_fn": schedule_digests, "schedule": "0 0 * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
        {"schedule_name": "monthly-statements", "workflow_fn": monthly_statements, "schedule": "0 30 6 1 * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "monthly-reports", "workflow_fn": monthly_reports, "schedule": "0 0 9 2 * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "onboarding-nudges", "workflow_fn": onboarding_nudges, "schedule": "0 0 10 * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        *([{"schedule_name": "sales-inbox", "workflow_fn": check_sales_inbox,
             "schedule": f"0 */{settings.sales_inbox_minutes} * * * *", "context": None, "automatic_backfill": False,
             "cron_timezone": None, "queue_name": None}] if settings.sales_inbox_minutes > 0 else []),
        {"schedule_name": "weekly-summaries", "workflow_fn": weekly_summaries, "schedule": "0 0 9 * * 1",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "inbox-follow-ups", "workflow_fn": inbox_follow_ups, "schedule": "0 30 10 * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "purge-email-text", "workflow_fn": purge_email_text, "schedule": "0 45 3 * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "purge-recordings", "workflow_fn": purge_recordings, "schedule": "0 30 3 * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "finalize-statements", "workflow_fn": finalize_statements, "schedule": "0 15 7 * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "cold-email-send", "workflow_fn": send_cold_emails, "schedule": "0 */5 * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
        {"schedule_name": "sequence-watchdog", "workflow_fn": sequence_watchdog, "schedule": "30 */10 * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
        {"schedule_name": "gmail-watch-renewal", "workflow_fn": renew_gmail_watches, "schedule": "0 0 5 * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": "Asia/Kolkata", "queue_name": None},
        {"schedule_name": "outlook-sync", "workflow_fn": poll_outlook, "schedule": "15 * * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
        {"schedule_name": "gmail-sync", "workflow_fn": poll_gmail, "schedule": f"*/{max(15, settings.gmail_poll_seconds)} * * * * *"
         if settings.gmail_poll_seconds < 60 else "0 * * * * *",
         "context": None, "automatic_backfill": False, "cron_timezone": None, "queue_name": None},
    ])
    await DBOS.start_workflow_async(sequence_watchdog, datetime.now(), None)  # recover enrollments on every boot
    DBOS.logger.info("agentry worker running: outbox every 5 s, metric rollups every 5 min")
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(run())
