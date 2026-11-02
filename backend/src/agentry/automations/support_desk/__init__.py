"""Support desk (ROADMAP-V3 A2): customer issues become tickets with an SLA; "where's my order?" is answered.

    tickets   the chat agent (website, WhatsApp, Telegram) opens one with the open_ticket tool when a customer has a
              problem it can't fix in the chat (a complaint, a refund, a damaged item, a technical issue); every
              handoff to a person becomes one too; staff can open them by hand. Each has a category, priority, SLA due
              time (settings: hours per priority), assignee and status
    orders    an order sheet (CSV / Excel: order number, customer, phone, email, status, items, amount, ETA, tracking
              link) uploaded or replaced any time; the order_status tool finds the customer's order by its number, or by
              the phone / email of the person writing, and answers only with what the sheet says
    SLA       every 15 minutes: an open ticket past its due time with no reply from the team -> breached, an urgent card
              and the ticket.sla_breached event (notification rules)
    CSAT      when a ticket is resolved the customer is asked to rate it 1-5 (WhatsApp / email); a reply within 3 days is
              stored on the ticket
"""
import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit
from agentry.automations import AutomationTemplate, register
from agentry.db import system_session, tenant_session
from agentry.events import emit

CATEGORIES = ["order", "delivery", "refund", "product", "complaint", "billing", "technical", "other"]
PRIORITIES = ["low", "normal", "high", "urgent"]


class SupportConfig(BaseModel):
    sla_hours: dict[str, float] = Field(default_factory=lambda: {"urgent": 2, "high": 8, "normal": 24, "low": 72},
                                        title="Reply within (hours) by priority", json_schema_extra={"editable_by": "client"})
    order_status_replies: bool = Field(True, title="Answer \"where's my order?\" from the order sheet", json_schema_extra={"editable_by": "client"})
    ask_rating: bool = Field(True, title="Ask customers to rate the help when a ticket is resolved", json_schema_extra={"editable_by": "client"})
    tickets_from_handoffs: bool = Field(True, title="Every conversation handed to a person becomes a ticket", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="support_desk", name="Support desk",
    description="Customer issues become tickets with SLAs and owners; order status answered from your order sheet; ratings after.",
    config_model=SupportConfig, metrics=("tickets_resolved",),
))


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'support_desk'"))).first()
    return (row.status, SupportConfig(**(row.config or {})).model_dump()) if row else (None, SupportConfig().model_dump())


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")[-10:]


# ---------- tickets ----------

async def open_ticket(conn: AsyncConnection, org_id: str, *, subject: str, summary: str | None = None, category: str = "other",
                      priority: str = "normal", conversation_id: str | None = None, order_ref: str | None = None, source: str = "agent",
                      assignee: str | None = None) -> dict:
    """A new ticket, or the open one this conversation already has (updated). Returns {"id", "number", "new"}."""
    _status, cfg = await settings_of(conn)
    category = category if category in CATEGORIES else "other"
    priority = priority if priority in PRIORITIES else "normal"
    if conversation_id:
        existing = (await conn.execute(text("""select id::text, number from app.tickets where conversation_id = cast(:c as uuid)
            and status in ('open','waiting_customer') order by created_at desc limit 1"""), {"c": conversation_id})).first()
        if existing:
            await conn.execute(text("""update app.tickets set summary = coalesce(:s, summary), order_ref = coalesce(:r, order_ref),
                priority = case when array_position(array['low','normal','high','urgent'], :p) > array_position(array['low','normal','high','urgent'], priority)
                  then :p else priority end, updated_at = now() where id = cast(:i as uuid)"""),
                {"s": summary, "r": order_ref, "p": priority, "i": existing.id})
            return {"id": existing.id, "number": existing.number, "new": False}
    conv = (await conn.execute(text("select contact_id::text, channel from app.conversations where id = cast(:c as uuid)"),
                               {"c": conversation_id})).first() if conversation_id else None
    due = datetime.now(UTC) + timedelta(hours=float(cfg["sla_hours"].get(priority, 24)))
    await conn.execute(text("select pg_advisory_xact_lock(hashtext(:o || '/tickets'))"), {"o": org_id})
    number = (await conn.execute(text("select coalesce(max(number), 1000) + 1 from app.tickets"))).scalar_one()
    tid = (await conn.execute(text("""insert into app.tickets (org_id, number, conversation_id, contact_id, channel, subject, summary, category, priority,
        order_ref, sla_due_at, source, assignee) values (:o, :n, cast(:c as uuid), cast(:k as uuid), :ch, :s, :sm, :cat, :p, :r, :d, :src, :a)
        returning id::text"""), {"o": org_id, "n": number, "c": conversation_id, "k": conv.contact_id if conv else None, "ch": conv.channel if conv else None,
                                 "s": subject[:200], "sm": summary, "cat": category, "p": priority, "r": order_ref, "d": due, "src": source,
                                 "a": assignee})).scalar_one()
    await emit(conn, org_id, "ticket.opened", {"ticket_id": tid, "number": number, "priority": priority, "category": category})
    return {"id": tid, "number": number, "new": True}


