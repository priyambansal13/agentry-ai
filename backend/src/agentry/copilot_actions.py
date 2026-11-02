"""Business copilot (ROADMAP-V3 C1, v2 10.4): "remind Rohan about E-1 and move his callback to Monday" becomes a plan of
steps that a person confirms with one tap, in the portal (Ask) or on the Telegram team bot (text or a voice note).

    propose   the model reads with the copilot's read-only tools and *proposes* actions with these tools; each proposal
              is checked at once (the person's permission, the agent switched on, the customer / invoice / appointment
              found and unambiguous) and either staged with a plain summary or returned as an error the model can fix
              or ask about. Nothing changes while planning
    confirm   the plan is saved; "Do it" runs each step again with the same checks; every step is in the audit log
    rules     messages to customers aren't sent at night (9 pm to 8 am, the governance rule): the step says so and can be
              run in the morning; amounts and prices come from the books, never from the model
"""
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit, governance
from agentry.db import tenant_session


class StepError(ValueError):
    pass


@dataclass
class ActionTool:
    name: str
    description: str
    params: dict
    required: list[str]
    needs: tuple[str, str]
    agent: str | None
    customer_facing: bool
    stage: Callable[[AsyncConnection, object, dict], Awaitable[dict]]   # -> {"summary", "resolved"} or raises StepError
    run: Callable[[AsyncConnection, str, object, dict], Awaitable[str]]  # -> what happened, in words


# ---------- finding things ----------

async def find_contact(conn: AsyncConnection, who: str) -> dict:
    q = (who or "").strip()
    if len(q) < 2:
        raise StepError("say which customer")
    digits = re.sub(r"\D", "", q)
    if len(digits) >= 10:
        rows = (await conn.execute(text("""select id::text, name, phone_e164, email, attributes->>'telegram_id' as telegram_id from app.contacts
            where merged_into is null and right(regexp_replace(coalesce(phone_e164, phone, ''), '\\D', '', 'g'), 10) = :d limit 3"""), {"d": digits[-10:]})).mappings().all()
    else:
        rows = (await conn.execute(text("""select id::text, name, phone_e164, email, attributes->>'telegram_id' as telegram_id from app.contacts
            where merged_into is null and (name ilike :p or email ilike :p) order by (lower(name) = lower(:q)) desc, created_at desc limit 5"""),
            {"p": f"%{q}%", "q": q})).mappings().all()
        exact = [r for r in rows if (r["name"] or "").lower() == q.lower()]
        rows = exact or rows
    if not rows:
        raise StepError(f"no customer called \"{q}\"")
    if len(rows) > 1:
        raise StepError(f"more than one customer matches \"{q}\": " + ", ".join(f"{r['name']} ({r['phone_e164'] or r['email'] or 'no contact'})" for r in rows[:4])
                        + ". Ask which one")
    return dict(rows[0])


def _who(c: dict) -> dict:
    return {"contact_id": c["id"], "contact_name": c["name"], "phone_e164": c["phone_e164"], "email": c["email"], "telegram_id": c["telegram_id"]}


async def _send(conn: AsyncConnection, org_id: str, contact: dict, body: str, subject: str) -> str:
    from agentry.outbound import reach_contact
    tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
    if governance.is_quiet(datetime.now(UTC), tz):
        raise StepError("not sent: it's between 9 pm and 8 am. Run it again in the morning")
    r = await reach_contact(conn, org_id, _who(contact), body, agent="copilot", subject=subject, email_ref=f"copilot:{contact['id']}:{datetime.now(UTC):%Y%m%d%H%M}")
    if r["status"] == "no_channel":
        raise StepError(f"{contact['name']} has no WhatsApp, Telegram or email on file")
    return f"sent to {contact['name']} on {r['channel']}" + (" (recorded: no mailbox connected)" if r["status"] == "recorded" else "")


# ---------- the actions ----------

