"""Notification Center (docs/ROADMAP-V2.md §2.1): any event, to the right people, on the right channel.

    event -> rules that match (event type + conditions on the event's facts)
          -> people (roles / named people / the card's assignee, who may see that kind of event; personal rules: just them)
          -> one notification per person (never twice for one event), shown in the portal's bell
          -> now: Telegram / WhatsApp / email as the rule says; anything that can't go out falls back to email
             later: quiet hours hold it until morning (unless critical); over a person's hourly limit, or a digest rule,
             it waits for the next digest; held items go out together as one message

The existing alert kinds (urgent emails, escalations, the weekly summary…) keep working as before; this covers the rest.
"""
import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.permissions import can

CHANNELS = ("telegram", "whatsapp", "email", "in_app")
OPS = ("gt", "gte", "lt", "lte", "eq", "ne", "in", "contains")
DEFAULT_MAX_PER_HOUR = 10
Describe = Callable[[AsyncConnection, dict], Awaitable[dict | None]]


@dataclass
class EventSpec:
    label: str
    area: str
    describe: Describe
    permission: tuple[str, str] = ("dashboard", "read")
    automations: tuple[str, ...] | None = None  # shown only to businesses with one of these (None: everyone)
    facts: dict[str, str] = field(default_factory=dict)  # fields rules can test: name -> "number" | "text" | "bool"


def _money(v: float | None, currency: str = "INR") -> str:
    if v is None:
        return ""
    return f"₹{v:,.0f}" if currency == "INR" else f"{currency} {v:,.2f}"


async def _one(conn: AsyncConnection, sql: str, **params: object) -> dict:
    row = (await conn.execute(text(sql), params)).mappings().first()
    return dict(row) if row else {}


# ---------- what each event says ----------

async def d_payment(conn, p):
    cur = p.get("currency") or "INR"
    return {"title": f"Payment received: {_money(p.get('amount'), cur)}" + (f" for {p['invoice']}" if p.get("invoice") else ""),
            "body": f"Via {p.get('gateway') or 'payment'}{', reference ' + p['reference'] if p.get('reference') else ''}. Invoice now {p.get('status', 'updated').replace('_', ' ')}.",
            "link": "/invoices", "facts": {"amount": p.get("amount"), "currency": cur, "invoice": p.get("invoice"), "gateway": p.get("gateway")}}


async def d_lead(conn, p):
    r = await _one(conn, """select coalesce(k.name, k.email, k.phone, 'Someone') as who, l.source, l.stage from app.leads l
        join app.contacts k on k.id = l.contact_id where l.id = cast(:i as uuid)""", i=p.get("lead_id"))
    if not r:
        return None
    return {"title": f"New lead: {r['who']}", "body": f"From {(r['source'] or 'unknown').replace('_', ' ')}.", "link": "/leads",
            "facts": {"source": r["source"], "stage": r["stage"]}}


async def d_booking(conn, p):
    at = datetime.fromisoformat(p["starts_at"]) if p.get("starts_at") else None
    when = at.strftime("%a %d %b, %I:%M %p") if at else "soon"
    return {"title": f"New booking: {p.get('service') or 'appointment'} on {when}", "body": f"Booked through {(p.get('source') or 'Agentry').replace('_', ' ')}.",
            "link": "/leads", "facts": {"service": p.get("service"), "source": p.get("source")}}


async def d_booking_change(conn, p):
    r = await _one(conn, """select s.name as service, k.name as who, b.starts_at from app.bookings b join app.services s on s.id = b.service_id
        left join app.contacts k on k.id = b.contact_id where b.id = cast(:i as uuid)""", i=p.get("booking_id"))
    r = r or {}
    when = r["starts_at"].strftime("%a %d %b, %I:%M %p") if r.get("starts_at") else "soon"
    what = "Cancelled" if p.get("reason") is not None else "No-show"
    return {"title": f"{what}: {r.get('who') or 'a customer'}, {r.get('service') or 'appointment'} on {when}",
            "body": p.get("reason") or "They didn't come in. The concierge has offered them new times.",
            "link": "/calendar", "facts": {"service": r.get("service"), "reason": p.get("reason")}}


