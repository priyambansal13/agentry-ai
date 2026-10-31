"""Appointment Concierge (ROADMAP-V2 9.3): fewer no-shows, full diaries.

    booked      -> reminder the evening before ("reply 1 to confirm, 2 to change"), a short note on the day
    reply 1     -> confirmed
    reply 2     -> the next 3 free times; the customer picks A/B/C (or 0 to cancel) and is rebooked
    cancelled   -> the slot is offered to the waitlist; the first "yes" gets it
    showed      -> an aftercare message (optional); a recall after N months ("time for your next cleaning")
    no-show     -> "we missed you", with new times to pick

Channels, per customer: WhatsApp (a template outside the 24-hour window), else Telegram (if they've used the business's
bot), else email from the business's mailbox, else a card asking the team to call. Every message the business starts
goes through governance (quiet hours, daily limit); replies to the customer don't.
"""
import json
import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import governance
from agentry.automations import AutomationTemplate, register
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.outbound import reach_contact
from agentry.worker.handlers import on

MAX_SLEEP = 86400
YES = re.compile(r"^\s*(1|yes|yeah|yep|confirm(ed)?|ok(ay)?|sure|👍|haan?|ha|ji)\b", re.IGNORECASE)
CHANGE = re.compile(r"^\s*(2|change|reschedule|another time|can'?t make it|cancel)\b", re.IGNORECASE)
CANCEL = re.compile(r"^\s*(0|cancel)\b", re.IGNORECASE)
PICK = re.compile(r"^\s*([abc])\s*[).]?\s*$", re.IGNORECASE)


class ConciergeConfig(BaseModel):
    reminder_hour: int = Field(18, ge=8, le=20, title="Evening-before reminder at (hour)", json_schema_extra={"editable_by": "client"})
    day_of_reminder: bool = Field(True, title="Also a short note 2 hours before", json_schema_extra={"editable_by": "client"})
    aftercare_text: str | None = Field(None, title="Aftercare message after a visit (optional)",
                                       description="e.g. 'Avoid hot drinks for 2 hours. Any pain, just reply here.'",
                                       json_schema_extra={"editable_by": "client"})
    recall_months: int = Field(6, ge=0, le=24, title="Recall after (months; 0 = off)", json_schema_extra={"editable_by": "client"})
    whatsapp_template: str | None = Field(None, title="Approved WhatsApp template for reminders",
                                          description="Body variables: name, service, time. Needed outside WhatsApp's 24-hour window.",
                                          json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="appointment_concierge",
    name="Appointment concierge",
    description="Reminds, confirms and reschedules appointments by WhatsApp, Telegram or email, fills cancellations from a waitlist, and recalls patients.",
    config_model=ConciergeConfig,
    metrics=("appointments_booked",),
))
governance.ACTIONS["appointment_concierge.send"] = governance.Action(
    "Send appointment reminders and recalls", "appointment_concierge", "outbound_draft", True, {"max_per_day": 300, "quiet_hours": True})


# ---------- reading ----------

BOOKING_SQL = """select b.*, s.key as service_key, s.name as service, st.name as staff, k.name as contact_name, k.phone_e164, k.email,
    k.attributes->>'telegram_id' as telegram_id, o.timezone, o.org_id as org from app.bookings b join app.services s on s.id = b.service_id
    join app.staff st on st.id = b.staff_id left join app.contacts k on k.id = b.contact_id join app.org_settings o on o.org_id = b.org_id"""


async def load(conn: AsyncConnection, booking_id: str) -> dict | None:
    row = (await conn.execute(text(BOOKING_SQL + " where b.id = cast(:i as uuid)"), {"i": booking_id})).mappings().first()
    return dict(row) if row else None


