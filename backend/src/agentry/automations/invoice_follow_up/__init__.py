"""Invoice follow-up (docs/automations/invoice-follow-up.md): reminders on days 7/14/21/28 after the due date,
stop on payment, and act on what customers reply."""
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.automations import AutomationTemplate, register
from agentry.db import tenant_session
from agentry.leads import opt_out
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.sequences import wake
from agentry.worker.handlers import on


class InvoiceConfig(BaseModel):
    payment_links: bool = Field(True, title="Add a payment link to reminders (when Razorpay is connected)",
                                json_schema_extra={"editable_by": "client"})
    promise_grace_days: int = Field(1, ge=0, le=7, title="Days to wait after a promised payment date",
                                    json_schema_extra={"editable_by": "client"})
    commission_basis: str = Field("overdue_only", title="Commission basis", json_schema_extra={"editable_by": "agentry"})
    send_from: str | None = Field(None, title="Send reminders from (email address)",
                                  description="One of your connected inboxes, e.g. accounts@. Empty = the first connected inbox.",
                                  json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="invoice_follow_up",
    name="Invoice follow-up",
    description="Polite, then firm reminders on days 7, 14, 21 and 28 after the due date. Stops the moment it's paid.",
    config_model=InvoiceConfig,
    metrics=("amount_recovered", "messages_sent"),
))


async def _active_enrollments(conn, invoice_id: str) -> list[str]:
    return [str(r) for r in (await conn.execute(text("""select id from app.sequence_enrollments
        where subject_type = 'invoice' and subject_id = :i and status in ('active','paused')"""), {"i": invoice_id})).scalars()]


@DBOS.step()
async def enrollments_for(org_id: str, invoice_id: str) -> list[str]:
    async with tenant_session(org_id) as conn:
        return await _active_enrollments(conn, invoice_id)


@on("payment.received")
@DBOS.workflow()
async def stop_on_payment(event: dict) -> None:
    """Paid (or partly paid): wake the invoice's sequence so it re-plans (completes if fully paid)."""
    if not event["payload"].get("invoice_id"):
        return
    for eid in await enrollments_for(event["org_id"], event["payload"]["invoice_id"]):
        await wake(eid, "payment")


@DBOS.step()
async def classify_reply(org_id: str, invoice: dict, reply: str) -> dict:
    prompt = load("invoice_reply_classifier")
    try:
        res = await complete("fast", prompt.render(invoice=invoice["number"], channel="email", text=reply), org_id=org_id,
                             prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps(_heuristic(reply)))
        return res.data if isinstance(res.data, dict) and res.data.get("label") else _heuristic(reply)
    except AllModelsFailed:
        return _heuristic(reply)


def _heuristic(reply: str) -> dict:
    import re

    from agentry.leads import is_opt_out
    t = reply.lower()
    if is_opt_out(reply):  # "STOP" on its own or clear phrases; "don't stop the service" is not an opt-out
        return {"label": "opt_out"}
    if re.search(r"\b(dispute|wrong|incorrect|not paying|disagree|issue with)\b", t):
        return {"label": "dispute", "reason": reply[:200]}
    if re.search(r"\b(already paid|paid it|have paid|transferred|utr|neft|cheque)\b", t):
        return {"label": "already_paid"}
    if re.search(r"\b(will pay|pay by|clear it by|by (monday|tuesday|wednesday|thursday|friday|\d))\b", t):
        return {"label": "promise_to_pay", "date": None}
    if re.search(r"\b(resend|send (the )?invoice|copy of the invoice)\b", t):
        return {"label": "resend_invoice"}
    return {"label": "other"}