async def d_call(conn, p):
    r = await _one(conn, """select metadata->'call' as call, (metadata->>'duration_seconds')::int as secs, metadata->>'test' as test
        from app.conversations where id = cast(:i as uuid)""", i=p.get("conversation_id"))
    call = (r.get("call") or {}) if r else {}
    who = call.get("caller_name") or "A caller"
    return {"title": f"Call: {who}" + (f" ({call['intent']})" if call.get("intent") else ""), "body": call.get("summary") or "Call finished.",
            "link": f"/conversations/{p.get('conversation_id')}",
            "facts": {"outcome": call.get("outcome"), "duration_seconds": r.get("secs") if r else None, "follow_up": bool(call.get("follow_up"))}}


async def d_email(conn, p):
    r = await _one(conn, "select subject from app.conversations where id = cast(:i as uuid)", i=p.get("conversation_id"))
    return {"title": f"{'URGENT email' if p.get('urgent') else 'Email'}: {r.get('subject') or '(no subject)'}", "body": f"Sorted as {p.get('category')}.",
            "link": f"/conversations/{p.get('conversation_id')}", "facts": {"urgent": bool(p.get("urgent")), "category": p.get("category")}}


async def _card(conn, approval_id):
    return await _one(conn, """select title, kind, automation_key, assigned_to, coalesce((payload->>'urgent')::boolean, false) as urgent,
        status, extract(epoch from now() - created_at) / 3600 as hours from app.approvals where id = cast(:i as uuid)""", i=approval_id)


async def d_card(conn, p):
    a = await _card(conn, p.get("approval_id"))
    if not a or a["status"] != "pending":
        return None
    return {"title": f"Needs you: {a['title']}", "body": "Waiting in Needs you.", "link": "/needs-you", "assignee": a["assigned_to"],
            "permission": ("invoice" if a["automation_key"] == "invoice_follow_up" else "conversation", "act"),
            "facts": {"kind": a["kind"], "urgent": a["urgent"], "agent": a["automation_key"]}}


async def d_card_waiting(conn, p):
    d = await d_card(conn, p)
    if d:
        d["title"] = f"Waiting {int(p.get('hours') or 0)} h: {d['title'].removeprefix('Needs you: ')}"
        d["body"] = "Nobody has acted on this card yet."
        d["facts"]["hours"] = p.get("hours")
    return d


async def d_cold(conn, p):
    r = await _one(conn, """select coalesce(x.name, x.email) as who, co.name as company from app.prospects x
        join app.prospect_companies co on co.id = x.company_id where x.id = cast(:i as uuid)""", i=p.get("prospect_id"))
    return {"title": f"Interested reply: {r.get('who', 'a prospect')}" + (f" at {r['company']}" if r.get("company") else ""),
            "body": "They replied to your cold email and want to talk.", "link": f"/conversations/{p.get('conversation_id')}", "facts": {}}


async def d_content_ready(conn, p):
    r = await _one(conn, """select s.title, (select count(*) from app.content_posts x where x.source_id = s.id) as posts
        from app.content_sources s where s.id = cast(:i as uuid)""", i=p.get("source_id"))
    return {"title": f"{r.get('posts', 0)} posts ready to review", "body": f"From “{r.get('title', 'your recording')}”.",
            "link": f"/content/{p.get('source_id')}", "facts": {"posts": r.get("posts")}}


async def d_content_published(conn, p):
    return {"title": f"Posted on {(p.get('platform') or 'social').title()}", "body": "A scheduled post went out" + (" (test mode)." if p.get("test_mode") else "."),
            "link": "/content/calendar", "facts": {"platform": p.get("platform")}}


async def d_statement(conn, p):
    r = await _one(conn, "select number, total, currency from app.statements where id = cast(:i as uuid)", i=p.get("statement_id"))
    return {"title": f"New statement from Agentry: {r.get('number', '')}", "body": f"Total {_money(float(r['total']), r['currency'])}." if r else "",
            "link": "/billing", "facts": {"total": float(r["total"]) if r else None}}