async def s_message(conn, who, a):
    c = await find_contact(conn, a.get("customer", ""))
    body = str(a.get("message") or "").strip()
    if len(body) < 2:
        raise StepError("what should the message say?")
    return {"summary": f"Message {c['name']}: \"{body[:160]}\"", "resolved": {"contact": c, "body": body[:1500]}}


async def r_message(conn, org_id, who, res):
    return await _send(conn, org_id, res["contact"], res["body"], "A message from us")


async def s_remind(conn, who, a):
    ref = str(a.get("invoice") or "").strip()
    rows = (await conn.execute(text("""select i.id::text, i.number, i.amount, i.amount_paid, i.currency, i.due_on, i.status, k.id::text as cid
        from app.invoices i left join app.contacts k on k.id = i.contact_id
        where i.status in ('open','partially_paid') and (upper(i.number) = upper(:r) or k.name ilike :p) order by i.due_on limit 5"""),
        {"r": ref, "p": f"%{ref}%"})).mappings().all()
    if not rows:
        raise StepError(f"no open invoice matches \"{ref}\"")
    if len(rows) > 1 and not any(r["number"].upper() == ref.upper() for r in rows):
        raise StepError("several open invoices match: " + ", ".join(r["number"] for r in rows) + ". Ask which one")
    inv = next((r for r in rows if r["number"].upper() == ref.upper()), rows[0])
    if not inv["cid"]:
        raise StepError(f"invoice {inv['number']} has no customer contact")
    c = (await conn.execute(text("select id::text, name, phone_e164, email, attributes->>'telegram_id' as telegram_id from app.contacts where id = cast(:i as uuid)"),
                            {"i": inv["cid"]})).mappings().one()
    bal = float(inv["amount"]) - float(inv["amount_paid"])
    return {"summary": f"Remind {c['name']} about invoice {inv['number']} ({inv['currency']} {bal:,.2f} due {inv['due_on']:%d %b}) with a payment link",
            "resolved": {"invoice_id": inv["id"], "contact": dict(c)}}


async def r_remind(conn, org_id, who, res):
    from agentry.invoices import payment_link
    inv = (await conn.execute(text("""select i.*, k.name as contact_name, k.email, k.phone_e164 from app.invoices i left join app.contacts k on k.id = i.contact_id
        where i.id = cast(:i as uuid)"""), {"i": res["invoice_id"]})).mappings().one()
    if inv["status"] not in ("open", "partially_paid"):
        raise StepError(f"invoice {inv['number']} is {inv['status']} now")
    bal = float(inv["amount"]) - float(inv["amount_paid"])
    link = await payment_link(conn, org_id, dict(inv))
    business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
    body = (f"Hi {(inv['contact_name'] or '').split()[0] if inv['contact_name'] else 'there'}, a gentle reminder from {business}: invoice {inv['number']} for "
            f"{inv['currency'].replace('INR', '₹')}{bal:,.2f} was due on {inv['due_on']:%d %b}." + (f" You can pay here: {link}" if link else "") + "\nThank you!")
    return await _send(conn, org_id, res["contact"], body, f"Invoice {inv['number']}")


async def _booking_for(conn, customer: str) -> dict:
    c = await find_contact(conn, customer)
    rows = (await conn.execute(text("""select b.id::text, b.starts_at, b.status, s.key as service_key, s.name as service from app.bookings b
        join app.services s on s.id = b.service_id where b.contact_id = cast(:k as uuid) and b.status in ('booked','confirmed') and b.starts_at > now()
        order by b.starts_at limit 3"""), {"k": c["id"]})).mappings().all()
    if not rows:
        raise StepError(f"{c['name']} has no upcoming appointment")
    if len(rows) > 1:
        raise StepError(f"{c['name']} has {len(rows)} upcoming appointments: " + ", ".join(f"{r['service']} {r['starts_at']:%d %b %H:%M}" for r in rows) + ". Ask which")
    return {"contact": c, "booking": dict(rows[0])}


