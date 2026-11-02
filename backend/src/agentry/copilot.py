"""Ask your business (ROADMAP-V2 9.1 part 2, 2.6): questions in plain words, answered from the business's own data.

The model never writes SQL and never changes anything: it picks from a fixed set of read-only tools, each a query in
code that runs inside the business's tenant session (row-level security) and checks the person's permission first
(money tools need invoice:read, conversations and leads need conversation:read...). Numbers in the answer come from
those results. The same tools are what the MCP server (api/routes/mcp.py) offers Claude Desktop or ChatGPT.
"""
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import runs
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.permissions import can

MAX_ROUNDS = 4
PERIODS = ["today", "yesterday", "this_week", "last_7_days", "this_month", "last_month", "last_30_days"]


@dataclass
class Who:
    org_id: str
    role: str | None
    staff: bool = False
    user_id: str | None = None

    def may(self, resource: str, action: str = "read") -> bool:
        return self.staff or can(self.role, resource, action)


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    needs: tuple[str, str]
    run: Callable[[AsyncConnection, dict, dict], Awaitable[dict]]


def window(period: str, tz: str) -> tuple[datetime, datetime, str]:
    zone = ZoneInfo(tz or "Asia/Kolkata")
    today = datetime.now(zone).date()
    start_of = lambda d: datetime.combine(d, time.min, zone)
    match period:
        case "today":
            s, e = today, today + timedelta(days=1)
        case "yesterday":
            s, e = today - timedelta(days=1), today
        case "this_week":
            s, e = today - timedelta(days=today.weekday()), today + timedelta(days=1)
        case "last_7_days":
            s, e = today - timedelta(days=6), today + timedelta(days=1)
        case "last_month":
            first = today.replace(day=1)
            s, e = (first - timedelta(days=1)).replace(day=1), first
        case "last_30_days":
            s, e = today - timedelta(days=29), today + timedelta(days=1)
        case _:
            s, e = today.replace(day=1), today + timedelta(days=1)
    return start_of(s), start_of(e), f"{s.isoformat()} to {(e - timedelta(days=1)).isoformat()}"


def _num(v) -> float:
    return round(float(v or 0), 2)


# ---------- the tools (read-only) ----------

async def t_money(conn, a, ctx) -> dict:
    s, e, label = window(a.get("period", "this_month"), ctx["tz"])
    received = (await conn.execute(text("select coalesce(sum(amount), 0), count(*) from app.payments where received_at >= :s and received_at < :e"),
                                   {"s": s, "e": e})).one()
    open_ = (await conn.execute(text("""select coalesce(sum(amount - amount_paid), 0) as owed, count(*) as n,
            coalesce(sum(amount - amount_paid) filter (where due_on < current_date), 0) as overdue,
            count(*) filter (where due_on < current_date) as overdue_n
        from app.invoices where status in ('open','partially_paid')"""))).mappings().one()
    return {"period": label, "currency": ctx["currency"], "received": _num(received[0]), "payments": received[1],
            "outstanding": _num(open_["owed"]), "open_invoices": open_["n"], "overdue": _num(open_["overdue"]), "overdue_invoices": open_["overdue_n"]}


async def t_overdue(conn, a, ctx) -> dict:
    rows = (await conn.execute(text("""select i.number, coalesce(k.company, k.name) as customer, i.amount - i.amount_paid as balance,
            current_date - i.due_on as days_late from app.invoices i left join app.contacts k on k.id = i.contact_id
        where i.status in ('open','partially_paid') and i.due_on < current_date order by balance desc limit :l"""),
        {"l": min(int(a.get("limit", 10)), 50)})).mappings().all()
    return {"currency": ctx["currency"], "invoices": [{**dict(r), "balance": _num(r["balance"])} for r in rows]}


async def t_leads(conn, a, ctx) -> dict:
    s, e, label = window(a.get("period", "last_7_days"), ctx["tz"])
    by_source = dict((await conn.execute(text("select source, count(*) from app.leads where created_at >= :s and created_at < :e group by 1"),
                                         {"s": s, "e": e})).all())
    by_stage = dict((await conn.execute(text("select stage, count(*) from app.leads group by 1"))).all())
    recent = (await conn.execute(text("""select k.name, l.source, l.stage, l.created_at::date as day from app.leads l join app.contacts k on k.id = l.contact_id
        where l.created_at >= :s and l.created_at < :e order by l.created_at desc limit 10"""), {"s": s, "e": e})).mappings().all()
    return {"period": label, "new_leads": sum(by_source.values()), "new_by_source": by_source, "all_leads_by_stage": by_stage,
            "recent": [dict(r) for r in recent]}


