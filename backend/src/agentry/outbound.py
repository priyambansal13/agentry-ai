"""Business-initiated messages (sequence steps): deliver on one channel and record them in a conversation.

email    -> the client's mailbox: the inbox chosen in the automation's settings ("send_from"), else the first Gmail,
            else the first Outlook. Later steps for the same invoice/lead continue the same thread, so the customer
            sees one conversation. Without any mailbox the message is only recorded (delivery 'recorded').
whatsapp -> an approved template (Meta requires templates for messages the business starts).
Every message is tagged with what it is about (subject_type/subject_id), so replies find their invoice or lead.
"""
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.connectors.store import get_connection


async def channel_problem(org_id: str, channel: str, template: str | None = None) -> str | None:
    """Why a message can't go out on this channel right now (None: it can). Checked before a card is made, before it
    is approved, and again on delivery, so nobody approves a message that would silently go nowhere."""
    if channel == "whatsapp":
        if not template:
            return "no approved WhatsApp template for this step"
        if not await get_connection(org_id, "whatsapp"):
            return "WhatsApp not connected"
    return None


async def _conversation(conn: AsyncConnection, org_id: str, *, channel: str, ref: str, contact_id: str | None,
                        subject: str, enrollment: dict, source: str, mailbox: str | None = None) -> str:
    meta = {"source": source, "subject_type": enrollment["subject_type"], "subject_id": str(enrollment["subject_id"]),
            "enrollment_id": str(enrollment["id"]), **({"mailbox": mailbox} if mailbox else {})}
    return str((await conn.execute(text("""
        insert into app.conversations (org_id, channel, automation_key, contact_id, subject, external_ref, metadata)
        values (:o, :ch, :a, :k, :s, :ref, cast(:m as jsonb))
        on conflict (org_id, channel, external_ref) do update set last_message_at = now(),
          metadata = app.conversations.metadata || excluded.metadata
        returning id"""), {"o": org_id, "ch": channel, "a": enrollment["automation_key"], "k": contact_id or enrollment["contact_id"],
                           "s": subject, "ref": ref, "m": json.dumps(meta)})).scalar_one())


async def _record(conn: AsyncConnection, org_id: str, conv: str, body: str, meta: dict, enrollment: dict | None = None) -> None:
    if enrollment:
        meta = {**meta, "subject_type": enrollment["subject_type"], "subject_id": str(enrollment["subject_id"]),
                "enrollment_id": str(enrollment["id"])}
    await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
        values (:o, :c, 'out', 'agent', :b, cast(:m as jsonb))"""), {"o": org_id, "c": conv, "b": body, "m": json.dumps(meta)})


async def _sending_mailbox(conn: AsyncConnection, org_id: str, automation_key: str) -> dict | None:
    """The mailbox reminders go out from: the one chosen in settings, else the first Gmail, else the first Outlook."""
    from agentry.connectors.store import get_connections
    chosen = (await conn.execute(text("select config->>'send_from' from app.automation_instances where template_key = :k"),
                                 {"k": automation_key})).scalar_one_or_none()
    boxes = [c for c in await get_connections(org_id, "gmail") + await get_connections(org_id, "outlook") if c["status"] == "connected"]
    return next((c for c in boxes if chosen and c["account_ref"] == chosen.lower()), boxes[0] if boxes else None)


async def _previous_thread(conn: AsyncConnection, enrollment: dict, provider: str) -> dict | None:
    """The thread an earlier step of this enrollment started, to continue it."""
    return (await conn.execute(text("""select c.external_ref, c.subject from app.conversations c
        where c.metadata->>'enrollment_id' = :e and c.channel = 'email' and c.external_ref like :p
        order by c.created_at limit 1"""), {"e": str(enrollment["id"]), "p": f"{provider}:%"})).mappings().first()


async def deliver_outbound(conn: AsyncConnection, org_id: str, *, enrollment: dict, channel: str, subject: str, body: str,
                           template: str | None, template_params: list[str]) -> dict:
    contact = (await conn.execute(text("select email, phone_e164 from app.contacts where id = :c"),
                                  {"c": enrollment["contact_id"]})).mappings().one()
    try:
        if channel == "email":
            if not contact["email"]:
                return {"status": "skipped", "reason": "no email address"}
            box = await _sending_mailbox(conn, org_id, enrollment["automation_key"])
            if box and box["provider"] == "gmail":
                from agentry.connectors.gmail import Gmail
                prev = await _previous_thread(conn, enrollment, "gmail")
                sent = await Gmail(org_id, box).send_new(
                    to=contact["email"], subject=f"Re: {prev['subject']}" if prev else subject, body=body,
                    thread_id=prev["external_ref"].split(":", 1)[1] if prev else None)
                conv = await _conversation(conn, org_id, channel="email", ref=f"gmail:{sent['threadId']}", contact_id=enrollment["contact_id"],
                                           subject=prev["subject"] if prev else subject, enrollment=enrollment, source="gmail", mailbox=box["account_ref"])
                await _record(conn, org_id, conv, body, {"external_id": f"gmail:{sent['id']}", "delivery": "sent",
                                                          "gmail": {"message_id": sent["id"], "thread_id": sent["threadId"]}}, enrollment)
                return {"status": "sent", "conversation_id": conv}
            if box and box["provider"] == "outlook":
                from agentry.connectors.outlook import Outlook
                sent = await Outlook(org_id, box).send_new(to=contact["email"], subject=subject, body=body)
                conv = await _conversation(conn, org_id, channel="email", ref=f"outlook:{sent['conversationId']}", contact_id=enrollment["contact_id"],
                                           subject=subject, enrollment=enrollment, source="outlook", mailbox=box["account_ref"])
                await _record(conn, org_id, conv, body, {"external_id": f"outlook:{sent['id']}", "delivery": "sent"}, enrollment)
                return {"status": "sent", "conversation_id": conv}
            conv = await _conversation(conn, org_id, channel="email", ref=f"seq:{enrollment['id']}:email", contact_id=enrollment["contact_id"],
                                       subject=subject, enrollment=enrollment, source="local")
            await _record(conn, org_id, conv, body, {"delivery": "recorded", "to": contact["email"]}, enrollment)
            return {"status": "recorded", "conversation_id": conv}
        if channel == "whatsapp":
            if why := await channel_problem(org_id, "whatsapp", template):
                return {"status": "skipped", "reason": why}
            from agentry.connectors.whatsapp import send_template
            wa_id = contact["phone_e164"].lstrip("+")
            wamid = await send_template(org_id, wa_id, template, params=template_params)
            conv = await _conversation(conn, org_id, channel="whatsapp", ref=f"wa:{wa_id}", contact_id=enrollment["contact_id"],
                                       subject="WhatsApp", enrollment=enrollment, source="whatsapp")
            await _record(conn, org_id, conv, f"[template {template}] " + " · ".join(template_params),
                          {"external_id": f"wa:{wamid}", "delivery": "sent", "template": template}, enrollment)
            return {"status": "sent", "conversation_id": conv}
        return {"status": "skipped", "reason": f"channel {channel} not available yet"}
    except Exception as e:  # noqa: BLE001 - one channel failing must not stop the others; recorded in the enrollment log
        return {"status": "failed", "reason": str(e)[:300]}