async def s_move(conn, who, a):
    from agentry.booking import availability
    found = await _booking_for(conn, a.get("customer", ""))
    try:
        new = datetime.fromisoformat(str(a.get("new_time")))
    except ValueError as e:
        raise StepError("give the new time as a date and time") from e
    tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
    if new.tzinfo is None:
        from zoneinfo import ZoneInfo
        new = new.replace(tzinfo=ZoneInfo(tz))
    slots, _tz, _svc = await availability(who.org_id, found["booking"]["service_key"], new.date(), days=1, limit=500)
    if not any(s.start == new for s in slots):
        free = [s.label(_tz) for s in slots][:4]
        raise StepError(f"{new:%a %d %b %H:%M} isn't free for {found['booking']['service']}" + (f"; free that day: {', '.join(free)}" if free else "; nothing free that day"))
    b = found["booking"]
    return {"summary": f"Move {found['contact']['name']}'s {b['service']} from {b['starts_at'].astimezone(new.tzinfo):%a %d %b %H:%M} to {new:%a %d %b %H:%M} and tell them",
            "resolved": {"contact": found["contact"], "booking_id": b["id"], "service_key": b["service_key"], "new_time": new.isoformat()}}


async def r_move(conn, org_id, who, res):
    from agentry.automations.appointment_concierge import cancel
    from agentry.booking import BookingError, book
    c = res["contact"]
    try:
        new = await book(org_id, service_key=res["service_key"], start=datetime.fromisoformat(res["new_time"]), name=c["name"] or "Customer",
                         phone=c["phone_e164"], email=c["email"], source="copilot")
    except BookingError as e:
        raise StepError(f"couldn't book the new time: {e}") from e
    await cancel(conn, org_id, res["booking_id"], "rescheduled")
    try:
        told = await _send(conn, org_id, c, f"Hi {(c['name'] or '').split()[0]}, your appointment is now {new['when']}. See you then!", "Your appointment")
    except StepError as e:
        told = f"not told: {e}"
    return f"moved to {new['when']}; {told}"


async def s_cancel(conn, who, a):
    found = await _booking_for(conn, a.get("customer", ""))
    b = found["booking"]
    return {"summary": f"Cancel {found['contact']['name']}'s {b['service']} on {b['starts_at']:%a %d %b} and tell them",
            "resolved": {"contact": found["contact"], "booking_id": b["id"], "reason": str(a.get("reason") or "cancelled by the business")[:200], "service": b["service"]}}


async def r_cancel(conn, org_id, who, res):
    from agentry.automations.appointment_concierge import cancel
    await cancel(conn, org_id, res["booking_id"], res["reason"])
    c = res["contact"]
    try:
        told = await _send(conn, org_id, c, f"Hi {(c['name'] or '').split()[0]}, your {res['service']} appointment has been cancelled. Reply here to book another time.",
                           "Your appointment")
    except StepError as e:
        told = f"not told: {e}"
    return f"cancelled; {told}"


async def s_note(conn, who, a):
    c = await find_contact(conn, a.get("customer", ""))
    note = str(a.get("note") or "").strip()
    if len(note) < 2:
        raise StepError("what's the note?")
    return {"summary": f"Add a note to {c['name']}: \"{note[:160]}\"", "resolved": {"contact_id": c["id"], "name": c["name"], "note": note[:1000]}}


async def r_note(conn, org_id, who, res):
    entry = {"at": datetime.now(UTC).isoformat(), "by": getattr(who, "user_id", None), "text": res["note"]}
    await conn.execute(text("""update app.contacts set attributes = jsonb_set(attributes, '{notes}', coalesce(attributes->'notes', '[]'::jsonb) || cast(:n as jsonb))
        where id = cast(:i as uuid)"""), {"n": json.dumps([entry]), "i": res["contact_id"]})
    return f"note added to {res['name']}"