async def config(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'appointment_concierge'"))).first()
    return (row.status, ConciergeConfig(**(row.config or {})).model_dump()) if row else (None, ConciergeConfig().model_dump())


def when(dt: datetime, tz: str, with_day: bool = True) -> str:
    local = dt.astimezone(ZoneInfo(tz or "Asia/Kolkata"))
    clock = local.strftime("%I:%M %p").lstrip("0")
    return f"{local.strftime('%a %d %b')} at {clock}" if with_day else clock


def first(name: str | None) -> str:
    return (name or "there").split()[0]


async def set_state(conn: AsyncConnection, booking_id: str, **state: object) -> None:
    await conn.execute(text("update app.bookings set concierge = concierge || cast(:s as jsonb) where id = cast(:i as uuid)"),
                       {"s": json.dumps(state, default=str), "i": booking_id})


# ---------- reaching a customer ----------

async def reach(conn: AsyncConnection, org_id: str, b: dict, body: str, *, cfg: dict, reply: bool = False, approved: bool = False) -> dict:
    """Send `body` to the booking's customer on the best channel they have. reply=True: answering them (no governance);
    approved=True: a person approved this message on a card."""
    if not reply and not approved:
        d = await governance.decide(conn, org_id, "appointment_concierge.send")
        if d.mode == "shadow":
            return {"status": "shadow", "would_send": body}
        if d.mode == "card":
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
                values (:o, 'outbound_draft', 'appointment_concierge', :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "t": f"Message {b['contact_name'] or 'customer'} about their {b['service']}", "b": body,
                 "p": json.dumps({"concierge_booking": str(b["id"]), **({"to_contact": str(b["contact_id"])} if b.get("waitlist") else {}),
                                  **({"held_because": d.reason} if d.reason else {})})})
            return {"status": "awaiting_approval", "reason": d.reason}
    params = [first(b["contact_name"]), b.get("service") or "", when(b["starts_at"], b["timezone"])] if b.get("starts_at") else None
    r = await reach_contact(conn, org_id, b, body, agent="appointment_concierge", subject=f"Your {b.get('service') or 'appointment'} appointment",
                            email_ref=f"appt:{b['contact_id']}", wa_template=cfg.get("whatsapp_template"), wa_params=params)
    if r["status"] != "no_channel":
        return r
    if not reply:  # no way to message them: a person calls
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
            values (:o, 'handoff', 'appointment_concierge', :t, :b, cast(:p as jsonb))"""),
            {"o": org_id, "t": f"Call {b['contact_name'] or 'the customer'} about their {b['service']}", "b": body,
             "p": json.dumps({"phone": b.get("phone_e164"), "concierge_booking": str(b["id"])})})
        return {"status": "call_needed"}
    return {"status": "no_channel"}


async def deliver_approved(conn: AsyncConnection, org_id: str, approval: dict) -> dict:
    """A person approved (maybe edited) a concierge message on a Needs-you card: send it to whoever it was for."""
    p = approval["payload"]
    b = await load(conn, p["concierge_booking"])
    if not b:
        return {"status": "skipped", "reason": "appointment not found"}
    if p.get("to_contact"):  # a waitlist offer: the booking is the freed slot, the message is for someone else
        k = (await conn.execute(text("""select id as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
            from app.contacts where id = cast(:k as uuid)"""), {"k": p["to_contact"]})).mappings().one()
        b = {**b, **dict(k)}
    _status, cfg = await config(conn)
    return await reach(conn, org_id, b, approval["body"], cfg=cfg, approved=True)


# ---------- the booking's journey ----------

def reminder_time(starts_at: datetime, tz: str, hour: int, now: datetime) -> datetime | None:
    """The evening before at `hour`; for bookings made too late for that, none (they just booked: no need)."""
    zone = ZoneInfo(tz or "Asia/Kolkata")
    day_before = starts_at.astimezone(zone).date() - timedelta(days=1)
    at = datetime.combine(day_before, time(hour), tzinfo=zone).astimezone(UTC)
    return at if at > now else None


@DBOS.step()
async def appt_send(org_id: str, booking_id: str, kind: str) -> str:
    async with tenant_session(org_id) as conn:
        b = await load(conn, booking_id)
        status, cfg = await config(conn)
        if not b or status not in ("live", "approval_mode") or b["status"] not in ("booked", "confirmed"):
            return "skipped"
        if kind == "reminder" and b["status"] == "booked":
            body = (f"Hi {first(b['contact_name'])}, a reminder: your {b['service']} is {when(b['starts_at'], b['timezone'])}"
                    f"{' with ' + b['staff'] if b['staff'] else ''}. Reply 1 to confirm or 2 to change the time.")
            r = await reach(conn, org_id, b, body, cfg=cfg)
            await set_state(conn, booking_id, reminded_at=datetime.now(UTC).isoformat(), awaiting="confirm", reminder=r.get("status"))
        elif kind == "day_of" and cfg["day_of_reminder"]:
            r = await reach(conn, org_id, b, f"See you at {when(b['starts_at'], b['timezone'], with_day=False)} today, {first(b['contact_name'])}.", cfg=cfg)
            await set_state(conn, booking_id, day_of_at=datetime.now(UTC).isoformat())
        else:
            return "skipped"
    return r.get("status", "skipped")


async def _sleep_until(target: datetime) -> None:
    while (left := (target - datetime.now(UTC)).total_seconds()) > 1:
        await DBOS.sleep_async(min(left, MAX_SLEEP))


@DBOS.step()
async def appt_plan(org_id: str, booking_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        b = await load(conn, booking_id)
        status, cfg = await config(conn)
    if not b or status not in ("live", "approval_mode"):
        return {}
    now = datetime.now(UTC)
    rem = reminder_time(b["starts_at"], b["timezone"], cfg["reminder_hour"], now)
    day_of = b["starts_at"] - timedelta(hours=2)
    return {"reminder": rem.isoformat() if rem else None, "day_of": day_of.isoformat() if day_of > now else None,
            "after": (b["ends_at"] + timedelta(hours=2)).isoformat()}


@DBOS.step()
async def appt_aftercare(org_id: str, booking_id: str) -> str:
    async with tenant_session(org_id) as conn:
        b = await load(conn, booking_id)
        _status, cfg = await config(conn)
        if not b or b["status"] != "showed" or not cfg.get("aftercare_text") or b["concierge"].get("aftercare_at"):
            return "skipped"
        r = await reach(conn, org_id, b, f"Hi {first(b['contact_name'])}, thanks for coming in today. {cfg['aftercare_text']}", cfg=cfg)
        await set_state(conn, booking_id, aftercare_at=datetime.now(UTC).isoformat())
    return r.get("status", "skipped")


@on("booking.created")
@DBOS.workflow()
async def concierge_booking(event: dict) -> None:
    org_id, bid = event["org_id"], event["payload"]["booking_id"]
    plan = await appt_plan(org_id, bid)
    if not plan:
        return
    if plan["reminder"]:
        await _sleep_until(datetime.fromisoformat(plan["reminder"]))
        await appt_send(org_id, bid, "reminder")
    if plan["day_of"]:
        await _sleep_until(datetime.fromisoformat(plan["day_of"]))
        await appt_send(org_id, bid, "day_of")
    await _sleep_until(datetime.fromisoformat(plan["after"]))
    await appt_aftercare(org_id, bid)


# ---------- replies ----------

async def free_times(org_id: str, service_key: str, after: datetime, n: int = 3) -> list[dict]:
    from agentry.booking import availability
    slots, tz, _svc = await availability(org_id, service_key, after.astimezone(UTC).date(), days=14, limit=200)
    picks, seen = [], set()
    for s in slots:
        if s.start <= after or s.start in seen:
            continue
        seen.add(s.start)
        picks.append({"start": s.start.isoformat(), "label": s.label(tz)})
        if len(picks) == n:
            break
    return picks


async def _offer(conn, org_id: str, b: dict, cfg: dict, lead_in: str) -> dict:
    times = await free_times(org_id, b["service_key"], max(datetime.now(UTC) + timedelta(hours=2), b["starts_at"] if b["status"] == "no_show" else datetime.now(UTC)))
    if not times:
        await reach(conn, org_id, b, f"{lead_in} We don't have a free time in the next two weeks; we'll call you to arrange one.", cfg=cfg, reply=True)
        await set_state(conn, str(b["id"]), awaiting=None)
        return {"handled": True, "action": "no_times"}
    lines = "\n".join(f"{'ABC'[i]}) {t['label']}" for i, t in enumerate(times))
    await reach(conn, org_id, b, f"{lead_in} Which suits you?\n{lines}\nReply A, B or C (or 0 to cancel).", cfg=cfg, reply=True)
    await set_state(conn, str(b["id"]), awaiting="pick_slot", offered=[t["start"] for t in times])
    return {"handled": True, "action": "offered_times"}


async def handle_reply(org_id: str, conversation_id: str, body: str) -> dict:
    """A customer replied on WhatsApp / Telegram. Returns {"handled": True, ...} when it was about an appointment."""
    async with tenant_session(org_id) as conn:
        status, cfg = await config(conn)
        if status not in ("live", "approval_mode"):
            return {"handled": False}
        contact = (await conn.execute(text("select contact_id from app.conversations where id = cast(:c as uuid)"), {"c": conversation_id})).scalar_one_or_none()
        if not contact:
            return {"handled": False}
        offer = (await conn.execute(text("""select w.*, s.key as service_key, s.name as service from app.waitlist w join app.services s on s.id = w.service_id
            where w.contact_id = :k and w.status = 'offered' order by w.created_at limit 1"""), {"k": contact})).mappings().first()
        if offer and YES.match(body):
            return await _take_offer(conn, org_id, dict(offer), conversation_id)
        row = (await conn.execute(text(BOOKING_SQL + """ where b.contact_id = :k and b.concierge ? 'awaiting' and b.concierge->>'awaiting' is not null
            and (b.starts_at > now() - interval '1 day' or b.status in ('no_show','showed')) order by b.starts_at desc limit 1"""), {"k": contact})).mappings().first()
        if not row:
            return {"handled": False}
        b = dict(row)
        awaiting = b["concierge"].get("awaiting")
        if awaiting == "confirm":
            if YES.match(body):
                await conn.execute(text("update app.bookings set status = 'confirmed' where id = :i"), {"i": b["id"]})
                await set_state(conn, str(b["id"]), awaiting=None, confirmed_at=datetime.now(UTC).isoformat())
                await emit(conn, org_id, "booking.confirmed", {"booking_id": str(b["id"])})
                await reach(conn, org_id, b, f"Thanks {first(b['contact_name'])}, see you {when(b['starts_at'], b['timezone'])}.", cfg=cfg, reply=True)
                return {"handled": True, "action": "confirmed"}
            if CHANGE.match(body):
                return await _offer(conn, org_id, b, cfg, "No problem.")
            return {"handled": False}
        if awaiting in ("rebook",) and (YES.match(body) or CHANGE.match(body)):
            return await _offer(conn, org_id, b, cfg, "Great.")
        if awaiting == "pick_slot":
            if CANCEL.match(body):
                if b["status"] in ("booked", "confirmed"):
                    await cancel(conn, org_id, str(b["id"]), "cancelled by the customer")
                await set_state(conn, str(b["id"]), awaiting=None)
                await reach(conn, org_id, b, "Done: your appointment is cancelled. Reply any time to book again.", cfg=cfg, reply=True)
                return {"handled": True, "action": "cancelled"}
            m = PICK.match(body)
            offered = b["concierge"].get("offered") or []
            if not m or "ABC".index(m[1].upper()) >= len(offered):
                return {"handled": False}
            return await _rebook(conn, org_id, b, cfg, datetime.fromisoformat(offered["ABC".index(m[1].upper())]), conversation_id)
    return {"handled": False}


@DBOS.step()
async def concierge_reply(org_id: str, conversation_id: str, body: str) -> bool:
    """For the WhatsApp / Telegram assistants: True when the concierge answered (an appointment reply), so they don't."""
    return bool(body) and (await handle_reply(org_id, conversation_id, body)).get("handled", False)