async def d_invoice_reply(conn, p):
    return {"title": "A customer replied about an invoice", "body": (p.get("text") or "")[:300], "link": f"/conversations/{p.get('conversation_id')}",
            "facts": {}}


async def d_live(conn, p):
    return {"title": "Your agents are live", "body": "Agentry is now working for you.", "link": "/home", "facts": {}}


async def d_broken(conn, p):
    return {"title": f"{(p.get('provider') or 'A connection').title()} stopped working", "body": f"{p.get('account') or ''}: {(p.get('error') or '')[:200]}".strip(": "),
            "link": "/settings/connections", "critical": True, "facts": {"provider": p.get("provider")}}


async def d_chat(conn, p):
    r = await _one(conn, """select coalesce(k.name, 'A customer') as who, c.channel from app.conversations c left join app.contacts k on k.id = c.contact_id
        where c.id = cast(:i as uuid)""", i=p.get("conversation_id"))
    ch = {"whatsapp": "WhatsApp", "telegram": "Telegram"}.get(r.get("channel", ""), "Message")
    return {"title": f"{ch} from {r.get('who', 'a customer')}", "body": (p.get("text") or "")[:300], "link": f"/conversations/{p.get('conversation_id')}",
            "facts": {"text": p.get("text")}}


async def d_pulse(conn, p):
    return {"title": p.get("title") or "Your brief", "body": p.get("body") or "", "link": "/home", "facts": {"todo": p.get("todo")}}


async def d_brief(conn, p):
    return {"title": p.get("title") or "Meeting brief", "body": p.get("body") or "", "link": f"/leads/{p['lead_id']}" if p.get("lead_id") else "/calendar",
            "facts": {}}


async def d_researched(conn, p):
    who = await _one(conn, """select k.name, k.email from app.leads l join app.contacts k on k.id = l.contact_id where l.id = cast(:i as uuid)""",
                     i=p.get("lead_id"))
    what = p.get("company") or ("no company website found" if p.get("status") != "done" else "their company")
    return {"title": f"Researched {who.get('name') or who.get('email') or 'a new lead'}: {what}", "body": "Open the lead for the note.",
            "link": f"/leads/{p.get('lead_id')}", "facts": {"status": p.get("status")}}