async def t_bookings(conn, a, ctx) -> dict:
    zone = ZoneInfo(ctx["tz"] or "Asia/Kolkata")
    day = date.fromisoformat(a["from"]) if a.get("from") else datetime.now(zone).date()
    days = min(int(a.get("days", 7)), 31)
    s = datetime.combine(day, time.min, zone)
    rows = (await conn.execute(text("""select b.starts_at, b.status, s.name as service, k.name as customer from app.bookings b
        join app.services s on s.id = b.service_id left join app.contacts k on k.id = b.contact_id
        where b.starts_at >= :s and b.starts_at < :e order by b.starts_at limit 60"""), {"s": s, "e": s + timedelta(days=days)})).mappings().all()
    items = [{"when": r["starts_at"].astimezone(zone).strftime("%a %d %b %H:%M"), "status": r["status"], "service": r["service"],
              "customer": r["customer"]} for r in rows]
    counts: dict[str, int] = {}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    return {"from": day.isoformat(), "days": days, "count": len(items), "by_status": counts, "appointments": items}


async def t_needs_you(conn, a, ctx) -> dict:
    rows = (await conn.execute(text("""select kind, automation_key, count(*) as n, min(created_at) as oldest from app.approvals
        where status = 'pending' and (snoozed_until is null or snoozed_until < now()) group by 1, 2 order by n desc"""))).mappings().all()
    return {"waiting": sum(r["n"] for r in rows), "by_kind": [{"kind": r["kind"], "agent": r["automation_key"], "count": r["n"],
                                                               "oldest": r["oldest"].date().isoformat()} for r in rows]}


async def t_conversations(conn, a, ctx) -> dict:
    s, e, label = window(a.get("period", "last_7_days"), ctx["tz"])
    by_channel = dict((await conn.execute(text("""select channel, count(*) from app.conversations where created_at >= :s and created_at < :e
        group by 1"""), {"s": s, "e": e})).all())
    by_cat = dict((await conn.execute(text("""select coalesce(metadata->>'category', 'uncategorised'), count(*) from app.conversations
        where created_at >= :s and created_at < :e and channel = 'email' group by 1"""), {"s": s, "e": e})).all())
    handed = (await conn.execute(text("select count(*) from app.conversations where status = 'handed_off'"))).scalar_one()
    return {"period": label, "new_conversations": sum(by_channel.values()), "by_channel": by_channel, "emails_by_category": by_cat,
            "with_a_person_now": handed}


async def t_expenses(conn, a, ctx) -> dict:
    month = a.get("month") or datetime.now(UTC).date().isoformat()[:7]
    rows = (await conn.execute(text("""select fields->'category'->>'value' as category, count(*) as n, sum((fields->'total'->>'value')::numeric) as total
        from app.documents where status = 'ready' and left(fields->'date'->>'value', 7) = :m group by 1 order by 3 desc"""), {"m": month})).mappings().all()
    waiting = (await conn.execute(text("select count(*) from app.documents where status = 'needs_review'"))).scalar_one()
    return {"month": month, "currency": ctx["currency"], "total": _num(sum(r["total"] or 0 for r in rows)),
            "by_category": [{"category": r["category"], "documents": r["n"], "total": _num(r["total"])} for r in rows], "to_check": waiting}


async def t_reviews(conn, a, ctx) -> dict:
    s, e, label = window(a.get("period", "last_30_days"), ctx["tz"])
    r = (await conn.execute(text("""select count(*) as n, round(avg(rating)::numeric, 2) as avg, count(*) filter (where rating <= 2) as low,
            count(*) filter (where reply_status = 'posted') as replied from app.reviews where reviewed_at >= :s and reviewed_at < :e"""),
        {"s": s, "e": e})).mappings().one()
    themes = dict((await conn.execute(text("""select t, count(*) from app.reviews, unnest(topics) t where reviewed_at >= :s and reviewed_at < :e
        group by 1 order by 2 desc limit 5"""), {"s": s, "e": e})).all())
    return {"period": label, "reviews": r["n"], "average": float(r["avg"]) if r["avg"] is not None else None, "low_ratings": r["low"],
            "replied": r["replied"], "topics": themes}


