"""Business Pulse (ROADMAP-V2 9.1): a morning brief and a Monday week-in-review for the owner.

The numbers and the order of importance come from code (never a model): what needs doing first (cards waiting,
callbacks, overdue money), then today, then good news. Each item says what to do and links to it. The `writer` model
only writes a one-line friendly opener from those numbers, and the opener is dropped if it mentions a number the brief
doesn't have. Delivered through the Notification Center (events pulse.daily / pulse.weekly), shown on Home and in the
Telegram team bot.
"""
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.features import enabled_automations
from agentry.llm.gateway import AllModelsFailed, complete

DEFAULT_HOUR = 8
BOOKING_AGENTS = {"website_chat", "whatsapp_assistant", "telegram_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"}


def _money(v: float, currency: str = "INR") -> str:
    if currency != "INR":
        return f"{currency} {v:,.0f}"
    s = str(round(v))  # Indian grouping: 2,50,000
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail if tail else head[-2:]
        head = head[:-2]
    return "₹" + (f"{head},{tail}" if head else tail)


async def _scalar(conn: AsyncConnection, sql: str, **p: object):
    return (await conn.execute(text(sql), p)).scalar_one()


async def gather(conn: AsyncConnection, start: datetime, end: datetime, today: tuple[datetime, datetime]) -> dict:
    """The numbers for one business between start and end (UTC), plus what's on today."""
    autos = set(await enabled_automations(conn))
    pages_leads = bool(autos & (BOOKING_AGENTS | {"inbox_triage"}))
    f: dict = {"automations": sorted(autos)}
    cur = (await conn.execute(text("select coalesce((select currency from app.pricing_plans limit 1), (select currency from app.org_settings))"))).scalar_one()
    f["currency"] = cur or "INR"
    f["cards"] = dict((await conn.execute(text("""select 'pending', count(*) from app.approvals where status = 'pending'
        and (snoozed_until is null or snoozed_until <= now()) union all
        select 'waiting', count(*) from app.approvals where status = 'pending' and created_at < now() - interval '4 hours'
        and (snoozed_until is null or snoozed_until <= now()) union all
        select 'callbacks', count(*) from app.approvals where status = 'pending' and kind = 'callback'"""))).all())
    if "invoice_follow_up" in autos:
        f["money_in"] = float(await _scalar(conn, "select coalesce(sum(amount), 0) from app.payments where received_at >= :a and received_at < :b", a=start, b=end))
        f["payments"] = await _scalar(conn, "select count(*) from app.payments where received_at >= :a and received_at < :b", a=start, b=end)
        od = (await conn.execute(text("""select coalesce(sum(i.amount - i.amount_paid), 0) as total, count(*) as n from app.invoices i
            where i.status in ('open','partially_paid') and i.due_on < current_date"""))).mappings().one()
        f["overdue"], f["overdue_count"] = float(od["total"]), od["n"]
        big = (await conn.execute(text("""select i.number, coalesce(k.company, k.name) as who, i.amount - i.amount_paid as balance, current_date - i.due_on as days
            from app.invoices i left join app.contacts k on k.id = i.contact_id where i.status in ('open','partially_paid') and i.due_on < current_date
            order by i.amount - i.amount_paid desc limit 1"""))).mappings().first()
        f["biggest_overdue"] = dict(big) | {"balance": float(big["balance"])} if big else None
    if pages_leads:
        f["leads"] = await _scalar(conn, "select count(*) from app.leads where created_at >= :a and created_at < :b", a=start, b=end)
        f["leads_untouched"] = await _scalar(conn, """select count(*) from app.leads where stage = 'new' and created_at < now() - interval '2 hours'
            and created_at > now() - interval '7 days'""")
    if autos & BOOKING_AGENTS:
        f["bookings_made"] = await _scalar(conn, "select count(*) from app.bookings where created_at >= :a and created_at < :b", a=start, b=end)
        f["bookings_today"] = await _scalar(conn, "select count(*) from app.bookings where starts_at >= :a and starts_at < :b and status <> 'cancelled'",
                                            a=today[0], b=today[1])
    if "ai_receptionist" in autos:
        f["calls"] = await _scalar(conn, """select count(*) from app.conversations where channel = 'voice' and created_at >= :a and created_at < :b
            and coalesce(metadata->>'test', 'false') <> 'true'""", a=start, b=end)
    if "inbox_triage" in autos:
        f["emails"] = await _scalar(conn, "select count(*) from app.conversations where channel = 'email' and created_at >= :a and created_at < :b", a=start, b=end)
        f["urgent_open"] = await _scalar(conn, """select count(*) from app.conversations where channel = 'email' and status <> 'closed'
            and coalesce((metadata->'triage'->>'urgent')::boolean, false) and created_at > now() - interval '7 days'""")
    if "content_repurposing" in autos:
        f["posts_to_review"] = await _scalar(conn, "select count(*) from app.content_posts where review in ('pending','needs_attention')")
        f["posts_published"] = await _scalar(conn, "select count(*) from app.content_posts where published_at >= :a and published_at < :b", a=start, b=end)
    if "cold_email" in autos:
        f["interested"] = await _scalar(conn, """select count(*) from app.email_events e join app.prospects p on p.id = e.prospect_id
            where e.kind = 'reply' and p.reply_kind = 'interested' and e.at >= :a and e.at < :b""", a=start, b=end)
    return f


