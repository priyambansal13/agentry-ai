"""Agentry's team bot on Telegram: alerts, Needs-you cards with buttons, and a Tools menu for every agent a business has.

Linking: Account & notifications -> Connect Telegram opens t.me/<bot>?start=<one-time code>; the bot ties that chat to
the person in that business. A chat linked in several businesses works in one at a time (/business to switch).

Everything goes through the same rules as the portal: a person only sees and acts on what their role allows, card
decisions use approvals.decide (audited "via telegram"), and links open the portal for anything bigger.
"""
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from agentry import approvals
from agentry.config import settings
from agentry.connectors import telegram as tg
from agentry.db import system_session, tenant_session
from agentry.features import org_features
from agentry.permissions import can, role_label

CODE_TTL = timedelta(minutes=15)
_username: str | None = None
CARD_KINDS = {"reply_draft": "Reply to send", "outbound_draft": "Message to send", "handoff": "Needs a person", "escalation": "Needs you",
              "dispute": "Disputed invoice", "low_confidence": "Check this", "payment_review": "Payment to check", "callback": "Call back"}
DRAFTS = ("reply_draft", "outbound_draft")


def enabled() -> bool:
    return bool(settings.telegram_bot_token)


async def bot_username() -> str | None:
    global _username
    if _username is None and enabled():
        try:
            _username = (await tg.get_me(settings.telegram_bot_token))["username"]
        except tg.TelegramError:
            return None
    return _username


def link_to(path: str) -> str:
    return f"{settings.dashboard_url}{path}"


def _url_button(label: str, path: str) -> dict | None:
    """Telegram only accepts public https links on buttons; in local development the link goes in the text instead."""
    url = link_to(path)
    return {"text": label, "url": url} if url.startswith("https://") else None


async def _say(chat_id: int, body: str, buttons: list[list[dict | None]] | None = None) -> None:
    rows = [[b for b in row if b] for row in (buttons or [])]
    await tg.send(settings.telegram_bot_token, chat_id, body, [r for r in rows if r] or None)


# ---------- linking (portal side) ----------

