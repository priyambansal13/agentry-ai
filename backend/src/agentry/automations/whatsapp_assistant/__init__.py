"""WhatsApp assistant: the client's agent (same AgentSpec as website chat) answering on their WhatsApp number.

live           -> replies are sent immediately (customer-initiated, inside Meta's 24-hour window)
approval_mode  -> replies wait in "Needs you" and are sent when approved
Non-text messages (voice notes, images) and conversations handed to a person are routed to the team.
"""
import json

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.agents.runtime import run_turn
from agentry.automations import AutomationTemplate, register
from agentry.config import settings
from agentry.connectors.whatsapp import send_text
from agentry.db import tenant_session
from agentry.leads import advance, claim
from agentry.llm.gateway import AllModelsFailed
from agentry.notify.alerts import send_owner_alert
from agentry.worker.handlers import on


class WhatsAppConfig(BaseModel):
    alert_template: str | None = Field(None, title="Approved template for owner alerts",
                                       description="Needed to alert you on WhatsApp outside a 24-hour window.",
                                       json_schema_extra={"editable_by": "agentry"})
    busy_reply: str = Field("Thanks for your message! A member of our team will reply shortly.",
                            title="Reply when a person needs to take over", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="whatsapp_assistant",
    name="WhatsApp assistant",
    description="Your AI assistant on your WhatsApp number: answers questions, qualifies and books, hands off to you.",
    config_model=WhatsAppConfig,
    metrics=("leads_captured", "appointments_booked", "messages_sent"),
))


@DBOS.step()
async def load_context(org_id: str, conversation_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select c.status as conv_status, a.status as automation_status, a.config
            from app.conversations c left join app.automation_instances a on a.template_key = 'whatsapp_assistant'
            where c.id = :c"""), {"c": conversation_id})).mappings().one()
        from agentry.automations.invoice_follow_up import invoice_in_conversation
        invoice = await invoice_in_conversation(conn, conversation_id, "whatsapp")
    return {"conv_status": row["conv_status"], "automation_status": row["automation_status"], "invoice_reply": bool(invoice),
            "config": WhatsAppConfig(**(row["config"] or {})).model_dump()}


@DBOS.step()
async def take_over_lead(org_id: str, conversation_id: str) -> str | None:
    """The customer wrote in: this conversation owns the lead now (stops reactivation / speed-to-lead sequences)."""
    async with tenant_session(org_id) as conn:
        lead = (await conn.execute(text("""select l.id, l.qualification from app.leads l join app.conversations c on c.contact_id = l.contact_id
            where c.id = :c and l.stage not in ('won','lost','disqualified','opted_out') order by l.created_at desc limit 1"""),
            {"c": conversation_id})).first()
        if not lead:
            return None
        await claim(conn, str(lead.id), "whatsapp_assistant", inbound=True)
        await advance(conn, str(lead.id), "engaged")
        q = lead.qualification or {}
        known = [f"{k.replace('_', ' ')}: {v}" for k, v in q.items() if k in ("interest", "need", "last_contact", "previous_status", "notes") and v]
        return ("What we already know about this person: " + "; ".join(known)) if known else None


@DBOS.step()
async def agent_reply(org_id: str, conversation_id: str, user_text: str, send_now: bool, context: str | None = None) -> dict:
    try:
        return await run_turn(org_id, conversation_id, user_text, source="whatsapp", channel="whatsapp",
                              persist_inbound=False, persist_reply=send_now, context=context)
    except AllModelsFailed:
        return {"reply": None, "booking": None, "tools": [], "message_id": None, "failed": True}


@DBOS.step(retries_allowed=True, max_attempts=4)
async def deliver(org_id: str, conversation_id: str, wa_id: str, body: str, message_id: str | None) -> str:
    wamid = await send_text(org_id, wa_id, body)
    async with tenant_session(org_id) as conn:
        if message_id:
            await conn.execute(text("""update app.messages set metadata = metadata || jsonb_build_object('external_id', cast(:x as text))
                where id = :m"""), {"x": f"wa:{wamid}", "m": message_id})
        else:
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
                values (:o, :c, 'out', 'agent', :b, jsonb_build_object('external_id', cast(:x as text)))"""),
                {"o": org_id, "c": conversation_id, "b": body, "x": f"wa:{wamid}"})
    return wamid


@DBOS.step()
async def queue_for_approval(org_id: str, conversation_id: str, wa_id: str, body: str) -> None:
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
            values (:o, 'reply_draft', 'whatsapp_assistant', :c, :t, :b, cast(:p as jsonb))"""),
            {"o": org_id, "c": conversation_id, "t": f"WhatsApp reply to +{wa_id}", "b": body,
             "p": json.dumps({"channel": "whatsapp"})})


@DBOS.step()
async def hand_to_team(org_id: str, conversation_id: str, wa_id: str, reason: str) -> None:
    async with tenant_session(org_id) as conn:  # a person takes it from here: the assistant stays quiet until handed back
        await conn.execute(text("update app.conversations set status = 'handed_off' where id = :c"), {"c": conversation_id})
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body)
            values (:o, 'handoff', 'whatsapp_assistant', :c, :t, :r)"""),
            {"o": org_id, "c": conversation_id, "t": f"WhatsApp from +{wa_id} needs a person", "r": reason})
    await send_owner_alert(org_id, f"WhatsApp from +{wa_id} needs you",
                           f"{reason}\n\nOpen: {settings.dashboard_url}/conversations/{conversation_id}")


@on("whatsapp.received")
@DBOS.workflow()
async def answer_whatsapp(event: dict) -> None:
    org_id, p = event["org_id"], event["payload"]
    ctx = await load_context(org_id, p["conversation_id"])
    if ctx["automation_status"] not in ("live", "approval_mode"):
        return  # assistant paused or not set up: the team sees the message in Conversations
    if ctx["conv_status"] == "handed_off":
        return  # a person is handling this conversation
    if ctx["invoice_reply"]:
        return  # a reply to a recent invoice reminder: the invoice agent handles it
    if p.get("type") != "text":
        await hand_to_team(org_id, p["conversation_id"], p["wa_id"], f"Customer sent a {p.get('type')} message.")
        await deliver(org_id, p["conversation_id"], p["wa_id"], ctx["config"]["busy_reply"], None)
        return
    send_now = ctx["automation_status"] == "live"
    context = await take_over_lead(org_id, p["conversation_id"])
    r = await agent_reply(org_id, p["conversation_id"], p["text"], send_now, context)
    if not r.get("reply"):
        await hand_to_team(org_id, p["conversation_id"], p["wa_id"], "The AI could not answer (all models failed).")
        return
    if send_now:
        await deliver(org_id, p["conversation_id"], p["wa_id"], r["reply"], r["message_id"])
    else:
        await queue_for_approval(org_id, p["conversation_id"], p["wa_id"], r["reply"])


@on("whatsapp.opted_out")
@DBOS.workflow()
async def confirm_opt_out(event: dict) -> None:
    """One last message confirming the opt-out (allowed: the customer just wrote to us), then silence."""
    p = event["payload"]
    await deliver(event["org_id"], p["conversation_id"], p["wa_id"],
                  "You won't receive any more messages from us here. Reply START any time to talk again.", None)
