"""Start a durable workflow for each new sequence enrollment."""
from dbos import DBOS

from agentry.sequences import start
from agentry.worker.handlers import on


@on("sequence.enrolled")
@DBOS.workflow()
async def start_enrollment(event: dict) -> None:
    await start(event["org_id"], event["payload"]["enrollment_id"])


@on("sequence.changed")
@DBOS.workflow()
async def wake_changed(event: dict) -> None:
    """Paused / resumed / stopped from the portal: the sleeping workflow re-plans now."""
    from agentry.sequences import wake
    await wake(event["payload"]["enrollment_id"], event["payload"].get("action", "changed"))


@DBOS.step()
async def active_enrollments() -> list[tuple[str, str]]:
    from sqlalchemy import text

    from agentry.db import system_session
    async with system_session() as conn:
        rows = (await conn.execute(text("""select org_id, id from app.sequence_enrollments
            where status in ('active','paused') order by created_at"""))).all()
    return [(r.org_id, str(r.id)) for r in rows]


@DBOS.step()
async def reminders_ended_backfill() -> int:
    """Invoices whose reminders all went out (before this check existed, or while the worker was down) and that are
    still unpaid get their "time for a call" card (once; sequences._reminders_ended)."""
    from sqlalchemy import text

    from agentry.db import system_session, tenant_session
    from agentry.sequences import _reminders_ended
    async with system_session() as conn:
        rows = (await conn.execute(text("""select distinct e.org_id, e.subject_id from app.sequence_enrollments e
            join app.invoices i on i.id = e.subject_id
            where e.subject_type = 'invoice' and e.status = 'completed' and e.stop_reason = 'all steps sent'
              and i.status in ('open', 'partially_paid') and i.reminders_ended_at is null
              and exists (select 1 from jsonb_array_elements(e.log) st, jsonb_array_elements(st->'results') r
                          where (st->>'step')::int = (select jsonb_array_length(s.steps) - 1 from app.sequences s where s.id = e.sequence_id)
                            and r->>'status' in ('sent', 'recorded'))"""))).all()
    for org_id, invoice_id in rows:
        async with tenant_session(org_id) as conn:
            inv = (await conn.execute(text("""select i.*, k.name as contact_name, k.company, k.phone_e164 from app.invoices i
                left join app.contacts k on k.id = i.contact_id where i.id = :i"""), {"i": invoice_id})).mappings().one()
            await _reminders_ended(conn, org_id, dict(inv))
    return len(rows)


@DBOS.workflow()
async def sequence_watchdog(scheduled_time, context) -> None:
    """Every active enrollment must have its workflow running. Starting one that already exists is a no-op (fixed
    workflow id), so this safely repairs enrollments whose start event was missed, e.g. during a deploy."""
    for org_id, eid in await active_enrollments():
        await start(org_id, eid)
    await reminders_ended_backfill()