async def _for_a_person(conn, org_id: str, invoice: dict, conversation_id: str | None, reply: str, title: str) -> None:
    """A reply only a person can handle (a question, a copy of the invoice, a part payment): a card in Needs you for
    finance, with the customer's words."""
    await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
        values (:o, 'escalation', 'invoice_follow_up', :c, :t, :b, cast(:p as jsonb))"""),
        {"o": org_id, "c": conversation_id, "t": title, "b": reply[:2000], "p": json.dumps({"invoice_id": invoice["id"]})})


@DBOS.step()
async def act_on_reply(org_id: str, invoice: dict, conversation_id: str | None, reply: str, result: dict, grace_days: int,
                       channel: str = "email") -> str:
    label = result.get("label", "other")
    async with tenant_session(org_id) as conn:
        enrollments = await _active_enrollments(conn, invoice["id"])
        note = f"{datetime.now(UTC):%d %b}: customer replied ({label})"
        if label == "promise_to_pay":
            try:
                until = datetime.fromisoformat(result["date"]).replace(tzinfo=UTC) + timedelta(days=grace_days) if result.get("date") \
                    else datetime.now(UTC) + timedelta(days=3)
            except (TypeError, ValueError):
                until = datetime.now(UTC) + timedelta(days=3)
            await conn.execute(text("""update app.sequence_enrollments set status = 'paused', paused_until = :u, updated_at = now()
                where id = any(cast(:ids as uuid[]))"""), {"u": until, "ids": enrollments})
            note += f", promised to pay by {result.get('date') or 'soon'}; reminders paused until {until:%d %b}"
        elif label == "dispute":
            await conn.execute(text("update app.invoices set status = 'disputed', updated_at = now() where id = :i"), {"i": invoice["id"]})
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
                values (:o, 'dispute', 'invoice_follow_up', :c, :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "c": conversation_id, "t": f"Invoice {invoice['number']} disputed", "b": result.get("reason") or reply[:500],
                 "p": json.dumps({"invoice_id": invoice["id"]})})
            from agentry.invoices import withdraw_reminder_cards
            await withdraw_reminder_cards(conn, invoice["id"], "disputed")
            note += "; reminders stopped for a person to resolve"
        elif label == "already_paid":
            await conn.execute(text("""update app.sequence_enrollments set status = 'paused', paused_until = now() + interval '3 days'
                where id = any(cast(:ids as uuid[]))"""), {"ids": enrollments})
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
                values (:o, 'payment_review', 'invoice_follow_up', :c, :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "c": conversation_id, "t": f"Customer says invoice {invoice['number']} is paid",
                 "b": f"Reference given: {result.get('utr') or 'none'}. Confirm the payment to close the invoice, or reply asking for proof.",
                 "p": json.dumps({"invoice_id": invoice["id"], "utr": result.get("utr")})})
            note += f", says already paid (ref {result.get('utr') or 'none'}); reminders paused 3 days for checking"
        elif label == "partial_payment":
            await conn.execute(text("""update app.sequence_enrollments set status = 'paused', paused_until = now() + interval '7 days'
                where id = any(cast(:ids as uuid[]))"""), {"ids": enrollments})
            await _for_a_person(conn, org_id, invoice, conversation_id, reply,
                                f"Paying part of invoice {invoice['number']}" + (f" ({result['amount']})" if result.get("amount") else ""))
            note += f", paying part ({result.get('amount') or 'amount not given'}); reminders paused 7 days"
        elif label == "ooo":
            await conn.execute(text("""update app.sequence_enrollments set status = 'paused', paused_until = now() + interval '5 days'
                where id = any(cast(:ids as uuid[]))"""), {"ids": enrollments})
            note += ", out of office; reminders paused 5 days"
        elif label == "opt_out" and invoice.get("contact_id"):
            await opt_out(conn, org_id, invoice["contact_id"], channel, source="reply:invoice")
            note += f"; opted out of {channel}"
        elif label == "resend_invoice":
            await _for_a_person(conn, org_id, invoice, conversation_id, reply, f"Customer asked for a copy of invoice {invoice['number']}")
            note += "; asked for a copy of the invoice"
        elif label == "other":
            await _for_a_person(conn, org_id, invoice, conversation_id, reply, f"Customer replied about invoice {invoice['number']}")
            note += "; replied with a question for the team"
        await conn.execute(text("update app.invoices set notes = concat_ws(E'\\n', notes, cast(:n as text)), updated_at = now() where id = :i"),
                           {"n": note, "i": invoice["id"]})
        await audit.record(conn, org_id=org_id, actor_type="agent", action=f"invoice.reply.{label}", target_type="invoice",
                           target_id=invoice["number"], metadata=result)
    return label


@DBOS.step()
async def invoice_for_reply(org_id: str, payload: dict) -> dict | None:
    async with tenant_session(org_id) as conn:
        row = None
        if payload.get("invoice_id"):
            row = (await conn.execute(text("select id, number, contact_id from app.invoices where id = cast(:i as uuid)"),
                                      {"i": payload["invoice_id"]})).mappings().first()
        if row is None and (num := (payload.get("entities") or {}).get("invoice")):
            row = (await conn.execute(text("select id, number, contact_id from app.invoices where number = :n"), {"n": num})).mappings().first()
        cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'invoice_follow_up'"))).scalar_one_or_none()
    return {**{k: str(v) if v is not None else None for k, v in row.items()},
            "grace": InvoiceConfig(**(cfg or {})).promise_grace_days} if row else None


@on("invoice.reply")
@DBOS.workflow()
async def handle_invoice_reply(event: dict) -> None:
    p = event["payload"]
    invoice = await invoice_for_reply(event["org_id"], p)
    if not invoice or not p.get("text"):
        return
    result = await classify_reply(event["org_id"], invoice, p["text"])
    await act_on_reply(event["org_id"], invoice, p.get("conversation_id"), p["text"], result, invoice["grace"], p.get("channel") or "email")
    for eid in await enrollments_for(event["org_id"], invoice["id"]):
        await wake(eid, "reply")


# ---------- replies that arrive without inbox triage (#2, #3) and go-live (#1) ----------

REPLY_WINDOW_DAYS = 14


async def invoice_in_conversation(conn, conversation_id: str, channel: str) -> str | None:
    """The invoice a customer is replying about: an email reminder thread is the invoice's own; a WhatsApp
    conversation is shared with everything else, so only a reminder sent there in the last 14 days counts."""
    if channel == "email":
        return (await conn.execute(text("""select metadata->>'subject_id' from app.conversations where id = cast(:c as uuid)
            and metadata->>'subject_type' = 'invoice'"""), {"c": conversation_id})).scalar_one_or_none()
    return (await conn.execute(text("""select metadata->>'subject_id' from app.messages where conversation_id = cast(:c as uuid)
        and direction = 'out' and metadata->>'subject_type' = 'invoice' and created_at > now() - make_interval(days => :d)
        order by created_at desc limit 1"""), {"c": conversation_id, "d": REPLY_WINDOW_DAYS})).scalar_one_or_none()


@DBOS.step()
async def reminder_reply_context(org_id: str, message_id: str) -> dict | None:
    """An email reply in a reminder thread, when inbox triage isn't live to route it (it emits invoice.reply itself)."""
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select m.conversation_id::text as conversation_id, m.body, m.direction,
                (select status from app.automation_instances where template_key = 'inbox_triage') as triage,
                (select status from app.automation_instances where template_key = 'invoice_follow_up') as invoices
            from app.messages m where m.id = cast(:m as uuid)"""), {"m": message_id})).mappings().first()
        if (not row or row["direction"] != "in" or row["triage"] in ("live", "approval_mode")
                or row["invoices"] not in ("live", "approval_mode")):
            return None
        invoice_id = await invoice_in_conversation(conn, row["conversation_id"], "email")
    return {"conversation_id": row["conversation_id"], "invoice_id": invoice_id, "text": row["body"]} if invoice_id else None


@on("email.received")
@DBOS.workflow()
async def reminder_reply(event: dict) -> None:
    ctx = await reminder_reply_context(event["org_id"], event["payload"]["message_id"])
    if ctx:
        await handle_invoice_reply({"org_id": event["org_id"], "payload": ctx})


@DBOS.step()
async def whatsapp_reply_context(org_id: str, conversation_id: str) -> str | None:
    async with tenant_session(org_id) as conn:
        status = (await conn.execute(text("select status from app.automation_instances where template_key = 'invoice_follow_up'"))).scalar()
        if status not in ("live", "approval_mode"):
            return None
        return await invoice_in_conversation(conn, conversation_id, "whatsapp")


@on("whatsapp.received")
@DBOS.workflow()
async def whatsapp_reminder_reply(event: dict) -> None:
    """A WhatsApp reply to a recent invoice reminder goes to the invoice agent (the WhatsApp assistant stays out)."""
    p = event["payload"]
    invoice_id = await whatsapp_reply_context(event["org_id"], p["conversation_id"])
    if invoice_id and p.get("text"):
        await handle_invoice_reply({"org_id": event["org_id"], "payload": {"conversation_id": p["conversation_id"],
                                                                             "invoice_id": invoice_id, "text": p["text"], "channel": "whatsapp"}})


@DBOS.step()
async def enroll_after_go_live(org_id: str) -> int:
    from agentry.invoices import enroll_open
    async with tenant_session(org_id) as conn:
        return await enroll_open(conn, org_id)


@on("org.went_live")
@DBOS.workflow()
async def enroll_on_go_live(event: dict) -> None:
    """Invoices imported during onboarding start their reminders when the client goes live."""
    if "invoice_follow_up" in (event["payload"].get("automations") or []):
        await enroll_after_go_live(event["org_id"])


def money(v) -> Decimal:
    return Decimal(str(v))