async def _rebook(conn, org_id: str, b: dict, cfg: dict, start: datetime, conversation_id: str) -> dict:
    from agentry.booking import BookingError, book
    try:
        new = await book(org_id, service_key=b["service_key"], start=start, name=b["contact_name"] or "Customer", phone=b.get("phone_e164"),
                         email=b.get("email"), source="concierge", conversation_id=conversation_id, lead_id=str(b["lead_id"]) if b.get("lead_id") else None)
    except BookingError:
        return await _offer(conn, org_id, b, cfg, "Sorry, that time was just taken.")
    if b["status"] in ("booked", "confirmed"):
        await cancel(conn, org_id, str(b["id"]), "rescheduled")
    await set_state(conn, str(b["id"]), awaiting=None, rebooked_as=new["booking_id"])
    await conn.execute(text("update app.bookings set status = 'confirmed' where id = cast(:i as uuid)"), {"i": new["booking_id"]})
    await reach(conn, org_id, b, f"You're booked: {b['service']}, {new['when']}. See you then.", cfg=cfg, reply=True)
    return {"handled": True, "action": "rebooked", "booking_id": new["booking_id"]}


async def cancel(conn, org_id: str, booking_id: str, reason: str) -> None:
    """Cancel, tell the team (booking.cancelled) and offer the freed slot to the waitlist."""
    b = await load(conn, booking_id)
    await conn.execute(text("update app.bookings set status = 'cancelled', cancel_reason = :r where id = cast(:i as uuid)"), {"r": reason, "i": booking_id})
    await emit(conn, org_id, "booking.cancelled", {"booking_id": booking_id, "reason": reason})
    if b and b["starts_at"] > datetime.now(UTC) + timedelta(hours=2):
        await offer_to_waitlist(conn, org_id, b)