async def s_ticket(conn, who, a):
    subject = str(a.get("subject") or "").strip()
    if len(subject) < 3:
        raise StepError("what's the ticket about?")
    c = await find_contact(conn, a["customer"]) if a.get("customer") else None
    pr = a.get("priority") if a.get("priority") in ("low", "normal", "high", "urgent") else "normal"
    return {"summary": f"Open a {pr} ticket: {subject}" + (f" for {c['name']}" if c else ""), "resolved": {"subject": subject[:200], "priority": pr,
                                                                                                  "summary": str(a.get("details") or "")[:2000]}}


async def r_ticket(conn, org_id, who, res):
    from agentry.automations.support_desk import open_ticket
    t = await open_ticket(conn, org_id, subject=res["subject"], summary=res["summary"] or None, priority=res["priority"], source="person")
    return f"ticket #{t['number']} opened"


async def s_renewed(conn, who, a):
    c = await find_contact(conn, a.get("customer", ""))
    rows = (await conn.execute(text("""select id::text, item, due_on from app.renewals where contact_id = cast(:k as uuid) and status in ('upcoming','lapsed')
        and (cast(:i as text) is null or item ilike :p) order by due_on limit 3"""), {"k": c["id"], "i": a.get("item"), "p": f"%{a.get('item') or ''}%"})).mappings().all()
    if not rows:
        raise StepError(f"no renewal due for {c['name']}")
    if len(rows) > 1:
        raise StepError(f"{c['name']} has several renewals: " + ", ".join(r["item"] for r in rows) + ". Ask which")
    return {"summary": f"Mark {c['name']}'s {rows[0]['item']} (due {rows[0]['due_on']:%d %b}) as renewed", "resolved": {"renewal_id": rows[0]["id"]}}


async def r_renewed(conn, org_id, who, res):
    from agentry.automations.renewals import mark
    await mark(conn, org_id, res["renewal_id"], "renewed", getattr(who, "user_id", None))
    return "marked renewed; the next due date is set"