async def update_ticket(conn: AsyncConnection, org_id: str, tid: str, changes: dict, *, user_id: str | None, actor_type: str = "user") -> dict:
    t = (await conn.execute(text("select * from app.tickets where id = cast(:i as uuid) for update"), {"i": tid})).mappings().first()
    if not t:
        raise ValueError("ticket not found")
    new = {k: v for k, v in changes.items() if k in ("status", "priority", "assignee", "category") and v is not None}
    if "status" in new and new["status"] not in ("open", "waiting_customer", "resolved", "closed"):
        raise ValueError("unknown status")
    if "priority" in new and new["priority"] not in PRIORITIES:
        raise ValueError("unknown priority")
    sets = [f"{k} = :{k}" for k in new]
    if new.get("status") in ("resolved", "closed") and t["status"] not in ("resolved", "closed"):
        sets.append("resolved_at = now()")
    if new.get("status") == "open" and t["status"] in ("resolved", "closed"):
        sets.append("resolved_at = null")
    if changes.get("note"):
        note = {"by": user_id, "at": datetime.now(UTC).isoformat(), "text": str(changes["note"])[:2000]}
        sets.append("notes = notes || cast(:note as jsonb)")
        new["note"] = json.dumps([note])
    if not sets:
        return dict(t)
    row = (await conn.execute(text(f"update app.tickets set {', '.join(sets)}, updated_at = now() where id = cast(:id as uuid) returning *"),
                              new | {"id": tid})).mappings().one()
    if new.get("status") and new["status"] != t["status"]:
        await audit.record(conn, org_id=org_id, actor_type=actor_type, actor_user_id=user_id, action="ticket.status", target_type="ticket",
                           target_id=tid, metadata={"from": t["status"], "to": new["status"]})
        if new["status"] == "resolved":
            await emit(conn, org_id, "ticket.resolved", {"ticket_id": tid, "number": t["number"]})
    return dict(row)


async def first_response(conn: AsyncConnection, conversation_id: str) -> None:
    """A person from the business replied in this conversation: the open ticket's first response time is set."""
    await conn.execute(text("""update app.tickets set first_response_at = coalesce(first_response_at, now()), updated_at = now()
        where conversation_id = cast(:c as uuid) and status in ('open','waiting_customer')"""), {"c": conversation_id})


# ---------- orders ----------

COLS = {"order_ref": ("order id", "order no", "order number", "order", "order #", "invoice no"), "customer": ("customer", "name", "customer name"),
        "phone": ("phone", "mobile", "whatsapp", "contact"), "email": ("email", "e-mail"), "status": ("status", "order status", "delivery status"),
        "items": ("items", "products", "product"), "amount": ("amount", "total", "order value"), "eta": ("eta", "expected delivery", "delivery date"),
        "tracking_url": ("tracking", "tracking url", "tracking link", "awb link")}


