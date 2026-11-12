"""Missed-call recovery (docs/PLAN-COMMERCIAL-2026-11.md #2): every missed call gets a WhatsApp within a minute, and the
WhatsApp assistant takes it from there.

    hook      the business's phone system (Exotel, MyOperator, Knowlarity, TATA Tele, Airtel IQ, any IVR that can call a URL)
              posts each call to /hooks/calls/{key}: JSON or form, the common field names understood. Answered calls are
              ignored; missed / no-answer / busy / unanswered ones are recorded.
    wait      the message goes after `delay_seconds` (they may call back first), and at opening time when the call came
              during quiet hours
    send      once per caller per day, never to the business's own numbers or to anyone who opted out, only when the business
              has confirmed callers are told they'll get a WhatsApp (that's the caller's consent to this one service
              message). WhatsApp free text inside the 24-hour window, else the approved template.
    results   replies (the assistant answers and books) and bookings within `attribution_days` are counted against the
              missed call: missed, messaged, replied, booked.
"""
import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.automations import AutomationTemplate, register
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.worker.handlers import on

MISSED = re.compile(r"no.?answer|not.?answered|unanswered|missed|busy|cancel|abandon|failed|no.?response|voicemail|declined|rejected", re.IGNORECASE)
ANSWERED = re.compile(r"^(completed|answered|connected|success|in.?progress|ringing)$", re.IGNORECASE)
FROM = ("From", "CallFrom", "caller", "caller_id", "callerid", "caller_number", "customer_number", "msisdn", "from", "CallerNumber", "customer")
TO = ("To", "CallTo", "called", "called_number", "did", "DialWhomNumber", "to", "virtual_number", "business_number")
STATUS = ("Status", "CallStatus", "DialCallStatus", "call_status", "status", "event", "callType", "call_type", "type", "disposition")


class MissedCallConfig(BaseModel):
    callers_informed: bool = Field(False, title="Callers are told they'll get a WhatsApp when you miss their call",
                                   description="On your IVR greeting or website (\"missed us? we'll WhatsApp you\"). Nothing is sent until this is on.",
                                   json_schema_extra={"editable_by": "client"})
    delay_seconds: int = Field(60, ge=0, le=900, title="Send the WhatsApp after (seconds)", json_schema_extra={"editable_by": "client"})
    message: str = Field("Hi, this is {business}. Sorry we missed your call! How can we help? Reply here and we'll take care of it.",
                         max_length=500, title="Message (inside WhatsApp's 24-hour window)", json_schema_extra={"editable_by": "client"})
    whatsapp_template: str | None = Field(None, title="Approved WhatsApp template for the first message",
                                          description="One parameter: your business name.", json_schema_extra={"editable_by": "agentry"})
    skip_numbers: list[str] = Field(default_factory=list, title="Never message these numbers (staff, suppliers)", json_schema_extra={"editable_by": "client"})
    attribution_days: int = Field(7, ge=1, le=30, title="Count a booking as recovered within (days)", json_schema_extra={"editable_by": "client"})
    hook_key: str | None = Field(None, title="Webhook key", json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="missed_call_recovery", name="Missed-call recovery",
    description="Every missed call gets a WhatsApp within a minute; replies go to your WhatsApp assistant, which answers and books.",
    config_model=MissedCallConfig, metrics=("missed_calls", "missed_calls_recovered"),
))


def pick(data: dict, names: tuple[str, ...]) -> str:
    low = {k.lower(): v for k, v in data.items()}
    for n in names:
        v = data.get(n, low.get(n.lower()))
        if v not in (None, ""):
            return str(v).strip()[:80]
    return ""


def is_missed(data: dict) -> bool:
    if str(data.get("missed", "")).lower() in ("1", "true", "yes"):
        return True
    st = pick(data, STATUS)
    return bool(st) and not ANSWERED.match(st) and bool(MISSED.search(st))


async def ensure_key(org_id: str) -> str:
    async with tenant_session(org_id) as conn:
        cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'missed_call_recovery'"))).scalar_one_or_none()
        if cfg is None:
            raise LookupError("missed-call recovery isn't switched on")
        if cfg.get("hook_key"):
            return cfg["hook_key"]
        key = "mc_" + secrets.token_urlsafe(18)
        await conn.execute(text("""update app.automation_instances set config = config || jsonb_build_object('hook_key', cast(:k as text))
            where template_key = 'missed_call_recovery'"""), {"k": key})
        return key