def _p(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


ACTIONS: dict[str, ActionTool] = {t.name: t for t in [
    ActionTool("propose_message", "Propose sending a customer a message (WhatsApp, else Telegram, else email). Write the message in full.",
               {"customer": _p("name, phone or email"), "message": _p("the exact message")}, ["customer", "message"], ("conversation", "act"), None, True,
               s_message, r_message),
    ActionTool("propose_invoice_reminder", "Propose reminding a customer about an unpaid invoice (amount and payment link come from the books).",
               {"invoice": _p("invoice number, or the customer's name")}, ["invoice"], ("invoice", "act"), None, True, s_remind, r_remind),
    ActionTool("propose_move_appointment", "Propose moving a customer's upcoming appointment to a new time (checked against free slots).",
               {"customer": _p("name, phone or email"), "new_time": _p("ISO date-time in the business's timezone, e.g. 2026-11-09T11:00")},
               ["customer", "new_time"], ("calendar", "act"), None, True, s_move, r_move),
    ActionTool("propose_cancel_appointment", "Propose cancelling a customer's upcoming appointment and telling them.",
               {"customer": _p("name, phone or email"), "reason": _p("why, briefly")}, ["customer"], ("calendar", "act"), None, True, s_cancel, r_cancel),
    ActionTool("propose_note", "Propose adding an internal note to a customer.", {"customer": _p("name, phone or email"), "note": _p("the note")},
               ["customer", "note"], ("conversation", "act"), None, False, s_note, r_note),
    ActionTool("propose_ticket", "Propose opening a support ticket.", {"subject": _p("what it's about"), "details": _p("details"),
               "customer": _p("name, phone or email (optional)"), "priority": _p("low, normal, high or urgent")}, ["subject"], ("conversation", "act"),
               "support_desk", False, s_ticket, r_ticket),
    ActionTool("propose_mark_renewed", "Propose marking a customer's renewal (AMC, membership…) as renewed.",
               {"customer": _p("name, phone or email"), "item": _p("what renewed, if they have several")}, ["customer"], ("conversation", "act"),
               "renewals", False, s_renewed, r_renewed),
]}


async def _agents(conn) -> set[str]:
    return set((await conn.execute(text("select template_key from app.automation_instances"))).scalars())


async def actions_for(who) -> list[ActionTool]:
    async with tenant_session(who.org_id) as conn:
        on = await _agents(conn)
    return [a for a in ACTIONS.values() if who.may(*a.needs) and (a.agent is None or a.agent in on)]


def action_defs(tools: list[ActionTool]) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": {"type": "object", "properties": t.params, "required": t.required}}} for t in tools]


async def stage(who, name: str, args: dict) -> dict:
    a = ACTIONS.get(name)
    if not a or not who.may(*a.needs):
        return {"error": "you can't do that in this business"}
    async with tenant_session(who.org_id) as conn:
        if a.agent and a.agent not in await _agents(conn):
            return {"error": "that agent isn't switched on"}
        try:
            s = await a.stage(conn, who, args or {})
        except StepError as e:
            return {"error": str(e)}
    return {"tool": name, "summary": s["summary"], "resolved": s["resolved"], "customer_facing": a.customer_facing}


async def save_plan(who, question: str, steps: list[dict], user_id: str | None) -> str:
    async with tenant_session(who.org_id) as conn:
        return str((await conn.execute(text("""insert into app.copilot_plans (org_id, user_id, question, steps) values (:o, :u, :q, cast(:s as jsonb))
            returning id"""), {"o": who.org_id, "u": user_id, "q": question[:2000], "s": json.dumps(steps, default=str)})).scalar_one())


async def run_plan(who, plan_id: str, user_id: str | None, via: str = "portal") -> dict:
    async with tenant_session(who.org_id) as conn:
        p = (await conn.execute(text("select * from app.copilot_plans where id = cast(:i as uuid) for update"), {"i": plan_id})).mappings().first()
        if not p:
            raise StepError("plan not found")
        if p["status"] != "proposed":
            raise StepError(f"this plan was already {p['status']}")
        if p["user_id"] and user_id and p["user_id"] != user_id and not getattr(who, "staff", False):
            raise StepError("only the person who asked can run this plan")
        await conn.execute(text("update app.copilot_plans set status = 'running' where id = cast(:i as uuid)"), {"i": plan_id})
    results = []
    for s in p["steps"]:
        a = ACTIONS.get(s["tool"])
        async with tenant_session(who.org_id) as conn:
            try:
                if not a or not who.may(*a.needs):
                    raise StepError("not allowed any more")
                if a.agent and a.agent not in await _agents(conn):
                    raise StepError("that agent was switched off")
                async with conn.begin_nested():
                    out = await a.run(conn, who.org_id, who, s["resolved"])
                results.append({"summary": s["summary"], "ok": True, "result": out})
            except StepError as e:
                results.append({"summary": s["summary"], "ok": False, "result": str(e)})
            await audit.record(conn, org_id=who.org_id, actor_type="user", actor_user_id=user_id, action="copilot.step", target_type="copilot_plan",
                               target_id=plan_id, metadata={"tool": s["tool"], "summary": s["summary"], "ok": results[-1]["ok"], "via": via})
    async with tenant_session(who.org_id) as conn:
        await conn.execute(text("update app.copilot_plans set status = 'done', results = cast(:r as jsonb), ran_at = now() where id = cast(:i as uuid)"),
                           {"r": json.dumps(results), "i": plan_id})
    return {"id": plan_id, "results": results}


async def cancel_plan(who, plan_id: str) -> None:
    async with tenant_session(who.org_id) as conn:
        await conn.execute(text("update app.copilot_plans set status = 'cancelled' where id = cast(:i as uuid) and status = 'proposed'"), {"i": plan_id})