async def offer_to_waitlist(conn, org_id: str, b: dict, n: int = 3) -> int:
    status, cfg = await config(conn)
    if status not in ("live", "approval_mode"):
        return 0
    waiting = (await conn.execute(text("""select w.id, w.contact_id, k.name as contact_name, k.phone_e164, k.email, k.attributes->>'telegram_id' as telegram_id
        from app.waitlist w join app.contacts k on k.id = w.contact_id where w.service_id = :s and w.status = 'waiting' order by w.created_at limit :n"""),
        {"s": b["service_id"], "n": n})).mappings().all()
    for w in waiting:
        target = {**b, "contact_id": w["contact_id"], "contact_name": w["contact_name"], "phone_e164": w["phone_e164"], "email": w["email"],
                  "telegram_id": w["telegram_id"], "waitlist": True}
        await conn.execute(text("update app.waitlist set status = 'offered', offered = cast(:o as jsonb) where id = :i"),
                           {"o": json.dumps({"starts_at": b["starts_at"].isoformat(), "booking_id": str(b["id"]), "at": datetime.now(UTC).isoformat()}),
                            "i": w["id"]})
        await reach(conn, org_id, target, f"Hi {first(w['contact_name'])}, a {b['service']} slot just opened: {when(b['starts_at'], b['timezone'])}. "
                                          "Reply YES to take it (first come, first served).", cfg=cfg)
    return len(waiting)