async def receive(key: str, data: dict) -> dict:
    """A call from the phone system. Returns what was done with it."""
    from agentry.leads import normalize_phone, resolve_contact
    async with system_session() as conn:
        org = (await conn.execute(text("""select org_id from app.automation_instances where template_key = 'missed_call_recovery'
            and config->>'hook_key' = :k"""), {"k": key})).scalar_one_or_none()
    if not org:
        raise LookupError("unknown key")
    if not is_missed(data):
        return {"recorded": False, "reason": "answered or not a missed call"}
    caller = normalize_phone(pick(data, FROM))
    if not caller:
        return {"recorded": False, "reason": "no caller number"}
    async with tenant_session(org) as conn:
        contact = await resolve_contact(conn, org, phone=caller, source="missed_call")
        mid = str((await conn.execute(text("""insert into app.missed_calls (org_id, caller, called, status, provider, contact_id, raw)
            values (:o, :c, :t, :s, :p, cast(:k as uuid), cast(:r as jsonb)) returning id"""),
            {"o": org, "c": caller, "t": normalize_phone(pick(data, TO)) or pick(data, TO) or None, "s": pick(data, STATUS) or "missed",
             "p": str(data.get("provider") or "")[:40] or None, "k": str(contact), "r": json.dumps({k: str(v)[:200] for k, v in list(data.items())[:40]})})).scalar_one())
        await emit(conn, org, "call.missed", {"missed_call_id": mid, "contact_id": str(contact)})
    return {"recorded": True, "id": mid}