async def create_link(org_id: str, user_id: str) -> dict:
    if not enabled():
        raise tg.TelegramError("Agentry's Telegram bot isn't set up yet")
    code = secrets.token_urlsafe(12)
    async with tenant_session(org_id) as conn:
        await conn.execute(text("delete from app.telegram_link_codes where expires_at < now() or (org_id = :o and user_id = :u)"),
                           {"o": org_id, "u": user_id})
        await conn.execute(text("insert into app.telegram_link_codes (code, org_id, user_id, expires_at) values (:c, :o, :u, :e)"),
                           {"c": code, "o": org_id, "u": user_id, "e": datetime.now(UTC) + CODE_TTL})
    return {"url": f"https://t.me/{await bot_username()}?start={code}", "expires_in_minutes": int(CODE_TTL.total_seconds() // 60)}


async def link_status(org_id: str, user_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("select username, linked_at from app.telegram_links where user_id = :u"), {"u": user_id})).mappings().first()
    return {"available": enabled(), "bot": await bot_username() if enabled() else None, "linked": bool(row),
            "username": row["username"] if row else None, "linked_at": row["linked_at"] if row else None}


async def unlink(org_id: str, user_id: str) -> None:
    async with tenant_session(org_id) as conn:
        await conn.execute(text("delete from app.telegram_links where user_id = :u"), {"u": user_id})


# ---------- who is this chat ----------

async def _links(chat_id: int) -> list[dict]:
    async with system_session() as conn:
        rows = (await conn.execute(text("""select l.org_id, l.user_id, l.active, l.pending, m.role, u.name, u.role as platform_role, o.name as business
            from app.telegram_links l join auth.member m on m."organizationId" = l.org_id and m."userId" = l.user_id
            join auth."user" u on u.id = l.user_id join auth.organization o on o.id = l.org_id
            where l.chat_id = :c order by l.active desc, o.name"""), {"c": chat_id})).mappings().all()
    return [dict(r) for r in rows]


class Person:
    def __init__(self, link: dict):
        self.org_id, self.user_id, self.role, self.name = link["org_id"], link["user_id"], link["role"], link["name"]
        self.business, self.pending = link["business"], link["pending"] or {}
        self.is_staff = link["platform_role"] == "admin"

    def can(self, resource: str, action: str) -> bool:
        return self.is_staff or can(self.role, resource, action)


async def _set_pending(p: Person, pending: dict | None) -> None:
    async with tenant_session(p.org_id) as conn:
        await conn.execute(text("update app.telegram_links set pending = cast(:p as jsonb) where user_id = :u"),
                           {"p": json.dumps(pending) if pending else None, "u": p.user_id})


# ---------- updates ----------

async def handle_update(update: dict) -> None:
    if cb := update.get("callback_query"):
        await _on_button(cb)
    elif (m := update.get("message")) and m.get("chat", {}).get("type") == "private":
        await _on_message(m)


async def _claim_code(chat_id: int, code: str, username: str | None) -> dict | None:
    async with system_session() as conn:
        row = (await conn.execute(text("delete from app.telegram_link_codes where code = :c and expires_at > now() returning org_id, user_id"),
                                  {"c": code})).mappings().first()
    if not row:
        return None
    async with tenant_session(row["org_id"]) as conn:
        await conn.execute(text("""insert into app.telegram_links (org_id, user_id, chat_id, username) values (:o, :u, :c, :n)
            on conflict (org_id, user_id) do update set chat_id = excluded.chat_id, username = excluded.username, linked_at = now(),
              active = true, pending = null"""), {"o": row["org_id"], "u": row["user_id"], "c": chat_id, "n": username})
    async with system_session() as conn:  # the chat now works in this business
        await conn.execute(text("update app.telegram_links set active = (org_id = :o) where chat_id = :c"), {"o": row["org_id"], "c": chat_id})
    return dict(row)


async def _on_message(m: dict) -> None:
    chat_id, body = m["chat"]["id"], (m.get("text") or "").strip()
    if body.startswith("/start"):
        code = body.split(maxsplit=1)[1] if " " in body else ""
        if code and await _claim_code(chat_id, code, m["from"].get("username")):
            links = await _links(chat_id)
            p = Person(links[0])
            await _say(chat_id, f"Connected: you'll get {p.business}'s alerts and cards here, {(p.name or '').split(' ')[0] or 'there'}.\n\n"
                                "Tap Tools for everything your agents do, or send /help.", [[{"text": "🧰 Tools", "callback_data": "tools"}]])
            return
        if code:
            await _say(chat_id, "That link has expired or was already used. Open Agentry → Account & notifications → Connect Telegram for a new one.")
            return
    links = await _links(chat_id)
    if not links:
        await _say(chat_id, "Hi! This is Agentry's bot for business teams. To connect, open Agentry → Account & notifications → "
                            "Connect Telegram.")
        return
    p = Person(next((link for link in links if link["active"]), links[0]))
    if p.pending.get("edit") and body and not body.startswith("/"):
        await _set_pending(p, None)
        await _decide(chat_id, p, p.pending["edit"], "approve", body)
        return
    if any(k in m for k in ("video", "audio", "voice", "document")):
        await _content_upload(chat_id, p, m)
        return
    cmd = body.lower().split()[0] if body else ""
    if cmd in ("/needs", "/needsyou"):
        await _needs_you(chat_id, p)
    elif cmd in ("/business", "/org"):
        await _choose_business(chat_id, links)
    elif cmd == "/help":
        await _say(chat_id, HELP, [[{"text": "🧰 Tools", "callback_data": "tools"}]])
    elif cmd == "/cancel":
        await _set_pending(p, None)
        await _say(chat_id, "Cancelled.")
    else:
        await _tools(chat_id, p)


HELP = ("What I can do:\n"
        "• Tools: everything your agents do, at a glance (/tools)\n"
        "• Needs you: approve, edit or discard drafts, mark things handled (/needs)\n"
        "• Alerts: urgent emails, escalations and more, if you chose Telegram in Account & notifications\n"
        "• Content: send me a video or audio file (up to 20 MB) and I'll turn it into posts\n"
        "• Several businesses? /business switches between them")


async def _on_button(cb: dict) -> None:
    chat_id, data = cb["message"]["chat"]["id"], cb.get("data") or ""
    await tg.call(settings.telegram_bot_token, "answerCallbackQuery", callback_query_id=cb["id"])
    links = await _links(chat_id)
    if not links:
        return
    if data.startswith("o:"):
        async with system_session() as conn:
            await conn.execute(text("update app.telegram_links set active = (org_id = :o) where chat_id = :c"), {"o": data[2:], "c": chat_id})
        links = await _links(chat_id)
        p = Person(links[0])
        await _say(chat_id, f"Now working in {p.business}.", [[{"text": "🧰 Tools", "callback_data": "tools"}]])
        return
    p = Person(next((link for link in links if link["active"]), links[0]))
    if data == "tools":
        await _tools(chat_id, p)
    elif data.startswith("t:"):
        await TOOLS[data[2:]]["run"](chat_id, p) if data[2:] in TOOLS else None
    elif data.startswith("c:"):
        _, action, aid = data.split(":", 2)
        if action == "edit":
            await _set_pending(p, {"edit": aid})
            await _say(chat_id, "Send me the new text and I'll send it as written. (/cancel to stop)")
        else:
            await _decide(chat_id, p, aid, action, None)


async def _choose_business(chat_id: int, links: list[dict]) -> None:
    if len(links) == 1:
        await _say(chat_id, f"You're connected to {links[0]['business']} only.")
        return
    await _say(chat_id, "Which business?", [[{"text": ("✓ " if link["active"] else "") + link["business"], "callback_data": f"o:{link['org_id']}"}]
                                           for link in links])


# ---------- cards ----------

def _card_text(a: dict) -> str:
    head = f"{CARD_KINDS.get(a['kind'], 'Needs you')}: {a['title']}"
    if a.get("assigned_name"):
        head += f"\n(for {a['assigned_name']})"
    parts = [head]
    if a.get("last_inbound"):
        parts.append(f"They wrote:\n{a['last_inbound'][:600]}")
    if a.get("body"):
        parts.append(("Draft:\n" if a["kind"] in DRAFTS else "") + a["body"][:2500])
    return "\n\n".join(parts)


def _card_buttons(a: dict) -> list[list[dict | None]]:
    aid = str(a["id"])
    path = f"/conversations/{a['conversation_id']}" if a.get("conversation_id") else "/needs-you"
    if a["kind"] in DRAFTS:
        return [[{"text": "✅ Approve & send", "callback_data": f"c:approve:{aid}"}, {"text": "✏️ Edit", "callback_data": f"c:edit:{aid}"}],
                [{"text": "🗑 Discard", "callback_data": f"c:reject:{aid}"}, _url_button("Open", path)]]
    return [[{"text": "✔️ Mark handled", "callback_data": f"c:resolve:{aid}"}, _url_button("Open", path)]]


CARD_SQL = """select a.id, a.kind, a.title, a.body, a.status, a.conversation_id, a.automation_key, a.assigned_to, u.name as assigned_name,
    (select body from app.messages m where m.conversation_id = a.conversation_id and m.direction = 'in' order by created_at desc limit 1) as last_inbound
    from app.approvals a left join auth."user" u on u.id = a.assigned_to"""


async def _needs_you(chat_id: int, p: Person) -> None:
    async with tenant_session(p.org_id) as conn:
        rows = [dict(r) for r in (await conn.execute(text(CARD_SQL + """ where a.status = 'pending'
            and (a.snoozed_until is null or a.snoozed_until <= now()) and (a.assigned_to is null or a.assigned_to = :u)
            order by coalesce((a.payload->>'urgent')::boolean, false) desc, a.created_at desc limit 20"""), {"u": p.user_id})).mappings()]
    mine = [a for a in rows if p.can(approvals.resource_for(a["automation_key"]), "act")]
    if not mine:
        await _say(chat_id, f"Nothing needs you in {p.business}. 🎉", [[{"text": "🧰 Tools", "callback_data": "tools"}]])
        return
    for a in mine[:5]:
        await _say(chat_id, _card_text(a), _card_buttons(a))
    if len(mine) > 5:
        await _say(chat_id, f"…and {len(mine) - 5} more.\n{link_to('/needs-you')}")


async def _decide(chat_id: int, p: Person, aid: str, action: str, body: str | None) -> None:
    async with tenant_session(p.org_id) as conn:
        try:
            status = await approvals.decide(conn, p.org_id, aid, action, body, user_id=p.user_id, name=p.name, is_staff=p.is_staff,
                                            actor_type="agentry_staff" if p.is_staff else "user", can_act=lambda r: p.can(r, "act"), via="telegram")
        except approvals.CardError as e:
            await _say(chat_id, f"Couldn't do that: {e}")
            return
    await _say(chat_id, {"approved": "✅ Approved: it's being sent.", "edited": "✅ Sent with your changes.", "rejected": "🗑 Discarded.",
                         "resolved": "✔️ Marked as handled."}[status])


async def push_card(org_id: str, approval_id: str) -> int:
    """A new card: send it to the people who'd act on it and want cards on Telegram. Returns how many got it."""
    if not enabled():
        return 0
    async with tenant_session(org_id) as conn:
        a = (await conn.execute(text(CARD_SQL + " where a.id = cast(:i as uuid) and a.status = 'pending'"), {"i": approval_id})).mappings().first()
        if not a:
            return 0
        a = dict(a)
        people = (await conn.execute(text("""select l.user_id, l.chat_id, m.role, u.role as platform_role, p.prefs from app.telegram_links l
            join auth.member m on m."organizationId" = l.org_id and m."userId" = l.user_id join auth."user" u on u.id = l.user_id
            left join app.notification_preferences p on p.user_id = l.user_id and p.org_id = l.org_id"""))).mappings().all()
    sent = 0
    resource = approvals.resource_for(a["automation_key"])
    for person in people:
        if a["assigned_to"] and person["user_id"] != a["assigned_to"]:
            continue
        if not (person["platform_role"] == "admin" or can(person["role"], resource, "act")):
            continue
        if "telegram" not in ((person["prefs"] or {}).get("cards", ["telegram"])):
            continue  # turned off in Account & notifications
        try:
            await _say(person["chat_id"], _card_text(a), _card_buttons(a))
            sent += 1
        except tg.TelegramError:
            pass  # they blocked the bot; the card is in the portal anyway
    return sent


async def send_alert(chat_id: int, subject: str, body: str) -> bool:
    try:
        await _say(chat_id, f"🔔 {subject}\n\n{body[:3500]}")
        return True
    except tg.TelegramError:
        return False


# ---------- tools ----------

async def _back() -> list[list[dict]]:
    return [[{"text": "◀ Tools", "callback_data": "tools"}]]


async def _tools(chat_id: int, p: Person) -> None:
    async with tenant_session(p.org_id) as conn:
        f = await org_features(conn)
    keys = [k for k, t in TOOLS.items() if t["when"](f, p)]  # f: what this business has (agentry/features.py)
    rows = [[{"text": TOOLS[k]["label"], "callback_data": f"t:{k}"} for k in keys[i:i + 2]] for i in range(0, len(keys), 2)]
    await _say(chat_id, f"🧰 Tools for {p.business} ({role_label(p.role)})", rows)


async def _rows(p: Person, sql: str, params: dict | None = None) -> list[dict]:
    async with tenant_session(p.org_id) as conn:
        return [dict(r) for r in (await conn.execute(text(sql), params or {})).mappings()]


def _money(v: float, currency: str = "INR") -> str:
    return f"₹{v:,.0f}" if currency == "INR" else f"{currency} {v:,.2f}"


async def t_needs(chat_id: int, p: Person) -> None:
    await _needs_you(chat_id, p)


async def t_inbox(chat_id: int, p: Person) -> None:
    r = (await _rows(p, """select count(*) filter (where c.created_at > now() - interval '24 hours') as today,
        count(*) filter (where (c.metadata->'triage'->>'urgent')::boolean and c.status <> 'closed' and c.created_at > now() - interval '7 days') as urgent
        from app.conversations c where c.channel = 'email'"""))[0]
    urgent = await _rows(p, """select subject from app.conversations where channel = 'email' and (metadata->'triage'->>'urgent')::boolean
        and status <> 'closed' and created_at > now() - interval '7 days' order by created_at desc limit 5""")
    lines = [f"📥 Inbox: {r['today']} emails sorted in the last 24 hours, {r['urgent']} urgent this week."]
    lines += [f"• {u['subject'] or '(no subject)'}" for u in urgent]
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/conversations?channel=email')}", await _back())


async def t_invoices(chat_id: int, p: Person) -> None:
    rows = await _rows(p, """select i.number, i.currency, i.amount - i.amount_paid as balance, current_date - i.due_on as late, coalesce(k.company, k.name) as who
        from app.invoices i left join app.contacts k on k.id = i.contact_id where i.status in ('open','partially_paid') order by i.due_on""")
    cur = rows[0]["currency"] if rows else "INR"
    overdue = [r for r in rows if r["late"] > 0]
    total, late = sum(float(r["balance"]) for r in rows), sum(float(r["balance"]) for r in overdue)
    lines = [f"💰 Outstanding {_money(total, cur)}, overdue {_money(late, cur)} ({len(overdue)} invoices)."]
    lines += [f"• {r['number']} {r['who'] or ''}: {_money(float(r['balance']), r['currency'])}, {r['late']} days late"
              for r in sorted(overdue, key=lambda r: -r["late"])[:5]]
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/invoices')}", await _back())


async def t_leads(chat_id: int, p: Person) -> None:
    rows = await _rows(p, """select l.stage, count(*) as n from app.leads l where l.created_at > now() - interval '7 days' group by l.stage order by n desc""")
    latest = await _rows(p, """select coalesce(k.name, k.email, k.phone) as who, l.source, l.stage from app.leads l join app.contacts k on k.id = l.contact_id
        order by l.created_at desc limit 5""")
    lines = ["🧲 Leads this week: " + (", ".join(f"{r['n']} {r['stage']}" for r in rows) or "none yet")]
    lines += [f"• {r['who']} ({r['source']}, {r['stage']})" for r in latest]
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/leads')}", await _back())


async def t_cold(chat_id: int, p: Person) -> None:
    rows = await _rows(p, """select c.name, c.status, (select count(*) from app.prospects x where x.campaign_id = c.id and x.review in ('pending','needs_attention')) as to_review,
        (select count(distinct prospect_id) from app.email_events e where e.campaign_id = c.id and e.kind = 'sent') as emailed,
        (select count(*) from app.prospects x where x.campaign_id = c.id and x.reply_kind = 'interested') as interested
        from app.campaigns c where c.kind = 'cold_email' order by c.created_at desc limit 5""")
    lines = ["✉️ Cold email"] + [f"• {r['name']} ({r['status']}): {r['emailed']} emailed, {r['interested']} interested, {r['to_review']} lines to review"
                                 for r in rows] if rows else ["✉️ No cold email lists yet."]
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/cold-email')}", await _back())


async def t_content(chat_id: int, p: Person) -> None:
    rows = await _rows(p, """select s.title, s.status, (select count(*) from app.content_posts x where x.source_id = s.id and x.review in ('pending','needs_attention')) as to_review,
        (select count(*) from app.content_posts x where x.source_id = s.id and x.published_at is null and x.scheduled_at is not null) as scheduled
        from app.content_sources s order by s.created_at desc limit 5""")
    lines = ["🎬 Content"] + [f"• {r['title'][:60]} ({r['status']}): {r['to_review']} to review, {r['scheduled']} scheduled" for r in rows]
    if p.can("automation", "configure"):
        lines.append("\nSend me a video or audio file (up to 20 MB) and I'll turn it into posts.")
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/content')}", await _back())


async def t_calls(chat_id: int, p: Person) -> None:
    r = (await _rows(p, """select count(*) filter (where created_at > now() - interval '24 hours') as today,
        count(*) filter (where created_at > now() - interval '7 days') as week from app.conversations where channel = 'voice'"""))[0]
    cb = (await _rows(p, "select count(*) as n from app.approvals where kind = 'callback' and status = 'pending'"))[0]["n"]
    await _say(chat_id, f"📞 Calls: {r['today']} today, {r['week']} this week. {cb} callbacks waiting.\n\n{link_to('/conversations?channel=voice')}",
               [[{"text": "Callbacks", "callback_data": "t:needs"}], *await _back()])


async def t_chats(chat_id: int, p: Person) -> None:
    rows = await _rows(p, """select channel, count(*) filter (where created_at > now() - interval '24 hours') as today,
        count(*) filter (where status = 'handed_off') as waiting from app.conversations where channel in ('web_chat','whatsapp','telegram') group by channel""")
    names = {"web_chat": "Website chat", "whatsapp": "WhatsApp", "telegram": "Telegram"}
    lines = ["💬 Chats"] + [f"• {names[r['channel']]}: {r['today']} today, {r['waiting']} waiting for a person" for r in rows] if rows else ["💬 No chats yet."]
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/conversations')}", await _back())


async def t_results(chat_id: int, p: Person) -> None:
    from agentry import billing
    start = datetime.now(UTC).replace(day=1).date()
    async with tenant_session(p.org_id) as conn:
        r = await billing.month_report(conn, start, datetime.now(UTC).date())
    lines = [f"📈 {datetime.now(UTC):%B} so far", f"• Appointments booked: {r['appointments']}", f"• Money recovered: {_money(r['recovered'], r['currency'])}",
             f"• Emails sorted: {r['emails_triaged']}", f"• Messages sent: {r['messages']}"]
    if r["content"]["generated"]:
        lines.append(f"• Posts written: {r['content']['generated']}, published: {r['content']['published']}")
    await _say(chat_id, "\n".join(lines) + f"\n\n{link_to('/reports')}", await _back())


async def t_pulse(chat_id: int, p: Person) -> None:
    from agentry import pulse
    b = await pulse.build(p.org_id, "daily", with_opener=False)
    await _say(chat_id, f"☀️ {b['title']}\n\n{b['body']}\n\n{link_to('/home')}", await _back())


TOOLS = {  # each tool appears when the business has that part of the portal and the person may see it
    "pulse": {"label": "☀️ Today", "run": t_pulse, "when": lambda f, p: p.can("dashboard", "read")},
    "needs": {"label": "📋 Needs you", "run": t_needs, "when": lambda f, p: "needs-you" in f["pages"] and (p.can("conversation", "act") or p.can("invoice", "act"))},
    "inbox": {"label": "📥 Inbox", "run": t_inbox, "when": lambda f, p: "inbox_triage" in f["automations"] and p.can("conversation", "read")},
    "invoices": {"label": "💰 Invoices", "run": t_invoices, "when": lambda f, p: "invoices" in f["pages"] and p.can("invoice", "read")},
    "leads": {"label": "🧲 Leads", "run": t_leads, "when": lambda f, p: "leads" in f["pages"] and p.can("conversation", "read")},
    "chats": {"label": "💬 Chats", "run": t_chats, "when": lambda f, p: bool({"website_chat", "whatsapp_assistant", "telegram_assistant"} & set(f["automations"]))
              and p.can("conversation", "read")},
    "calls": {"label": "📞 Calls", "run": t_calls, "when": lambda f, p: "ai_receptionist" in f["automations"] and p.can("conversation", "read")},
    "cold": {"label": "✉️ Cold email", "run": t_cold, "when": lambda f, p: "cold-email" in f["pages"] and p.can("conversation", "read")},
    "content": {"label": "🎬 Content", "run": t_content, "when": lambda f, p: "content" in f["pages"] and p.can("conversation", "read")},
    "results": {"label": "📈 Results", "run": t_results, "when": lambda f, p: p.can("dashboard", "read")},
}


async def _content_upload(chat_id: int, p: Person, m: dict) -> None:
    """A recording sent to the bot becomes a content source (only for businesses with content repurposing)."""
    from agentry.automations.content import sources
    from agentry.events import emit
    async with tenant_session(p.org_id) as conn:
        f = await org_features(conn)
    if "content_repurposing" not in f["automations"] or not p.can("automation", "configure"):
        await _say(chat_id, "I can only turn recordings into posts for businesses with content repurposing, and for owners or managers.")
        return
    item = m.get("video") or m.get("audio") or m.get("voice") or m.get("document")
    name = item.get("file_name") or ("recording.mp4" if "video" in m else "recording.ogg" if "voice" in m else "recording.mp3")
    kind = sources.kind_of(name) or ("audio" if "voice" in m else None)
    if not kind:
        await _say(chat_id, "Send a video, audio or transcript file (MP4, MOV, MP3, M4A, WAV, SRT, VTT, TXT).")
        return
    if (item.get("file_size") or 0) > 20 * 1024 * 1024:
        await _say(chat_id, f"Telegram lets bots download files up to 20 MB. Upload bigger recordings in Agentry: {link_to('/content')}")
        return
    data = await tg.download(settings.telegram_bot_token, item["file_id"])
    title = (m.get("caption") or Path(name).stem or "Recording from Telegram")[:200]
    async with tenant_session(p.org_id) as conn:
        sid = str((await conn.execute(text("""insert into app.content_sources (org_id, title, kind, created_by) values (:o, :t, :k, :u) returning id"""),
                                      {"o": p.org_id, "t": title, "k": kind, "u": p.user_id})).scalar_one())
    path = sources.folder(p.org_id, sid) / f"source{Path(name).suffix.lower() or '.ogg'}"
    path.write_bytes(data)
    transcript = sources.parse_transcript(data.decode(errors="ignore"), name) if kind == "transcript" else None
    async with tenant_session(p.org_id) as conn:
        await conn.execute(text("""update app.content_sources set file_path = :p, file_bytes = :b, transcript = cast(:t as jsonb) where id = cast(:i as uuid)"""),
                           {"p": sources.relative(path), "b": len(data), "t": json.dumps(transcript) if transcript else None, "i": sid})
        await emit(conn, p.org_id, "content.source_added", {"source_id": sid})
    await _say(chat_id, f"Got it: “{title}”. I'll message you when the posts are ready to review.\n{link_to(f'/content/{sid}')}")