async def t_customer(conn, a, ctx) -> dict:
    q = (a.get("name") or "").strip()
    if len(q) < 2:
        return {"error": "give at least 2 letters of a name, company, phone or email"}
    money = ("(select count(*) from app.invoices i where i.contact_id = k.id and i.status in ('open','partially_paid')) as open_invoices,"
             if ctx.get("money") else "")
    rows = (await conn.execute(text(f"""select k.id, k.name, k.company, k.email, k.phone_e164 as phone,
            (select max(last_message_at) from app.conversations c where c.contact_id = k.id) as last_message, {money}
            (select max(starts_at) from app.bookings b where b.contact_id = k.id) as last_booking
        from app.contacts k where k.merged_into is null and (k.name ilike :q or k.company ilike :q or k.email ilike :q or k.phone_e164 ilike :q)
        order by k.created_at desc limit 5"""), {"q": f"%{q}%"})).mappings().all()
    return {"matches": [{k: (str(v) if isinstance(v, datetime) else v) for k, v in dict(r).items() if k != "id"} for r in rows]}


def _p(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


PERIOD = _p("time period", enum=PERIODS)
TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("money_summary", "Payments received in a period, money still owed, and what's overdue.", {"period": PERIOD}, ("invoice", "read"), t_money),
    Tool("overdue_invoices", "The overdue invoices, biggest first: number, customer, balance, days late.",
         {"limit": {"type": "integer", "description": "how many (default 10)"}}, ("invoice", "read"), t_overdue),
    Tool("leads_summary", "New leads in a period by source, all leads by stage, and the most recent ones.", {"period": PERIOD},
         ("conversation", "read"), t_leads),
    Tool("appointments", "Appointments from a day for some days, with their status (booked, confirmed, showed, no_show, cancelled).",
         {"from": _p("YYYY-MM-DD, default today"), "days": {"type": "integer", "description": "how many days (default 7)"}}, ("calendar", "read"), t_bookings),
    Tool("needs_you", "Cards waiting for a person in Needs you, by kind and agent, with the oldest date.", {}, ("dashboard", "read"), t_needs_you),
    Tool("conversations_summary", "New conversations in a period by channel, emails by category, and how many a person is handling.",
         {"period": PERIOD}, ("conversation", "read"), t_conversations),
    Tool("expenses", "Filed expenses (receipts and bills) for a month by category, and how many wait to be checked.",
         {"month": _p("YYYY-MM, default this month")}, ("invoice", "read"), t_expenses),
    Tool("reviews_summary", "Customer reviews in a period: count, average rating, low ratings, replies, topics.", {"period": PERIOD},
         ("conversation", "read"), t_reviews),
    Tool("find_customer", "Look up a customer by name, company, phone or email: contact details, last message, open invoices, last appointment.",
         {"name": _p("part of a name, company, phone or email")}, ("conversation", "read"), t_customer),
]}


def tools_for(who: Who) -> list[Tool]:
    return [t for t in TOOLS.values() if who.may(*t.needs)]


def tool_defs(tools: list[Tool]) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": {"type": "object", "properties": t.params, "required": []}}} for t in tools]


async def _context(conn) -> dict:
    row = (await conn.execute(text("select timezone, currency, profile from app.org_settings"))).mappings().first() or {}
    return {"tz": row.get("timezone") or "Asia/Kolkata", "currency": row.get("currency") or "INR"}


async def call_tool(who: Who, name: str, args: dict) -> dict:
    """Run one tool for this person (permission checked here, not only in the list)."""
    t = TOOLS.get(name)
    if not t:
        return {"error": f"unknown tool {name}"}
    if not who.may(*t.needs):
        return {"error": "you don't have access to this information"}
    async with tenant_session(who.org_id) as conn:
        try:
            return await t.run(conn, args or {}, {**await _context(conn), "money": who.may("invoice", "read")})
        except (ValueError, KeyError) as e:
            return {"error": f"couldn't read that: {e}"}


# ---------- answering ----------

SYSTEM = """You answer questions from the owner or team of {business} about their own business, using only the tools.
- Call the tools you need, then answer in a few short sentences or a short list. Today is {today} ({tz}).
- Every number you give must come from a tool result. If the tools don't cover the question, say so and suggest what they can ask.
- Amounts are in {currency}; write Indian amounts like ₹1,25,000.
- {act}
- {limits}"""
READ_ONLY = "You can only read: if they ask you to send, change or delete something, say where in Agentry to do it."
CAN_ACT = ("When they ask you to do something, propose it with the propose_* tools: look up what you need first, then propose each step with "
           "exact details (write customer messages in full, warm and short). Nothing happens until the person taps Do it, so never say it's done: "
           "say in one line what the plan will do. If a proposal comes back with an error, fix it or ask them (for example which customer). "
           "Things the tools can't do: say where in Agentry to do them.")