CATALOGUE: dict[str, EventSpec] = {
    "payment.received": EventSpec("A payment arrives", "Money", d_payment, ("invoice", "read"), ("invoice_follow_up",),
                                  {"amount": "number", "currency": "text", "gateway": "text", "invoice": "text"}),
    "invoice.reply": EventSpec("A customer replies about an invoice", "Money", d_invoice_reply, ("invoice", "read"), ("invoice_follow_up",)),
    "statement.issued": EventSpec("Agentry issues a statement", "Money", d_statement, ("billing", "read"), None, {"total": "number"}),
    "lead.created": EventSpec("A new lead comes in", "Leads & bookings", d_lead, ("conversation", "read"), None, {"source": "text", "stage": "text"}),
    "booking.created": EventSpec("An appointment is booked", "Leads & bookings", d_booking, ("calendar", "read"),
                                 ("website_chat", "whatsapp_assistant", "telegram_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"),
                                 {"service": "text", "source": "text"}),
    "booking.cancelled": EventSpec("An appointment is cancelled", "Leads & bookings", d_booking_change, ("calendar", "read"), ("appointment_concierge",),
                                   {"service": "text", "reason": "text"}),
    "booking.no_show": EventSpec("Someone misses their appointment", "Leads & bookings", d_booking_change, ("calendar", "read"), ("appointment_concierge",),
                                 {"service": "text"}),
    "lead.researched": EventSpec("A new lead has been researched", "Leads & bookings", d_researched, ("conversation", "read"), ("lead_research",),
                                 {"status": "text"}),
    "meeting.brief": EventSpec("A meeting brief is ready (before an appointment)", "Leads & bookings", d_brief, ("calendar", "read"), ("lead_research",)),
    "cold_email.interested": EventSpec("A cold-email prospect is interested", "Leads & bookings", d_cold, ("conversation", "read"), ("cold_email",)),
    "call.completed": EventSpec("A phone call ends", "Calls & chats", d_call, ("conversation", "read"), ("ai_receptionist",),
                                {"outcome": "text", "duration_seconds": "number", "follow_up": "bool"}),
    "whatsapp.received": EventSpec("A WhatsApp message arrives", "Calls & chats", d_chat, ("conversation", "read"), ("whatsapp_assistant",), {"text": "text"}),
    "telegram.received": EventSpec("A Telegram message arrives", "Calls & chats", d_chat, ("conversation", "read"), ("telegram_assistant",), {"text": "text"}),
    "email.triaged": EventSpec("An email is sorted", "Calls & chats", d_email, ("conversation", "read"), ("inbox_triage",), {"urgent": "bool", "category": "text"}),
    "approval.created": EventSpec("A card lands in Needs you", "Work", d_card, ("dashboard", "read"), None,
                                  {"kind": "text", "urgent": "bool", "agent": "text"}),
    "approval.waiting_long": EventSpec("A card has waited 4 hours", "Work", d_card_waiting, ("dashboard", "read"), None,
                                       {"kind": "text", "urgent": "bool", "agent": "text", "hours": "number"}),
    "content.ready": EventSpec("Posts are ready to review", "Content", d_content_ready, ("conversation", "read"), ("content_repurposing",), {"posts": "number"}),
    "content.published": EventSpec("A post is published", "Content", d_content_published, ("conversation", "read"), ("content_repurposing",), {"platform": "text"}),
    "connection.broken": EventSpec("A connection stops working", "Platform", d_broken, ("connection", "manage"), None, {"provider": "text"}),
    "org.went_live": EventSpec("Your agents go live", "Platform", d_live),
    "pulse.daily": EventSpec("The morning brief is ready", "Business Pulse", d_pulse, ("dashboard", "read"), None, {"todo": "number"}),
    "pulse.weekly": EventSpec("The Monday week in review is ready", "Business Pulse", d_pulse, ("dashboard", "read"), None, {"todo": "number"}),
}

# Sensible defaults: created once per business (owners can edit or switch them off). Only for events the business has.
DEFAULTS = [  # each added once per business, by key (a business that edits or deletes one keeps its choice)
    {"key": "money_in", "name": "Money in", "event_type": "payment.received", "roles": ["owner", "finance"], "channels": ["telegram", "in_app"]},
    {"key": "bookings", "name": "New bookings", "event_type": "booking.created", "roles": ["owner", "manager", "staff"], "channels": ["in_app", "telegram"]},
    {"key": "leads_digest", "name": "New leads, daily digest", "event_type": "lead.created", "roles": ["owner", "manager"], "channels": ["telegram", "email"],
     "cadence": "digest", "digest_hour": 18},
    {"key": "waiting_assignee", "name": "Cards waiting too long", "event_type": "approval.waiting_long", "roles": [], "assignee": True,
     "channels": ["telegram", "email"]},
    {"key": "waiting_owner", "name": "Cards waiting too long (owner)", "event_type": "approval.waiting_long", "roles": ["owner"], "channels": ["telegram", "in_app"]},
    {"key": "cold_interested", "name": "Interested cold-email replies", "event_type": "cold_email.interested", "roles": ["owner", "manager"],
     "channels": ["telegram", "email"]},
    {"key": "content_ready", "name": "Posts ready to review", "event_type": "content.ready", "roles": ["owner", "manager"], "channels": ["in_app", "telegram"]},
    {"key": "broken", "name": "Broken connections", "event_type": "connection.broken", "roles": ["owner", "manager"], "channels": ["telegram", "email"],
     "critical": True},
    {"key": "meeting_briefs", "name": "Meeting briefs", "event_type": "meeting.brief", "roles": ["owner", "manager"], "channels": ["telegram", "email", "in_app"]},
    {"key": "pulse_daily", "name": "Morning brief", "event_type": "pulse.daily", "roles": ["owner"], "channels": ["telegram", "email"]},
    {"key": "pulse_weekly", "name": "Monday week in review", "event_type": "pulse.weekly", "roles": ["owner", "manager"], "channels": ["email", "telegram"]},
]
LEGACY_KEYS = ["money_in", "bookings", "leads_digest", "waiting_assignee", "waiting_owner", "cold_interested", "content_ready", "broken"]