def items(f: dict) -> list[dict]:
    """Ranked: do these first, then today, then good news. Each: {text, action, link, kind}."""
    out: list[dict] = []
    cur = f["currency"]
    cards = f["cards"]
    if cards.get("waiting"):
        out.append({"kind": "do", "text": f"{cards['waiting']} card{'s' if cards['waiting'] != 1 else ''} waiting over 4 hours",
                    "action": "Clear them in Needs you", "link": "/needs-you"})
    if cards.get("callbacks"):
        out.append({"kind": "do", "text": f"{cards['callbacks']} {'people' if cards['callbacks'] != 1 else 'person'} asked for a call back",
                    "action": "Call them today", "link": "/needs-you"})
    if f.get("urgent_open"):
        out.append({"kind": "do", "text": f"{f['urgent_open']} urgent email{'s' if f['urgent_open'] != 1 else ''} still open",
                    "action": "Reply or close them", "link": "/conversations?channel=email"})
    if f.get("overdue_count"):
        b = f.get("biggest_overdue")
        extra = f"; biggest: {b['number']}{' (' + b['who'] + ')' if b.get('who') else ''}, {_money(b['balance'], cur)}, {b['days']} days late" if b else ""
        out.append({"kind": "do", "text": f"{_money(f['overdue'], cur)} overdue across {f['overdue_count']} invoice{'s' if f['overdue_count'] != 1 else ''}{extra}",
                    "action": "A personal call works best for the biggest one", "link": "/invoices"})
    if f.get("leads_untouched"):
        out.append({"kind": "do", "text": f"{f['leads_untouched']} new lead{'s' if f['leads_untouched'] != 1 else ''} not contacted yet",
                    "action": "Reply while they're warm", "link": "/leads"})
    if f.get("posts_to_review"):
        out.append({"kind": "do", "text": f"{f['posts_to_review']} post{'s' if f['posts_to_review'] != 1 else ''} waiting for your approval",
                    "action": "Approve the ones you like", "link": "/content"})
    if f.get("bookings_today"):
        out.append({"kind": "today", "text": f"{f['bookings_today']} appointment{'s' if f['bookings_today'] != 1 else ''} today",
                    "action": "", "link": "/calendar"})
    good = []
    if f.get("money_in"):
        good.append(f"{_money(f['money_in'], cur)} received ({f['payments']} payment{'s' if f['payments'] != 1 else ''})")
    if f.get("bookings_made"):
        good.append(f"{f['bookings_made']} booking{'s' if f['bookings_made'] != 1 else ''} made")
    if f.get("leads"):
        good.append(f"{f['leads']} new lead{'s' if f['leads'] != 1 else ''}")
    if f.get("calls"):
        good.append(f"{f['calls']} call{'s' if f['calls'] != 1 else ''} answered")
    if f.get("emails"):
        good.append(f"{f['emails']} email{'s' if f['emails'] != 1 else ''} sorted")
    if f.get("interested"):
        good.append(f"{f['interested']} interested cold-email repl{'ies' if f['interested'] != 1 else 'y'}")
    if f.get("posts_published"):
        good.append(f"{f['posts_published']} post{'s' if f['posts_published'] != 1 else ''} published")
    if good:
        out.append({"kind": "good", "text": ", ".join(good), "action": "", "link": "/reports"})
    return out


OPENER = """Write ONE short, warm opening sentence (max 25 words) for a business owner's {period} brief. Use only these facts,
and no numbers that aren't here. No emojis, no exclamation marks.

Business: {business}. First name: {name}.
{facts}"""


async def opener(org_id: str, period: str, business: str, name: str | None, its: list[dict], use_model: bool = True) -> str:
    todo = sum(1 for i in its if i["kind"] == "do")
    name = name[:1].upper() + name[1:] if name else name
    needs = f"{todo} thing{'s' if todo != 1 else ''} need{'s' if todo == 1 else ''} you today." if todo else "nothing urgent today."
    if not use_model:  # the portal's card: any time of day
        return f"{name}, {needs}" if name else needs[:1].upper() + needs[1:]
    fallback = (f"Good morning{', ' + name if name else ''}: " if period == "daily" else f"Your week at {business}: ") + needs
    facts = "\n".join(f"- {i['text']}" for i in its) or "- a quiet day"
    try:
        res = await complete("writer", [{"role": "user", "content": OPENER.format(period="morning" if period == "daily" else "weekly", business=business,
                                                                               name=name or "", facts=facts)}],
                             org_id=org_id, prompt_key="pulse_opener", prompt_version="v1", mock_response=fallback)
        line = res.text.strip().splitlines()[0] if res.text.strip() else fallback
    except AllModelsFailed:
        return fallback
    allowed = set(re.findall(r"\d[\d,.]*", facts + f" {todo}"))
    if any(n not in allowed for n in re.findall(r"\d[\d,.]*", line)) or len(line) > 220:
        return fallback  # a number we didn't give it: use the plain line
    return line


