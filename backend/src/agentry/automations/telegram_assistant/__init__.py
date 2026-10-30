"""Telegram assistant: the business's AI assistant (same agent as website chat and WhatsApp) on the business's own
Telegram bot.

live           -> replies go out straight away
approval_mode  -> replies wait in "Needs you" and are sent when approved
Voice notes, photos and files, and conversations handed to a person, go to the team. A customer can share their phone
number with the bot; it's added to their contact. Telegram bots can only reply to people who wrote first.
"""
import json

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.agents.runtime import run_turn
from agentry.automations import AutomationTemplate, register
from agentry.config import settings
from agentry.connectors.telegram import send_to_customer
from agentry.db import tenant_session
from agentry.leads import advance, claim
from agentry.llm.gateway import AllModelsFailed
from agentry.notify.alerts import send_owner_alert
from agentry.worker.handlers import on


class TelegramConfig(BaseModel):
    busy_reply: str = Field("Thanks for your message! A member of our team will reply shortly.",
                            title="Reply when a person needs to take over", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="telegram_assistant",
    name="Telegram assistant",
    description="Your AI assistant on your own Telegram bot: answers questions, qualifies and books, hands off to you.",
    config_model=TelegramConfig,
    metrics=("leads_captured", "appointments_booked", "messages_sent"),
))


@DBOS.step()
async def tg_context(org_id: str, conversation_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select c.status as conv_status, a.status as automation_status, a.config
            from app.conversations c left join app.automation_instances a on a.template_key = 'telegram_assistant'
            where c.id = :c"""), {"c": conversation_id})).mappings().one()
    return {"conv_status": row["conv_status"], "automation_status": row["automation_status"],
            "config": TelegramConfig(**(row["config"] or {})).model_dump()}


@DBOS.step()
async def tg_take_over_lead(org_id: str, conversation_id: str) -> str | None:
    async with tenant_session(org_id) as conn:
        lead = (await conn.execute(text("""select l.id, l.qualification from app.leads l join app.conversations c on c.contact_id = l.contact_id
            where c.id = :c and l.stage not in ('won','lost','disqualified','opted_out') order by l.created_at desc limit 1"""),
            {"c": conversation_id})).first()
        if not lead:
            return None
        await claim(conn, str(lead.id), "telegram_assistant", inbound=True)
        await advance(conn, str(lead.id), "engaged")
        q = lead.qualification or {}
        known = [f"{k.replace('_', ' ')}: {v}" for k, v in q.items() if k in ("interest", "need", "last_contact", "previous_status", "notes") and v]
        return ("What we already know about this person: " + "; ".join(known)) if known else None


@DBOS.step()
async def tg_agent_reply(org_id: str, conversation_id: str, user_text: str, send_now: bool, context: str | None = None) -> dict:
    try:
        return await run_turn(org_id, conversation_id, user_text, source="telegram", channel="telegram",
                              persist_inbound=False, persist_reply=send_now, context=context)
    except AllModelsFailed:
        return {"reply": None, "booking": None, "tools": [], "message_id": None, "failed": True}


@DBOS.step(retries_allowed=True, max_attempts=4)
async def tg_deliver(org_id: str, conversation_id: str, chat_id: int, body: str, message_id: str | None) -> int:
    sent = await send_to_customer(org_id, chat_id, body)
    async with tenant_session(org_id) as conn:
        if message_id:
            await conn.execute(text("""update app.messages set metadata = metadata || jsonb_build_object('external_id', cast(:x as text))
                where id = :m"""), {"x": f"tg:{chat_id}:{sent}", "m": message_id})
        else:
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
                values (:o, :c, 'out', 'agent', :b, jsonb_build_object('external_id', cast(:x as text)))"""),
                {"o": org_id, "c": conversation_id, "b": body, "x": f"tg:{chat_id}:{sent}"})
    return sent


@DBOS.step()
async def tg_queue_for_approval(org_id: str, conversation_id: str, who: str, body: str) -> None:
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
            values (:o, 'reply_draft', 'telegram_assistant', :c, :t, :b, cast(:p as jsonb))"""),
            {"o": org_id, "c": conversation_id, "t": f"Telegram reply to {who}", "b": body, "p": json.dumps({"channel": "telegram"})})


@DBOS.step()
async def tg_hand_to_team(org_id: str, conversation_id: str, who: str, reason: str) -> None:
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.conversations set status = 'handed_off' where id = :c"), {"c": conversation_id})
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body)
            values (:o, 'handoff', 'telegram_assistant', :c, :t, :r)"""),
            {"o": org_id, "c": conversation_id, "t": f"Telegram from {who} needs a person", "r": reason})
    await send_owner_alert(org_id, f"Telegram from {who} needs you", f"{reason}\n\nOpen: {settings.dashboard_url}/conversations/{conversation_id}")


async def _who(org_id: str, conversation_id: str) -> str:
    async with tenant_session(org_id) as conn:
        return (await conn.execute(text("""select coalesce(k.name, 'a customer') from app.conversations c left join app.contacts k on k.id = c.contact_id
            where c.id = :c"""), {"c": conversation_id})).scalar_one()


@on("telegram.received")
@DBOS.workflow()
async def answer_telegram(event: dict) -> None:
    org_id, p = event["org_id"], event["payload"]
    ctx = await tg_context(org_id, p["conversation_id"])
    if ctx["automation_status"] not in ("live", "approval_mode") or ctx["conv_status"] == "handed_off":
        return  # paused / not set up, or a person is handling it: the team sees the message in Conversations
    who = await _who(org_id, p["conversation_id"])
    if p.get("type") not in ("text", "contact"):
        await tg_hand_to_team(org_id, p["conversation_id"], who, f"Customer sent a {p.get('type')} message.")
        await tg_deliver(org_id, p["conversation_id"], p["chat_id"], ctx["config"]["busy_reply"], None)
        return
    send_now = ctx["automation_status"] == "live"
    context = await tg_take_over_lead(org_id, p["conversation_id"])
    r = await tg_agent_reply(org_id, p["conversation_id"], p["text"], send_now, context)
    if not r.get("reply"):
        await tg_hand_to_team(org_id, p["conversation_id"], who, "The AI could not answer (all models failed).")
        return
    if send_now:
        await tg_deliver(org_id, p["conversation_id"], p["chat_id"], r["reply"], r["message_id"])
    else:
        await tg_queue_for_approval(org_id, p["conversation_id"], who, r["reply"])


@on("telegram.opted_out")
@DBOS.workflow()
async def confirm_telegram_opt_out(event: dict) -> None:
    p = event["payload"]
    await tg_deliver(event["org_id"], p["conversation_id"], p["chat_id"],
                     "You won't receive any more messages from us here. Send a message any time to talk again.", None)