def available(event_type: str, automations: list[str]) -> bool:
    spec = CATALOGUE.get(event_type)
    return bool(spec) and (spec.automations is None or bool(set(spec.automations) & set(automations)))


async def ensure_defaults(conn: AsyncConnection, org_id: str) -> int:
    """Add any default rule this business hasn't had yet (remembered by key in org_settings.profile)."""
    profile = (await conn.execute(text("select profile from app.org_settings"))).scalar_one_or_none()
    if profile is None:
        return 0
    seeded = set(profile.get("notification_default_keys") or (LEGACY_KEYS if profile.get("notification_defaults") else []))
    autos = list((await conn.execute(text("select template_key from app.automation_instances"))).scalars())
    n = 0
    for d in DEFAULTS:
        if d["key"] in seeded or not available(d["event_type"], autos):
            continue  # an agent switched on later still gets its defaults then
        seeded.add(d["key"])
        await conn.execute(text("""insert into app.notification_rules (org_id, name, event_type, roles, assignee, channels, cadence, digest_hour,
                critical, is_default) values (:o, :n, :e, :r, :a, :c, :cad, :h, :crit, true)"""),
                {"o": org_id, "n": d["name"], "e": d["event_type"], "r": d["roles"], "a": d.get("assignee", False), "c": d["channels"],
                 "cad": d.get("cadence", "now"), "h": d.get("digest_hour", 18), "crit": d.get("critical", False)})
        n += 1
    await conn.execute(text("update app.org_settings set profile = profile || jsonb_build_object('notification_default_keys', cast(:k as jsonb))"),
                       {"k": json.dumps(sorted(seeded))})
    return n


# ---------- matching ----------

def matches(conditions: list[dict], facts: dict) -> bool:
    for c in conditions or []:
        v, want, op = facts.get(c.get("field")), c.get("value"), c.get("op", "eq")
        try:
            if op in ("gt", "gte", "lt", "lte"):
                if v is None:
                    return False
                a, b = float(v), float(want)
                if not {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]:
                    return False
            elif op == "eq" and str(v).lower() != str(want).lower() or op == "ne" and str(v).lower() == str(want).lower() or op == "in" and str(v).lower() not in [str(x).strip().lower() for x in (want if isinstance(want, list) else str(want).split(","))] or op == "contains" and str(want).lower() not in str(v or "").lower():
                return False
        except (TypeError, ValueError):
            return False
    return True


async def _people(conn: AsyncConnection, org_id: str) -> list[dict]:
    rows = (await conn.execute(text("""select m."userId" as user_id, m.role, u.email, u.name, u.role as platform_role, p.prefs, t.chat_id
        from auth.member m join auth."user" u on u.id = m."userId"
        left join app.notification_preferences p on p.user_id = m."userId" and p.org_id = m."organizationId"
        left join app.telegram_links t on t.user_id = m."userId" and t.org_id = m."organizationId"
        where m."organizationId" = :o"""), {"o": org_id})).mappings().all()
    return [dict(r) for r in rows]


def _may(person: dict, perm: tuple[str, str]) -> bool:
    return person["platform_role"] == "admin" or can(person["role"], *perm)


def audience(rule: dict, people: list[dict], perm: tuple[str, str], assignee: str | None) -> list[dict]:
    out = []
    for p in people:
        if rule["owner_user"]:
            chosen = p["user_id"] == rule["owner_user"]
        else:
            roles = {r.strip() for r in (p["role"] or "").split(",")}
            chosen = bool(roles & set(rule["roles"])) or p["user_id"] in rule["user_ids"] or (rule["assignee"] and assignee == p["user_id"])
        muted = str(rule["id"]) in ((p["prefs"] or {}).get("muted_rules") or [])
        if chosen and not muted and _may(p, perm):
            out.append(p)
    return out