async def import_orders(conn: AsyncConnection, org_id: str, rows: list[list[str]]) -> dict:
    from agentry.automations.ca.core import find_col, money, parse_date
    if len(rows) < 2:
        raise ValueError("the sheet needs a header row and at least one order")
    head = rows[0]
    col = {k: find_col(head, *names) for k, names in COLS.items()}
    if col["order_ref"] is None or col["status"] is None:
        raise ValueError("the sheet needs an order number column and a status column")
    n = 0
    for r in rows[1:]:
        g = {k: (str(r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        if not g["order_ref"] or not g["status"]:
            continue
        await conn.execute(text("""insert into app.orders (org_id, order_ref, customer, phone, email, status, items, amount, eta, tracking_url)
            values (:o, :r, :c, :p, :e, :s, :i, :a, :eta, :t) on conflict (org_id, order_ref) do update set customer = excluded.customer,
            phone = excluded.phone, email = excluded.email, status = excluded.status, items = excluded.items, amount = excluded.amount,
            eta = excluded.eta, tracking_url = excluded.tracking_url, updated_at = now()"""),
            {"o": org_id, "r": g["order_ref"].upper(), "c": g["customer"] or None, "p": g["phone"] or None, "e": g["email"].lower() or None,
             "s": g["status"], "i": g["items"] or None, "a": money(g["amount"]), "eta": parse_date(g["eta"]), "t": g["tracking_url"] or None})
        n += 1
    return {"imported": n}


def table_rows(data: bytes, filename: str | None) -> list[list[str]]:
    if (filename or "").lower().endswith(".xlsx"):
        from agentry.automations.ca.core import xlsx_rows
        return xlsx_rows(data)
    return [r for r in csv.reader(io.StringIO(data.decode("utf-8-sig", errors="ignore"))) if any(c.strip() for c in r)]


async def order_status(org_id: str, conversation_id: str, order_ref: str | None) -> dict:
    """For the chat agent: the customer's order(s), only from the sheet, only theirs (matched by order number + their
    phone / email when known, or by their phone / email)."""
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if not status or not cfg["order_status_replies"]:
            return {"error": "order status isn't available here: offer to pass the question to the team"}
        who = (await conn.execute(text("""select k.phone_e164, k.email_norm from app.conversations c left join app.contacts k on k.id = c.contact_id
            where c.id = cast(:c as uuid)"""), {"c": conversation_id})).first()
        phone, email = _digits(who.phone_e164 if who else None), (who.email_norm if who else None)
        if order_ref:
            rows = (await conn.execute(text("select * from app.orders where upper(order_ref) = upper(:r)"), {"r": order_ref.strip().lstrip("#")})).mappings().all()
            # only the writer's own order: its phone or email must match theirs (an order with neither can't be checked: not shown)
            rows = [r for r in rows if (phone and _digits(r["phone"]) == phone) or (email and (r["email"] or "").lower() == email)]
        elif phone or email:
            rows = (await conn.execute(text("""select * from app.orders where (:p <> '' and right(regexp_replace(coalesce(phone, ''), '\\D', '', 'g'), 10) = :p)
                or (cast(:e as text) is not null and lower(email) = :e) order by updated_at desc limit 3"""), {"p": phone, "e": email})).mappings().all()
        else:
            return {"error": "ask the customer for their order number"}
    if not rows:
        return {"found": False, "note": "no order matches: ask for the order number, or offer to open a ticket"}
    return {"found": True, "orders": [{"order": r["order_ref"], "status": r["status"], "items": r["items"], "eta": str(r["eta"]) if r["eta"] else None,
                                       "tracking": r["tracking_url"]} for r in rows]}


# ---------- SLA and ratings ----------

async def check_sla(org_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text("""select id::text, number, subject, priority, conversation_id::text from app.tickets
            where status = 'open' and first_response_at is null and breached_at is null and sla_due_at < :n"""), {"n": now})).mappings().all()
        for t in rows:
            await conn.execute(text("update app.tickets set breached_at = :n where id = cast(:i as uuid)"), {"n": now, "i": t["id"]})
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
                values (:o, 'escalation', 'support_desk', cast(:c as uuid), :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "c": t["conversation_id"], "t": f"Ticket #{t['number']} is past its reply time: {t['subject']}"[:200],
                 "b": f"{t['priority'].title()} priority and nobody has replied yet.", "p": json.dumps({"ticket_id": t["id"], "urgent": True})})
            await emit(conn, org_id, "ticket.sla_breached", {"ticket_id": t["id"], "number": t["number"], "priority": t["priority"]})
    return len(rows)


async def ask_ratings(org_id: str) -> int:
    from agentry.outbound import reach_contact
    sent = 0
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status != "live" or not cfg["ask_rating"]:
            return 0
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        rows = (await conn.execute(text("""select t.id::text, t.number, t.subject, k.id::text as contact_id, k.name, k.phone_e164, k.email,
            k.attributes->>'telegram_id' as telegram_id from app.tickets t join app.contacts k on k.id = t.contact_id
            where t.status = 'resolved' and t.csat_asked_at is null and t.resolved_at > now() - interval '2 days'"""))).mappings().all()
        for t in rows:
            body = (f"Hi{(' ' + t['name'].split()[0]) if t['name'] else ''}, we've marked your request #{t['number']} ({t['subject']}) as resolved. "
                    f"How did we do? Reply with a number from 1 (poor) to 5 (great).\n{business}")
            r = await reach_contact(conn, org_id, {"contact_id": t["contact_id"], "contact_name": t["name"], "phone_e164": t["phone_e164"], "email": t["email"],
                                                   "telegram_id": t["telegram_id"]}, body, agent="support_desk", subject=f"How did we do with #{t['number']}?",
                                    email_ref=f"ticket-csat:{t['id']}")
            await conn.execute(text("update app.tickets set csat_asked_at = now() where id = cast(:i as uuid)"), {"i": t["id"]})
            sent += r["status"] == "sent"
    return sent


RATING = re.compile(r"^\s*([1-5])\s*(/\s*5|stars?|⭐+)?\s*[.!]?\s*$", re.IGNORECASE)


async def take_rating(org_id: str, conversation_id: str, body: str) -> bool:
    """A 1-5 reply from a customer who was asked to rate a resolved ticket in the last 3 days. True = stored."""
    m = RATING.match(body or "")
    if not m:
        return False
    async with tenant_session(org_id) as conn:
        contact = (await conn.execute(text("select contact_id from app.conversations where id = cast(:c as uuid)"), {"c": conversation_id})).scalar_one_or_none()
        if not contact:
            return False
        t = (await conn.execute(text("""select id::text from app.tickets where contact_id = :k and csat is null and csat_asked_at > now() - interval '3 days'
            order by csat_asked_at desc limit 1"""), {"k": contact})).scalar_one_or_none()
        if not t:
            return False
        await conn.execute(text("update app.tickets set csat = :r where id = cast(:i as uuid)"), {"r": int(m.group(1)), "i": t})
        await emit(conn, org_id, "ticket.rated", {"ticket_id": t, "rating": int(m.group(1))})
    return True


async def support_jobs(now: datetime | None = None) -> dict:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'support_desk'
            and status in ('live','approval_mode')"""))).scalars())
    out = {"breached": 0, "ratings": 0}
    for o in orgs:
        out["breached"] += await check_sla(o, now)
        out["ratings"] += await ask_ratings(o)
    return out


@DBOS.step()
async def support_jobs_step() -> dict:
    return await support_jobs()


@DBOS.workflow()
async def support_schedule(scheduled_time: datetime, context) -> None:
    await support_jobs_step()