@DBOS.step()
async def missed_call_plan_step(org_id: str, mid: str) -> dict:
    """How long to wait: the delay, then (if it lands in quiet hours) until they end."""
    from agentry.automations.inbox_triage.config import TriageConfig
    from agentry.automations.inbox_triage.escalation import seconds_until_quiet_end
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select s.timezone, a.config, t.config as triage from app.org_settings s
            join app.automation_instances a on a.template_key = 'missed_call_recovery'
            left join app.automation_instances t on t.template_key = 'inbox_triage'"""))).mappings().one()
    cfg = MissedCallConfig(**(row["config"] or {}))
    quiet = list(TriageConfig(**(row["triage"] or {})).quiet_hours)
    later = datetime.now(UTC) + timedelta(seconds=cfg.delay_seconds)
    from zoneinfo import ZoneInfo
    extra = seconds_until_quiet_end(row["timezone"] or "Asia/Kolkata", quiet, later.astimezone(ZoneInfo(row["timezone"] or "Asia/Kolkata")))
    return {"wait": cfg.delay_seconds + extra}


@DBOS.step()
async def missed_call_send_step(org_id: str, mid: str) -> str:
    from agentry.leads import record_consent
    from agentry.outbound import reach_contact
    async with tenant_session(org_id) as conn:
        call = (await conn.execute(text("select * from app.missed_calls where id = cast(:i as uuid)"), {"i": mid})).mappings().one()
        row = (await conn.execute(text("""select a.status, a.config, o.name from app.automation_instances a, app.org_settings s
            join auth.organization o on o.id = s.org_id where a.template_key = 'missed_call_recovery'"""))).mappings().one()
        cfg = MissedCallConfig(**(row["config"] or {}))

        async def skip(reason: str) -> str:
            await conn.execute(text("update app.missed_calls set outcome = 'skipped', skip_reason = :r where id = :i"), {"r": reason, "i": call["id"]})
            return reason
        if row["status"] not in ("live", "approval_mode"):
            return await skip("the agent isn't live")
        if not cfg.callers_informed:
            return await skip("callers aren't told they'll get a WhatsApp yet (setting)")
        digits = re.sub(r"\D", "", call["caller"])[-10:]
        if any(re.sub(r"\D", "", n)[-10:] == digits for n in cfg.skip_numbers):
            return await skip("one of your own numbers")
        consent = (await conn.execute(text("select status from app.consents where contact_id = :c and channel = 'whatsapp'"),
                                      {"c": call["contact_id"]})).scalar_one_or_none()
        if consent == "revoked":
            return await skip("opted out of WhatsApp")
        if (await conn.execute(text("""select 1 from app.missed_calls where caller = :c and outcome = 'sent' and sent_at > now() - interval '24 hours'"""),
                               {"c": call["caller"]})).first():
            return await skip("already messaged today")
        if (await conn.execute(text("""select 1 from app.messages m join app.conversations c on c.id = m.conversation_id
            where c.contact_id = :k and m.direction = 'in' and m.created_at > :at"""), {"k": call["contact_id"], "at": call["at"]})).first():
            return await skip("they wrote to you already")
        if consent is None:  # told on the IVR / website: the missed call is their request for this message
            await record_consent(conn, org_id, str(call["contact_id"]), "whatsapp", True, source="missed_call")
        who = {"contact_id": str(call["contact_id"]), "contact_name": None, "phone_e164": call["caller"], "email": None, "telegram_id": None}
        res = await reach_contact(conn, org_id, who, cfg.message.replace("{business}", row["name"]), agent="missed_call_recovery",
                                  subject="Sorry we missed your call", email_ref=f"missed:{mid}", wa_template=cfg.whatsapp_template, wa_params=[row["name"]])
        if res["status"] != "sent":
            await conn.execute(text("update app.missed_calls set outcome = 'failed', skip_reason = :r where id = :i"),
                               {"r": "WhatsApp isn't connected or the template isn't approved yet" if res["status"] == "no_channel" else res["status"], "i": call["id"]})
            return "failed"
        await conn.execute(text("""update app.missed_calls set outcome = 'sent', sent_at = now(), conversation_id = cast(:c as uuid) where id = :i"""),
                           {"c": res.get("conversation_id"), "i": call["id"]})
        await emit(conn, org_id, "missed_call.messaged", {"missed_call_id": mid})
    return "sent"


@on("call.missed")
@DBOS.workflow()
async def missed_call_flow(event: dict) -> None:
    plan = await missed_call_plan_step(event["org_id"], event["payload"]["missed_call_id"])
    if plan["wait"] > 0:
        await DBOS.sleep_async(min(plan["wait"], 16 * 3600))
    await missed_call_send_step(event["org_id"], event["payload"]["missed_call_id"])


async def _attribute(org_id: str, contact_id: str | None, column: str, extra: dict) -> None:
    if not contact_id:
        return
    async with tenant_session(org_id) as conn:
        days = (await conn.execute(text("select coalesce((config->>'attribution_days')::int, 7) from app.automation_instances where template_key = 'missed_call_recovery'"))).scalar_one_or_none()
        if days is None:
            return
        sets = ", ".join(f"{k} = cast(:{k} as uuid)" for k in extra)
        n = (await conn.execute(text(f"""update app.missed_calls set {column} = now(){', ' + sets if sets else ''}
            where id = (select id from app.missed_calls where contact_id = cast(:c as uuid) and outcome = 'sent' and {column} is null
                        and at > now() - make_interval(days => :d) order by at desc limit 1) returning id"""),
            {"c": contact_id, "d": days, **extra})).first()
        if n and column == "booked_at":
            await emit(conn, org_id, "missed_call.recovered", {"missed_call_id": str(n.id), "booking_id": extra.get("booking_id")})


@DBOS.step()
async def missed_reply_step(org_id: str, conversation_id: str | None) -> None:
    async with tenant_session(org_id) as conn:
        contact = (await conn.execute(text("select contact_id from app.conversations where id = cast(:c as uuid)"),
                                      {"c": conversation_id})).scalar_one_or_none() if conversation_id else None
    await _attribute(org_id, str(contact) if contact else None, "replied_at", {})


@on("whatsapp.received")
@DBOS.workflow()
async def missed_call_reply(event: dict) -> None:
    await missed_reply_step(event["org_id"], event["payload"].get("conversation_id"))


@DBOS.step()
async def missed_booking_step(org_id: str, contact_id: str | None, booking_id: str | None) -> None:
    await _attribute(org_id, contact_id, "booked_at", {"booking_id": booking_id})


@on("booking.created")
@DBOS.workflow()
async def missed_call_booking(event: dict) -> None:
    await missed_booking_step(event["org_id"], event["payload"].get("contact_id"), event["payload"].get("booking_id"))


async def summary(conn, days: int = 30) -> dict:
    row = (await conn.execute(text("""select count(*) as missed, count(*) filter (where outcome = 'sent') as messaged,
        count(*) filter (where replied_at is not null) as replied, count(*) filter (where booked_at is not null) as booked
        from app.missed_calls where at > now() - make_interval(days => :d)"""), {"d": days})).mappings().one()
    return dict(row)