async def _take_offer(conn, org_id: str, w: dict, conversation_id: str) -> dict:
    from agentry.booking import BookingError, book
    _status, cfg = await config(conn)
    contact = (await conn.execute(text("select name, phone_e164, email from app.contacts where id = :k"), {"k": w["contact_id"]})).mappings().one()
    start = datetime.fromisoformat(w["offered"]["starts_at"])
    target = {"id": w["offered"]["booking_id"], "service": w["service"], "contact_id": w["contact_id"], "contact_name": contact["name"],
              "phone_e164": contact["phone_e164"], "email": contact["email"], "telegram_id": None, "starts_at": start, "timezone": None}
    try:
        new = await book(org_id, service_key=w["service_key"], start=start, name=contact["name"] or "Customer", phone=contact["phone_e164"],
                         email=contact["email"], source="waitlist", conversation_id=conversation_id)
    except BookingError:
        await conn.execute(text("update app.waitlist set status = 'waiting', offered = null where id = :i"), {"i": w["id"]})
        await reach(conn, org_id, target, "Sorry, someone took that slot a moment ago. You're still on the waitlist.", cfg=cfg, reply=True)
        return {"handled": True, "action": "offer_taken"}
    await conn.execute(text("update app.waitlist set status = 'booked' where id = :i"), {"i": w["id"]})
    await conn.execute(text("""update app.waitlist set status = 'waiting', offered = null where status = 'offered' and offered->>'booking_id' = :b and id <> :i"""),
                       {"b": w["offered"]["booking_id"], "i": w["id"]})
    await reach(conn, org_id, target, f"It's yours: {w['service']}, {new['when']}. See you then.", cfg=cfg, reply=True)
    return {"handled": True, "action": "waitlist_booked", "booking_id": new["booking_id"]}