def _local(now: datetime, tz: str) -> datetime:
    return now.astimezone(ZoneInfo(tz or "Asia/Kolkata"))


def quiet_until(prefs: dict, now: datetime, tz: str) -> datetime | None:
    """When this person's quiet hours end, if they're in them now (e.g. {"from": "21:00", "to": "08:00"})."""
    q = (prefs or {}).get("quiet") or {}
    if not q.get("from") or not q.get("to"):
        return None
    local = _local(now, tz)
    start, end = time.fromisoformat(q["from"]), time.fromisoformat(q["to"])
    t = local.time()
    inside = (start <= t or t < end) if start > end else (start <= t < end)
    if not inside:
        return None
    day = local.date() if t < end else local.date() + timedelta(days=1)
    return datetime.combine(day, end, tzinfo=local.tzinfo).astimezone(UTC)


def next_digest(hour: int, now: datetime, tz: str) -> datetime:
    local = _local(now, tz)
    at = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    return (at if at > local else at + timedelta(days=1)).astimezone(UTC)


# ---------- planning (event -> notifications) ----------

async def plan(event: dict, now: datetime | None = None) -> list[int]:
    """Create the notifications for one event; returns the ids to send now."""
    spec = CATALOGUE.get(event["type"])
    if not spec or not event.get("org_id"):
        return []
    now = now or datetime.now(UTC)
    org_id = event["org_id"]
    send_now: list[int] = []
    async with tenant_session(org_id) as conn:
        await ensure_defaults(conn, org_id)
        rules = [dict(r) for r in (await conn.execute(text("""select * from app.notification_rules where enabled and event_type = :e
            order by owner_user nulls first, created_at"""), {"e": event["type"]})).mappings()]
        if not rules:
            return []
        d = await spec.describe(conn, event.get("payload") or {})
        if not d:
            return []
        tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
        people = await _people(conn, org_id)
        perm = d.get("permission") or spec.permission
        critical_event = bool(d.get("critical"))
        done: set[str] = set()
        for rule in rules:
            if not matches(rule["conditions"], d.get("facts") or {}):
                continue
            for p in audience(rule, people, perm, d.get("assignee")):
                if p["user_id"] in done:
                    continue  # one notification per person per event, from the first rule that matches
                done.add(p["user_id"])
                critical = rule["critical"] or critical_event
                external = [c for c in rule["channels"] if c != "in_app"]
                status, after = "pending", None
                if not external:
                    status = "in_app_only"
                elif rule["cadence"] == "digest" and not critical:
                    status, after = "digest", next_digest(rule["digest_hour"], now, tz)
                elif not critical and (q := quiet_until(p["prefs"], now, tz)):
                    status, after = "held", q
                elif not critical:
                    limit = int((p["prefs"] or {}).get("max_per_hour") or DEFAULT_MAX_PER_HOUR)
                    recent = (await conn.execute(text("""select count(*) from app.notifications where user_id = :u and status = 'sent'
                        and sent_at > :t"""), {"u": p["user_id"], "t": now - timedelta(hours=1)})).scalar_one()
                    if recent >= limit:
                        status, after = "digest", now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                nid = (await conn.execute(text("""insert into app.notifications (org_id, user_id, event_id, event_type, rule_id, title, body, link,
                    critical, status, deliver_after, deliveries) values (:o, :u, :e, :t, cast(:r as uuid), :ti, :b, :l, :c, :s, :a,
                    cast(:ch as jsonb)) on conflict (org_id, user_id, event_id) do nothing returning id"""),
                    {"o": org_id, "u": p["user_id"], "e": event["id"], "t": event["type"], "r": str(rule["id"]), "ti": d["title"][:300],
                     "b": d.get("body", "")[:2000], "l": d.get("link"), "c": critical, "s": status, "a": after,
                     "ch": json.dumps([{"channel": c, "status": "planned"} for c in external])})).scalar_one_or_none()
                if nid and status == "pending":
                    send_now.append(nid)
    return send_now


