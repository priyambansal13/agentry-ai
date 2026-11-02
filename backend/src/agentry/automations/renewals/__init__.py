"""Renewals & repeat business (ROADMAP-V3 A4): reminders before things lapse, win-backs after, birthday wishes.

    renewals   customer, what renews (an AMC, a membership, a policy, a service due), due date, amount, how often; from a
               CSV / Excel or added by hand
    remind     30, 7 and 1 days before (settings), on WhatsApp / Telegram / email, with a Razorpay payment link when there's
               an amount and Razorpay is connected; each reminder once per due date
    renewed    marked in the portal (or when the link is paid): the next due date moves on by the cycle; the reminders
               start again for it
    lapsed     N days after the due date without a renewal: lapsed, one win-back message (with the offer from settings)
    birthdays  a birthday column in the sheet: a short wish on the day (no offer unless settings has one)
Nothing is sent in approval mode: the renewals page shows what's coming.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit
from agentry.automations import AutomationTemplate, register
from agentry.connectors.http import client
from agentry.connectors.store import get_connection
from agentry.db import system_session, tenant_session
from agentry.events import emit

STEP = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}


class RenewalConfig(BaseModel):
    remind_days: list[int] = Field(default_factory=lambda: [30, 7, 1], title="Remind customers this many days before",
                                   json_schema_extra={"editable_by": "client"})
    winback_after_days: int = Field(15, ge=1, le=120, title="Call it lapsed this many days after the due date", json_schema_extra={"editable_by": "client"})
    winback_offer: str | None = Field(None, title="Offer in the win-back message", description="e.g. 10% off if you renew this week",
                                      json_schema_extra={"editable_by": "client"})
    birthday_wishes: bool = Field(True, title="Send birthday wishes", json_schema_extra={"editable_by": "client"})
    birthday_offer: str | None = Field(None, title="Birthday offer (optional)", json_schema_extra={"editable_by": "client"})
    payment_links: bool = Field(True, title="Add a payment link when there's an amount (Razorpay)", json_schema_extra={"editable_by": "client"})
    whatsapp_template: str | None = Field(None, title="Approved WhatsApp template", description="One parameter: the message.",
                                          json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="renewals", name="Renewals & repeat business",
    description="Reminds customers before AMCs, memberships and services are due, with a payment link; wins back lapsed ones; birthday wishes.",
    config_model=RenewalConfig, metrics=("renewals_won",),
))


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'renewals'"))).first()
    return (row.status, RenewalConfig(**(row.config or {})).model_dump()) if row else (None, RenewalConfig().model_dump())


def next_due(d: date, every: str) -> date | None:
    if every == "once":
        return None
    import calendar
    m = d.month - 1 + STEP[every]
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


COLS = {"customer": ("customer", "name", "client"), "phone": ("phone", "mobile", "whatsapp"), "email": ("email",),
        "item": ("item", "plan", "product", "service", "what", "policy", "membership"), "due_on": ("due", "due date", "renewal date", "expiry", "expires", "next due"),
        "amount": ("amount", "price", "fee", "premium"), "every": ("every", "frequency", "cycle", "renews"), "birthday": ("birthday", "dob", "date of birth")}
EVERY = {"month": "monthly", "monthly": "monthly", "quarter": "quarterly", "quarterly": "quarterly", "half": "half_yearly", "half-yearly": "half_yearly",
         "half_yearly": "half_yearly", "6 months": "half_yearly", "year": "yearly", "yearly": "yearly", "annual": "yearly", "annually": "yearly", "once": "once"}


async def add(conn: AsyncConnection, org_id: str, d: dict) -> str:
    from agentry.leads import resolve_contact
    contact = await resolve_contact(conn, org_id, name=d["customer"], phone=d.get("phone"), email=d.get("email"), source="renewals") \
        if d.get("phone") or d.get("email") else None
    if contact and d.get("birthday"):
        await conn.execute(text("""update app.contacts set attributes = attributes || jsonb_build_object('birthday', cast(:b as text)) where id = :k"""),
                           {"b": d["birthday"], "k": contact})
    if contact and d.get("phone"):
        from agentry.leads import record_consent
        await record_consent(conn, org_id, contact, "whatsapp", True, "renewals")  # an existing customer of the business
    return str((await conn.execute(text("""insert into app.renewals (org_id, contact_id, customer, phone, email, item, due_on, amount, every, notes)
        values (:o, cast(:k as uuid), :c, :p, :e, :i, :d, :a, :ev, :n) returning id"""),
        {"o": org_id, "k": contact, "c": d["customer"][:120], "p": d.get("phone"), "e": d.get("email"), "i": d["item"][:120], "d": d["due_on"],
         "a": d.get("amount"), "ev": d.get("every") or "yearly", "n": d.get("notes")})).scalar_one())


async def import_sheet(conn: AsyncConnection, org_id: str, rows: list[list[str]]) -> dict:
    from agentry.automations.ca.core import find_col, money, parse_date
    if len(rows) < 2:
        raise ValueError("the sheet needs a header row and at least one row")
    col = {k: find_col(rows[0], *names) for k, names in COLS.items()}
    if col["customer"] is None or col["due_on"] is None:
        raise ValueError("the sheet needs a customer name column and a due date column")
    added, skipped = 0, []
    for n, r in enumerate(rows[1:], start=2):
        g = {k: (str(r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        due = parse_date(g["due_on"])
        if not g["customer"] or not due:
            skipped.append(n)
            continue
        bday = parse_date(g["birthday"]) if g["birthday"] else None
        await add(conn, org_id, {"customer": g["customer"], "phone": g["phone"] or None, "email": g["email"] or None, "item": g["item"] or "Renewal",
                                 "due_on": due, "amount": money(g["amount"]), "every": EVERY.get(g["every"].lower(), "yearly") if g["every"] else "yearly",
                                 "birthday": f"{bday:%m-%d}" if bday else None})
        added += 1
    return {"added": added, "skipped_rows": skipped[:20]}


async def _pay_link(org_id: str, r: dict) -> str | None:
    rz = await get_connection(org_id, "razorpay")
    if not rz or not r["amount"]:
        return None
    async with client() as c:
        res = await c.post("https://api.razorpay.com/v1/payment_links", auth=(rz["secret"]["key_id"], rz["secret"]["key_secret"]),
                           json={"amount": int(Decimal(str(r["amount"])) * 100), "currency": "INR", "description": f"{r['item']} renewal",
                                 "reference_id": f"ren-{str(r['id'])[:8]}-{r['due_on']:%Y%m%d}", "notes": {"renewal_id": str(r["id"]), "org_id": org_id},
                                 "customer": {k: v for k, v in {"name": r["customer"], "email": r["email"], "contact": r["phone"]}.items() if v}})
    return res.json().get("short_url") if res.status_code < 300 else None


def reminder(r: dict, left: int, business: str, link: str | None) -> str:
    first = r["customer"].split()[0]
    when = "today" if left == 0 else "tomorrow" if left == 1 else f"on {r['due_on']:%d %b}"
    amt = f" (₹{float(r['amount']):,.0f})" if r["amount"] else ""
    return (f"Hi {first}, a friendly reminder from {business}: your {r['item']}{amt} is due for renewal {when}."
            + (f" You can renew here: {link}" if link else " Reply here to renew or if you have any questions.") + "\nThank you!")


async def _who(conn: AsyncConnection, contact_id) -> dict | None:
    if not contact_id:
        return None
    w = (await conn.execute(text("""select id::text as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
        from app.contacts where id = :k"""), {"k": contact_id})).mappings().first()
    return dict(w) if w else None


async def daily(org_id: str, today: date | None = None) -> dict:
    from agentry.outbound import reach_contact
    today = today or datetime.now(UTC).date()
    out = {"reminders": 0, "lapsed": 0, "winbacks": 0, "birthdays": 0}
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode"):
            return out
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        offsets = sorted({int(x) for x in cfg["remind_days"] if 0 <= int(x) <= 120}, reverse=True)
        horizon = today + timedelta(days=max(offsets or [0]))
        lapse = today - timedelta(days=cfg["winback_after_days"])
        lapsed = (await conn.execute(text("""update app.renewals set status = 'lapsed', updated_at = now() where status = 'upcoming' and due_on <= :d
            returning id"""), {"d": lapse})).all()
        out["lapsed"] = len(lapsed)
        if status != "live":
            return out
        for r in (await conn.execute(text("select * from app.renewals where status = 'upcoming' and due_on between :t and :h"),
                                     {"t": today, "h": horizon})).mappings().all():
            left = (r["due_on"] - today).days
            off = min((o for o in offsets if left <= o), default=None)
            done = set(r["reminded"] or [])
            if off is None or off in done or (done and min(done) <= off):
                continue
            who = await _who(conn, r["contact_id"])
            if not who:
                continue
            link = r["payment_link"] or (await _pay_link(org_id, dict(r)) if cfg["payment_links"] else None)
            body = reminder(dict(r), left, business, link)
            res = await reach_contact(conn, org_id, who, body, agent="renewals", subject=f"Your {r['item']} renewal", email_ref=f"renewal:{r['id']}:{r['due_on']}",
                                      wa_template=cfg["whatsapp_template"], wa_params=[body])
            if res["status"] in ("sent", "recorded"):
                await conn.execute(text("""update app.renewals set reminded = cast(:r as jsonb), payment_link = coalesce(:l, payment_link), updated_at = now()
                    where id = :i"""), {"r": f"[{','.join(str(x) for x in sorted(done | {off}))}]", "l": link, "i": r["id"]})
                out["reminders"] += 1
        for r in (await conn.execute(text("select * from app.renewals where status = 'lapsed' and not winback_sent"))).mappings().all():
            who = await _who(conn, r["contact_id"])
            if who:
                body = (f"Hi {r['customer'].split()[0]}, we noticed your {r['item']} with {business} lapsed on {r['due_on']:%d %b}. "
                        f"We'd love to have you back.{(' ' + cfg['winback_offer']) if cfg['winback_offer'] else ''} Reply here and we'll sort it out.")
                await reach_contact(conn, org_id, who, body, agent="renewals", subject=f"Your {r['item']}", email_ref=f"renewal-winback:{r['id']}",
                                    wa_template=cfg["whatsapp_template"], wa_params=[body])
                out["winbacks"] += 1
            await conn.execute(text("update app.renewals set winback_sent = true where id = :i"), {"i": r["id"]})
        if cfg["birthday_wishes"]:
            mmdd = f"{today:%m-%d}"
            for k in (await conn.execute(text("""select id::text as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
                from app.contacts where attributes->>'birthday' = :b and coalesce(attributes->>'wished', '') <> :y"""), {"b": mmdd, "y": str(today.year)})).mappings().all():
                body = (f"Happy birthday, {(k['contact_name'] or 'there').split()[0]}! Warm wishes from all of us at {business}."
                        f"{(' ' + cfg['birthday_offer']) if cfg['birthday_offer'] else ''}")
                await reach_contact(conn, org_id, dict(k), body, agent="renewals", subject=f"Happy birthday from {business}", email_ref=f"bday:{k['contact_id']}:{today.year}",
                                    wa_template=cfg["whatsapp_template"], wa_params=[body])
                await conn.execute(text("update app.contacts set attributes = attributes || jsonb_build_object('wished', cast(:y as text)) where id = cast(:k as uuid)"),
                                   {"y": str(today.year), "k": k["contact_id"]})
                out["birthdays"] += 1
    return out


async def mark(conn: AsyncConnection, org_id: str, rid: str, action: str, user_id: str | None) -> dict:
    r = (await conn.execute(text("select * from app.renewals where id = cast(:i as uuid) for update"), {"i": rid})).mappings().first()
    if not r:
        raise ValueError("not found")
    if action == "renewed":
        nxt = next_due(r["due_on"], r["every"])
        if nxt:
            await conn.execute(text("""update app.renewals set due_on = :d, status = 'upcoming', reminded = '[]', winback_sent = false, payment_link = null,
                renewals = renewals + 1, updated_at = now() where id = :i"""), {"d": nxt, "i": r["id"]})
        else:
            await conn.execute(text("update app.renewals set status = 'renewed', renewals = renewals + 1, updated_at = now() where id = :i"), {"i": r["id"]})
        await emit(conn, org_id, "renewal.won", {"renewal_id": rid, "amount": float(r["amount"] or 0), "item": r["item"]})
    elif action == "cancelled":
        await conn.execute(text("update app.renewals set status = 'cancelled', updated_at = now() where id = :i"), {"i": r["id"]})
    else:
        raise ValueError("renewed or cancelled")
    await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"renewal.{action}", target_type="renewal", target_id=rid)
    return {"id": rid, "action": action}


async def renewal_paid(org_id: str, renewal_id: str) -> None:
    """A Razorpay payment for a renewal's link (webhook notes.renewal_id)."""
    async with tenant_session(org_id) as conn:
        await mark(conn, org_id, renewal_id, "renewed", None)


async def renewal_jobs() -> dict:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'renewals'
            and status in ('live','approval_mode')"""))).scalars())
    tot = {"reminders": 0, "lapsed": 0, "winbacks": 0, "birthdays": 0}
    for o in orgs:
        for k, v in (await daily(o)).items():
            tot[k] += v
    return tot


@DBOS.step()
async def renewal_jobs_step() -> dict:
    return await renewal_jobs()


@DBOS.workflow()
async def renewal_schedule(scheduled_time: datetime, context) -> None:
    await renewal_jobs_step()

