"""Outbound delivery of human-approved replies, and the Gmail sync schedule.

Approving a reply in "Needs you" records it immediately; this workflow then sends it through the channel the
conversation came from (Gmail draft -> sent; WhatsApp text, if still inside the 24-hour window). Failures are
written back onto the message so the portal can show them.
"""
import json
from datetime import UTC, datetime
from typing import Any

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text

from agentry.connectors.store import all_connected
from agentry.db import tenant_session
from agentry.worker.handlers import on


@DBOS.step()
async def approved_reply(org_id: str, approval_id: str) -> dict | None:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""
            select a.body, a.conversation_id, c.metadata->>'source' as source, c.external_ref,
                   (select id from app.messages m where m.metadata->>'approval_id' = :a limit 1) as message_id
            from app.approvals a join app.conversations c on c.id = a.conversation_id
            where a.id = cast(:a as uuid) and a.kind = 'reply_draft' and a.status in ('approved', 'edited')"""), {"a": approval_id})).mappings().first()
    return {k: (str(v) if v is not None else None) for k, v in row.items()} if row else None


@DBOS.step(retries_allowed=True, max_attempts=4)
async def send_approved(org_id: str, r: dict) -> dict:
    if r["source"] == "gmail":
        from agentry.connectors.gmail import GmailMailbox
        sent_id = await GmailMailbox().send_reply(org_id, r["conversation_id"], r["body"])
        return {"external_id": f"gmail:{sent_id}", "delivery": "sent"}
    if r["source"] == "outlook":
        from agentry.connectors.outlook import OutlookMailbox
        sent_id = await OutlookMailbox().send_reply(org_id, r["conversation_id"], r["body"])
        return {"external_id": f"outlook:{sent_id}", "delivery": "sent"}
    if r["source"] == "whatsapp":
        from agentry.connectors.whatsapp import send_text, within_window
        if not await within_window(org_id, r["conversation_id"]):
            return {"delivery": "failed", "delivery_error": "Outside WhatsApp's 24-hour window: send a template instead."}
        wamid = await send_text(org_id, r["external_ref"].removeprefix("wa:"), r["body"])
        return {"external_id": f"wa:{wamid}", "delivery": "sent"}
    return {"delivery": "recorded"}  # local mailbox: nothing external to send


@DBOS.step()
async def mark_delivery(org_id: str, message_id: str | None, result: dict) -> None:
    if not message_id:
        return
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.messages set metadata = metadata || cast(:r as jsonb) where id = :m"),
                           {"r": json.dumps(result), "m": message_id})


@DBOS.step()
async def deliver_outbound_draft(org_id: str, approval_id: str) -> dict:
    """An approved sequence message (reminder, reactivation): send it now on its channel."""
    from agentry.outbound import deliver_outbound
    from agentry.sequences import _load
    async with tenant_session(org_id) as conn:
        a = (await conn.execute(text("""select body, payload from app.approvals where id = cast(:a as uuid)
            and kind = 'outbound_draft' and status in ('approved','edited')"""), {"a": approval_id})).mappings().first()
        if not a:
            return {"status": "skipped"}
        p = a["payload"]
        e = await _load(conn, p["enrollment_id"])
        from agentry.sequences import _resolved, _subject
        if e and (why := _resolved(e, await _subject(conn, e))):  # paid or disputed while the card waited (#5)
            await conn.execute(text("update app.approvals set payload = payload || jsonb_build_object('withdrawn', cast(:w as text)) where id = cast(:a as uuid)"),
                               {"w": why, "a": approval_id})
            return {"status": "skipped", "reason": why}
        result = await deliver_outbound(conn, org_id, enrollment=e, channel=p["channel"], subject=p.get("subject") or "",
                                        body=a["body"], template=p.get("template"), template_params=p.get("template_params") or [])
        await conn.execute(text("update app.approvals set payload = payload || jsonb_build_object('delivery', cast(:r as jsonb)) where id = cast(:a as uuid)"),
                           {"r": json.dumps(result), "a": approval_id})
        if result["status"] in ("sent", "recorded"):
            from agentry.events import emit
            await emit(conn, org_id, "message.sent", {"channel": p["channel"], "enrollment_id": p["enrollment_id"]})
            await conn.execute(text("""update app.sequence_enrollments set log = log || cast(:l as jsonb) where id = cast(:e as uuid)"""),
                               {"e": p["enrollment_id"], "l": json.dumps([{"step": p["step"], "at": datetime.now(UTC).isoformat(),
                                                                          "results": [{"channel": p["channel"], **result}]}])})
            if e and e["subject_type"] == "invoice" and p["step"] == len(e["steps"]) - 1:
                from agentry.sequences import _reminders_ended
                inv = await _subject(conn, e)
                if inv["status"] in ("open", "partially_paid"):  # the approved final reminder went out: next is a phone call
                    await _reminders_ended(conn, org_id, inv)
    return result


@on("approval.decided")
@DBOS.workflow()
async def deliver_approved_reply(event: dict) -> None:
    if event["payload"].get("status") not in ("approved", "edited"):
        return
    if event["payload"].get("kind") == "outbound_draft":
        await deliver_outbound_draft(event["org_id"], event["payload"]["approval_id"])
        return
    if event["payload"].get("kind") != "reply_draft":
        return
    r = await approved_reply(event["org_id"], event["payload"]["approval_id"])
    if not r:
        return
    try:
        result = await send_approved(event["org_id"], r)
    except Exception as e:  # noqa: BLE001 - recorded on the message for the portal; retries already happened
        result = {"delivery": "failed", "delivery_error": str(e)[:300]}
    await mark_delivery(event["org_id"], r["message_id"], result)


@DBOS.step()
async def gmail_sync_step(org_id: str) -> int:
    from agentry.connectors.gmail import GmailError, sync
    try:
        return await sync(org_id)
    except GmailError:
        return 0  # recorded on the connection (last_error); the portal shows it


@DBOS.workflow()
async def sync_one_gmail(org_id: str) -> None:
    await gmail_sync_step(org_id)


@DBOS.step()
async def outlook_sync_step(org_id: str) -> int:
    from agentry.connectors.outlook import OutlookError, sync
    try:
        return await sync(org_id)
    except OutlookError:
        return 0  # recorded on the connection (last_error); the portal shows it


@DBOS.workflow()
async def sync_one_outlook(org_id: str) -> None:
    await outlook_sync_step(org_id)


@DBOS.step()
async def outlook_connections() -> list[str]:
    return sorted({c["org_id"] for c in await all_connected("outlook")})


@DBOS.workflow()
async def poll_outlook(scheduled_time: datetime, context: Any) -> None:
    for org_id in await outlook_connections():
        with SetWorkflowID(f"outlook-sync-{org_id}-{int(scheduled_time.timestamp())}"):
            await DBOS.start_workflow_async(sync_one_outlook, org_id)


@on("gmail.push")
@DBOS.workflow()
async def on_gmail_push(event: dict) -> None:
    """Gmail push (#5): sync this client's inboxes right away."""
    await gmail_sync_step(event["org_id"])


@DBOS.step()
async def gmail_connections() -> list[str]:
    return sorted({c["org_id"] for c in await all_connected("gmail")})


@DBOS.workflow()
async def poll_gmail(scheduled_time: datetime, context: Any) -> None:
    for org_id in await gmail_connections():
        with SetWorkflowID(f"gmail-sync-{org_id}-{int(scheduled_time.timestamp())}"):
            await DBOS.start_workflow_async(sync_one_gmail, org_id)


@DBOS.step()
async def human_reply(org_id: str, message_id: str) -> dict | None:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select m.body, m.conversation_id, c.metadata->>'source' as source, c.external_ref, c.channel
            from app.messages m join app.conversations c on c.id = m.conversation_id where m.id = cast(:m as uuid)"""),
            {"m": message_id})).mappings().first()
    return {k: (str(v) if v is not None else None) for k, v in row.items()} if row else None


@on("reply.created")
@DBOS.workflow()
async def deliver_human_reply(event: dict) -> None:
    """A person replied from the portal: send it through the conversation's channel (the website chat widget picks
    replies up itself)."""
    r = await human_reply(event["org_id"], event["payload"]["message_id"])
    if not r:
        return
    if r["channel"] == "web_chat":
        result = {"delivery": "sent"}
    else:
        try:
            result = await send_approved(event["org_id"], r)
        except Exception as e:  # noqa: BLE001 - shown on the message in the portal
            result = {"delivery": "failed", "delivery_error": str(e)[:300]}
    await mark_delivery(event["org_id"], event["payload"]["message_id"], result)


@DBOS.step()
async def renew_gmail_watches_step() -> int:
    from agentry.connectors.gmail import renew_watches
    return await renew_watches()


@DBOS.workflow()
async def renew_gmail_watches(scheduled_time: datetime, context: Any) -> None:
    """Daily 05:00 IST: Gmail push subscriptions last 7 days; renew them (#5)."""
    await renew_gmail_watches_step()