# ---------- delivery ----------

async def _send(channel: str, person: dict, org_id: str, subject: str, body: str) -> str | None:
    """Returns None on success, else why not."""
    if channel == "telegram":
        from agentry import telegram_team
        if not (telegram_team.enabled() and person.get("chat_id")):
            return "Telegram isn't linked"
        return None if await telegram_team.send_alert(person["chat_id"], subject, body) else "Telegram send failed"
    if channel == "whatsapp":
        from agentry.notify.alerts import whatsapp_alerts
        to = (person.get("prefs") or {}).get("whatsapp_to")
        wa = await whatsapp_alerts(org_id) if to else None
        if not wa:
            return "WhatsApp alerts aren't set up for this person"
        from agentry.connectors.whatsapp import WhatsAppError, send_template
        try:
            await send_template(org_id, to, wa["template"], wa["lang"], [subject[:200], body[:900]])
            return None
        except WhatsAppError as e:
            return f"WhatsApp: {str(e)[:150]}"
    if channel == "email":
        from agentry.notify.alerts import send_email
        try:
            await asyncio.to_thread(send_email, person["email"], subject, body)
            return None
        except Exception as e:  # noqa: BLE001 - recorded on the notification
            return f"email: {str(e)[:150]}"
    return f"unknown channel {channel}"


async def deliver(org_id: str, ids: list[int]) -> dict:
    """Send these notifications (one person each; several ids for one person = one combined message, e.g. a digest)."""
    if not ids:
        return {"sent": 0}
    async with tenant_session(org_id) as conn:
        rows = [dict(r) for r in (await conn.execute(text("""select n.*, r.channels from app.notifications n
            left join app.notification_rules r on r.id = n.rule_id where n.id = any(:i) order by n.created_at"""), {"i": ids})).mappings()]
        people = {p["user_id"]: p for p in await _people(conn, org_id)}
    by_person: dict[str, list[dict]] = {}
    for r in rows:
        by_person.setdefault(r["user_id"], []).append(r)
    sent = 0
    for uid, items in by_person.items():
        person = people.get(uid)
        if not person:
            continue
        channels = [c for c in dict.fromkeys(c for it in items for c in (it["channels"] or ["email"])) if c != "in_app"] or ["email"]
        if len(items) == 1:
            it = items[0]
            subject, body = it["title"], it["body"] + (f"\n\n{settings.dashboard_url}{it['link']}" if it["link"] else "")
        else:
            subject = f"{len(items)} updates from Agentry"
            body = "\n".join(f"• {it['title']}" for it in items) + f"\n\n{settings.dashboard_url}/home"
        log, ok = [], False
        for ch in channels:
            why = await _send(ch, person, org_id, subject, body)
            log.append({"channel": ch, "status": "sent" if why is None else "failed", "error": why, "at": datetime.now(UTC).isoformat(timespec="seconds")})
            ok = ok or why is None
        if not ok and "email" not in channels:  # nobody misses it: email as the last resort
            why = await _send("email", person, org_id, subject, body)
            log.append({"channel": "email", "status": "sent" if why is None else "failed", "error": why, "fallback": True,
                        "at": datetime.now(UTC).isoformat(timespec="seconds")})
            ok = why is None
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.notifications set status = :s, sent_at = case when :ok then now() else sent_at end,
                deliveries = cast(:d as jsonb) where id = any(:i)"""),
                {"s": "sent" if ok else "failed", "ok": ok, "d": json.dumps(log), "i": [it["id"] for it in items]})
        sent += ok
    return {"sent": sent}


async def release_due(now: datetime | None = None) -> int:
    """Held (quiet hours) and digest notifications whose time has come: one combined message per person."""
    now = now or datetime.now(UTC)
    async with system_session() as conn:
        rows = (await conn.execute(text("""select org_id, user_id, array_agg(id order by created_at) as ids from app.notifications
            where status in ('held','digest') and deliver_after <= :n group by org_id, user_id"""), {"n": now})).all()
    for org_id, _uid, ids in rows:
        await deliver(org_id, list(ids))
    return len(rows)