# ---------- after the visit ----------

async def mark(org_id: str, booking_id: str, status: str, user_id: str | None = None) -> dict:
    """The team marks attendance (or cancels). No-show: a "we missed you" with new times."""
    async with tenant_session(org_id) as conn:
        b = await load(conn, booking_id)
        if not b:
            raise ValueError("booking not found")
        if status == "cancelled":
            await cancel(conn, org_id, booking_id, "cancelled by the team")
            return {"status": "cancelled"}
        await conn.execute(text("update app.bookings set status = :s where id = cast(:i as uuid)"), {"s": status, "i": booking_id})
        if status == "showed" and b["status"] != "showed":
            await emit(conn, org_id, "booking.showed", {"booking_id": booking_id})  # e.g. review management asks for a review
        if status == "no_show":
            await emit(conn, org_id, "booking.no_show", {"booking_id": booking_id})
            st, cfg = await config(conn)
            if st in ("live", "approval_mode") and not b["concierge"].get("no_show_followup_at"):
                b["status"] = "no_show"
                r = await reach(conn, org_id, b, f"Hi {first(b['contact_name'])}, we missed you today. Reply 1 and we'll find you a new time.", cfg=cfg)
                await set_state(conn, booking_id, no_show_followup_at=datetime.now(UTC).isoformat(), awaiting="rebook", followup=r.get("status"))
    return {"status": status}


async def recalls(now: datetime | None = None) -> int:
    """Daily: visits N months ago (per business) with nothing booked since get a "time for your next visit"."""
    now = now or datetime.now(UTC)
    async with system_session() as conn:
        rows = (await conn.execute(text("""select b.org_id, b.id::text, coalesce((a.config->>'recall_months')::int, 6) as months
            from app.bookings b join app.automation_instances a on a.org_id = b.org_id and a.template_key = 'appointment_concierge'
            where a.status in ('live','approval_mode') and b.status = 'showed' and not (b.concierge ? 'recall_sent_at')
              and coalesce((a.config->>'recall_months')::int, 6) > 0
              and b.starts_at < :n - make_interval(months => coalesce((a.config->>'recall_months')::int, 6))
              and not exists (select 1 from app.bookings later where later.contact_id = b.contact_id and later.starts_at > b.starts_at
                              and later.status <> 'cancelled')"""), {"n": now})).all()
    for org_id, bid, months in rows:
        async with tenant_session(org_id) as conn:
            b = await load(conn, bid)
            _st, cfg = await config(conn)
            r = await reach(conn, org_id, b, f"Hi {first(b['contact_name'])}, it's been {months} months since your {b['service']}. "
                                             "Reply 1 and we'll find you a time.", cfg=cfg)
            await set_state(conn, bid, recall_sent_at=now.isoformat(), awaiting="rebook", recall=r.get("status"))
    return len(rows)


@DBOS.step()
async def recalls_step() -> int:
    return await recalls()


@DBOS.workflow()
async def send_recalls(scheduled_time: datetime, context) -> None:
    await recalls_step()