def render(op: str, its: list[dict], period: str) -> str:
    lines = [op, ""]
    do = [i for i in its if i["kind"] == "do"]
    today = [i for i in its if i["kind"] == "today"]
    good = [i for i in its if i["kind"] == "good"]
    if do:
        lines += ["Needs you:"] + [f"• {i['text']}. {i['action']}." for i in do] + [""]
    if today:
        lines += [f"• {i['text']}." for i in today] + [""]
    if good:
        lines += [("Yesterday: " if period == "daily" else "This week: ") + good[0]["text"] + "."]
    if not (do or today or good):
        lines += ["A quiet one: nothing new, nothing waiting."]
    return "\n".join(lines).strip()


def windows(period: str, tz: str, now: datetime) -> tuple[datetime, datetime, tuple[datetime, datetime]]:
    zone = ZoneInfo(tz or "Asia/Kolkata")
    local_today = now.astimezone(zone).date()
    day = lambda d: datetime.combine(d, time.min, tzinfo=zone).astimezone(UTC)
    today = (day(local_today), day(local_today + timedelta(days=1)))
    if period == "daily":
        return day(local_today - timedelta(days=1)), today[0], today
    return day(local_today - timedelta(days=7)), today[0], today


async def build(org_id: str, period: str = "daily", now: datetime | None = None, *, with_opener: bool = True) -> dict:
    now = now or datetime.now(UTC)
    async with tenant_session(org_id) as conn:
        org = (await conn.execute(text("""select o.name, s.timezone from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
        owner = (await conn.execute(text("""select u.name from auth.member m join auth."user" u on u.id = m."userId"
            where m."organizationId" = :o and m.role like '%owner%' order by m."createdAt" limit 1"""), {"o": org_id})).scalar_one_or_none()
        start, end, today = windows(period, org["timezone"], now)
        f = await gather(conn, start, end, today)
    its = items(f)
    first = (owner or "").split(" ")[0] or None
    op = await opener(org_id, period, org["name"], first, its, use_model=with_opener)
    title = (f"Morning brief: {sum(1 for i in its if i['kind'] == 'do')} to do" if period == "daily" else f"Your week at {org['name']}")
    return {"period": period, "title": title, "opener": op, "items": its, "body": render(op, its, period), "facts": f,
            "from": start.isoformat(), "to": end.isoformat()}


async def send(org_id: str, period: str, now: datetime | None = None) -> int:
    """Emit the pulse event (the Notification Center delivers it). Returns the event id."""
    b = await build(org_id, period, now)
    async with tenant_session(org_id) as conn:
        return await emit(conn, org_id, f"pulse.{period}", {"title": b["title"], "body": b["body"], "items": b["items"],
                                                            "todo": sum(1 for i in b["items"] if i["kind"] == "do")})


async def due(now: datetime | None = None) -> list[tuple[str, str]]:
    """Businesses whose brief is due this hour (their local time), once a day; Monday also gets the week."""
    now = now or datetime.now(UTC)
    async with system_session() as conn:
        rows = (await conn.execute(text("""select s.org_id, s.timezone, s.profile from app.org_settings s where s.status = 'live'"""))).mappings().all()
    out = []
    for r in rows:
        p = (r["profile"] or {}).get("pulse") or {}
        if p.get("enabled") is False:
            continue
        local = now.astimezone(ZoneInfo(r["timezone"] or "Asia/Kolkata"))
        if local.hour != int(p.get("hour", DEFAULT_HOUR)):
            continue
        sent = (r["profile"] or {}).get("pulse_sent") or {}
        today = local.date().isoformat()
        if sent.get("daily") != today:
            out.append((r["org_id"], "daily"))
        if local.weekday() == 0 and p.get("weekly", True) and sent.get("weekly") != today:
            out.append((r["org_id"], "weekly"))
    return out


async def mark_sent(org_id: str, period: str, day: date) -> None:
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""update app.org_settings set profile = jsonb_set(profile, '{pulse_sent}',
            coalesce(profile->'pulse_sent', '{}'::jsonb) || jsonb_build_object(cast(:p as text), cast(:d as text)))"""), {"p": period, "d": day.isoformat()})


def settings_of(profile: dict) -> dict:
    p = (profile or {}).get("pulse") or {}
    return {"enabled": p.get("enabled", True), "hour": int(p.get("hour", DEFAULT_HOUR)), "weekly": p.get("weekly", True)}