ROUTES = [(r"overdue|owe|late|unpaid|outstanding|money|paid|payment|revenue|collect", "money_summary"),
          (r"lead|enquir|prospect", "leads_summary"), (r"appointment|booking|calendar|no.?show|tomorrow|schedule", "appointments"),
          (r"needs you|waiting|card|approve", "needs_you"), (r"email|conversation|message|chat|whatsapp", "conversations_summary"),
          (r"expense|spend|receipt|bill|budget", "expenses"), (r"review|rating|star", "reviews_summary")]


def _route(question: str) -> str | None:
    return next((tool for rx, tool in ROUTES if re.search(rx, question, re.IGNORECASE)), None)


def _plain(name: str, result: dict) -> str:
    """The mock-mode answer: the tool's result in plain words (no model)."""
    return f"Here's what I found ({name.replace('_', ' ')}): " + json.dumps(result, default=str)[:900]


async def answer(who: Who, question: str, history: list[dict] | None = None, *, act: bool = True, via: str = "portal") -> dict:
    """{"answer", "tools": [names used], "model", "plan"?}. With act, the model may also propose actions (copilot_actions):
    they're staged, never run, and come back as a plan the person confirms."""
    from agentry import copilot_actions as ca
    tools = tools_for(who)
    actions = await ca.actions_for(who) if act else []
    staged: list[dict] = []
    async with tenant_session(who.org_id) as conn:
        ctx = await _context(conn)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": who.org_id})).scalar_one_or_none() or "the business"
    used: list[str] = []
    hidden = [area for area, perm in (("money, invoices and expenses", ("invoice", "read")), ("leads, conversations and reviews", ("conversation", "read")),
                                      ("appointments", ("calendar", "read"))) if not who.may(*perm)]
    limits = (f"This person's role doesn't include {' or '.join(hidden)}: if they ask, say it's outside their access in Agentry "
              "and don't try to work it out from other tools.") if hidden else "They can see everything the tools cover."
    msgs = [{"role": "system", "content": SYSTEM.format(business=business, today=datetime.now(ZoneInfo(ctx["tz"])).date().isoformat(), tz=ctx["tz"],
                                                         currency=ctx["currency"], limits=limits, act=CAN_ACT if actions else READ_ONLY)},
            *[{"role": m["role"], "content": str(m["content"])[:2000]} for m in (history or [])[-6:] if m.get("role") in ("user", "assistant")],
            {"role": "user", "content": question[:2000]}]
    async with runs.run(who.org_id, "copilot", "question") as r:
        for _round in range(MAX_ROUNDS):
            try:
                defs = (tool_defs(tools) if tools else []) + ca.action_defs(actions)
                res = await complete("writer", msgs, org_id=who.org_id, prompt_key="copilot", prompt_version="v2" if actions else "v1",
                                     tools=defs or None, mock_response="")
            except AllModelsFailed:
                return {"answer": "The AI is unavailable right now. Please try again in a minute.", "tools": used, "model": None}
            if res.mock:  # no model: route by keywords to one tool and show its result
                name = _route(question)
                if not name or name not in {t.name for t in tools}:
                    return {"answer": "I can answer questions about money, leads, appointments, conversations, expenses and reviews.", "tools": [],
                            "model": res.model}
                result = await call_tool(who, name, {})
                return {"answer": _plain(name, result), "tools": [name], "model": res.model}
            if not res.tool_calls:
                r.step("answered", tools=used, staged=len(staged))
                out = {"answer": (res.text or "").strip() or ("Here's the plan." if staged else "I couldn't find an answer to that."), "tools": used, "model": res.model}
                if staged:
                    out["plan"] = {"id": await ca.save_plan(who, question, staged, who.user_id), "steps": [s["summary"] for s in staged]}
                return out
            msgs.append({"role": "assistant", "content": res.text or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in res.tool_calls]})
            for c in res.tool_calls:
                used.append(c["name"])
                if c["name"] in ca.ACTIONS:  # a proposal: checked and staged, never run here
                    out = await ca.stage(who, c["name"], c["arguments"] or {})
                    if "error" not in out:
                        staged.append(out)
                        out = {"staged": True, "summary": out["summary"], "note": "will run only after the person taps Do it"}
                    r.step("proposed", tool=c["name"], ok="error" not in out)
                    msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)[:4000]})
                    continue
                out = await call_tool(who, c["name"], c["arguments"] or {})
                r.step("tool", tool=c["name"])
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)[:12000]})
        return {"answer": "That needed more steps than I can take; try a narrower question.", "tools": used, "model": None}
