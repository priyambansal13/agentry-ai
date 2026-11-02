"""Ops dispatcher (ROADMAP-V3 C2, v2 11.4): service requests become jobs, assigned to the right technician, with
customer updates and an invoice when the work is done.

    in        the chat agent's book_job tool (website, WhatsApp, Telegram) when a customer needs a visit, or the team adds one
    assign    the active technician with the skill and the area who has the fewest jobs that day (under their daily
              maximum); nobody fits -> the job waits as "new" with a Needs-you card
    tech      the dispatcher sends the job to the technician on WhatsApp with one tap (a prefilled message)
    updates   "on the way" and "done" messages to the customer (WhatsApp / Telegram / email; never 9 pm - 8 am)
    done      photos of the finished work are kept on the job; an amount creates an invoice (invoice follow-up chases it
              when that agent is on)
"""
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit, governance
from agentry.automations import AutomationTemplate, register
from agentry.config import settings
from agentry.db import tenant_session
from agentry.events import emit

SLOTS = ("morning", "afternoon", "evening", "any")


class DispatchConfig(BaseModel):
    services: list[str] = Field(default_factory=lambda: ["AC service", "AC repair", "Plumbing", "Electrical", "Cleaning"], title="Services you send people for",
                                json_schema_extra={"editable_by": "client"})
    auto_assign: bool = Field(True, title="Assign jobs to a technician automatically", json_schema_extra={"editable_by": "client"})
    tell_customers: bool = Field(True, title="Tell customers when the technician is on the way and when the job is done", json_schema_extra={"editable_by": "client"})
    invoice_days: int = Field(7, ge=0, le=60, title="Invoice due after (days)", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ops_dispatcher", name="Ops dispatcher",
    description="Service requests become jobs assigned to the right technician; customers get 'on the way' and 'done' updates; finished jobs get invoiced.",
    config_model=DispatchConfig, metrics=("jobs_done",),
))


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'ops_dispatcher'"))).first()
    return (row.status, DispatchConfig(**(row.config or {})).model_dump()) if row else (None, DispatchConfig().model_dump())


def _match(a: str, b: str) -> bool:
    a, b = (a or "").lower().strip(), (b or "").lower().strip()
    return bool(a and b) and (a in b or b in a)


async def pick(conn: AsyncConnection, service: str, area: str | None, day: date) -> dict | None:
    techs = (await conn.execute(text("""select t.id::text, t.name, t.phone, t.skills, t.areas, t.max_per_day,
        (select count(*) from app.service_jobs j where j.technician_id = t.id and j.day = :d and j.status not in ('cancelled')) as load
        from app.technicians t where t.active order by t.name"""), {"d": day})).mappings().all()
    fit = [t for t in techs if (not t["skills"] or any(_match(s, service) for s in t["skills"]))
           and (not area or not t["areas"] or any(_match(a, area) for a in t["areas"])) and t["load"] < t["max_per_day"]]
    return dict(min(fit, key=lambda t: (t["load"], t["name"]))) if fit else None


async def create_job(conn: AsyncConnection, org_id: str, *, customer: str, service: str, day: date, phone: str | None = None, address: str | None = None,
                     area: str | None = None, slot: str = "any", description: str | None = None, conversation_id: str | None = None,
                     source: str = "person", user_id: str | None = None) -> dict:
    from agentry.leads import resolve_contact
    _s, cfg = await settings_of(conn)
    if day < date.today():
        raise ValueError("that day has passed")
    contact = await resolve_contact(conn, org_id, name=customer, phone=phone, source="dispatcher") if phone else None
    if not contact and conversation_id:
        contact = (await conn.execute(text("select contact_id::text from app.conversations where id = cast(:c as uuid)"), {"c": conversation_id})).scalar_one_or_none()
    await conn.execute(text("select pg_advisory_xact_lock(hashtext(:o || '/jobs'))"), {"o": org_id})
    number = (await conn.execute(text("select coalesce(max(number), 100) + 1 from app.service_jobs"))).scalar_one()
    tech = await pick(conn, service, area, day) if cfg["auto_assign"] else None
    jid = str((await conn.execute(text("""insert into app.service_jobs (org_id, number, contact_id, conversation_id, customer, phone, address, area, service,
        description, day, slot, status, technician_id, source) values (:o, :n, cast(:k as uuid), cast(:c as uuid), :cu, :p, :ad, :ar, :sv, :de, :d, :sl, :st,
        cast(:t as uuid), :src) returning id"""),
        {"o": org_id, "n": number, "k": contact, "c": conversation_id, "cu": customer[:120], "p": phone, "ad": address, "ar": area, "sv": service[:80],
         "de": description, "d": day, "sl": slot if slot in SLOTS else "any", "st": "assigned" if tech else "new", "t": tech["id"] if tech else None,
         "src": source})).scalar_one())
    await emit(conn, org_id, "job.created", {"job_id": jid, "number": number, "assigned": bool(tech)})
    if not tech:
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload) values (:o, 'escalation', 'ops_dispatcher', :t, :b,
            cast(:p as jsonb))"""), {"o": org_id, "t": f"Job #{number} needs a technician: {service} for {customer} on {day:%d %b}",
                                     "b": "Nobody with that skill and area is free that day. Assign someone on the Jobs page.", "p": json.dumps({"job_id": jid})})
    return {"id": jid, "number": number, "technician": tech["name"] if tech else None}


async def job_from_chat(org_id: str, conversation_id: str, args: dict) -> dict:
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode"):
            return {"error": "jobs can't be booked here: offer to have the team call them"}
        try:
            day = date.fromisoformat(str(args.get("day")))
        except ValueError:
            return {"error": "ask which day suits them"}
        if not args.get("address") and not args.get("area"):
            return {"error": "ask for their address or area first"}
        try:
            j = await create_job(conn, org_id, customer=str(args.get("name") or "Customer"), service=str(args.get("service") or cfg["services"][0]), day=day,
                                 phone=args.get("phone"), address=args.get("address"), area=args.get("area"), slot=str(args.get("slot") or "any"),
                                 description=args.get("problem"), conversation_id=conversation_id, source="agent")
        except ValueError as e:
            return {"error": str(e)}
    return {"job": j["number"], "tell_customer": f"Booked as job #{j['number']} for {day:%a %d %b}. The team will confirm the technician and time."}


async def _tell(conn: AsyncConnection, org_id: str, job: dict, body: str) -> str | None:
    from agentry.outbound import reach_contact
    if not job["contact_id"]:
        return None
    tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
    if governance.is_quiet(datetime.now(UTC), tz):
        return "not sent: it's night"
    k = (await conn.execute(text("""select id::text as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
        from app.contacts where id = :k"""), {"k": job["contact_id"]})).mappings().one()
    return (await reach_contact(conn, org_id, dict(k), body, agent="ops_dispatcher", subject=f"Your {job['service']} job", email_ref=f"job:{job['id']}"))["status"]


async def update(conn: AsyncConnection, org_id: str, jid: str, changes: dict, user_id: str | None) -> dict:
    j = (await conn.execute(text("""select j.*, t.name as tech, t.phone as tech_phone from app.service_jobs j left join app.technicians t on t.id = j.technician_id
        where j.id = cast(:i as uuid) for update of j"""), {"i": jid})).mappings().first()
    if not j:
        raise ValueError("job not found")
    _s, cfg = await settings_of(conn)
    new = {k: v for k, v in changes.items() if k in ("status", "technician_id", "day", "slot", "amount", "notes") and v is not None}
    if new.get("status") and new["status"] not in ("new", "assigned", "on_the_way", "in_progress", "done", "cancelled"):
        raise ValueError("unknown status")
    if new.get("technician_id") and new.get("status") is None and j["status"] == "new":
        new["status"] = "assigned"
    if new.get("status") in ("on_the_way", "in_progress", "done") and not (new.get("technician_id") or j["technician_id"]):
        raise ValueError("assign a technician first")
    sets = [f"{k} = cast(:{k} as uuid)" if k == "technician_id" else f"{k} = :{k}" for k in new]
    if new.get("status") == "done":
        sets.append("done_at = now()")
    if not sets:
        return dict(j)
    await conn.execute(text(f"update app.service_jobs set {', '.join(sets)}, updated_at = now() where id = cast(:id as uuid)"), new | {"id": jid})
    told = None
    tech = j["tech"]
    if new.get("technician_id"):
        tech = (await conn.execute(text("select name from app.technicians where id = cast(:i as uuid)"), {"i": new["technician_id"]})).scalar_one_or_none()
    business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
    first = (j["customer"] or "").split()[0] if j["customer"] else "there"
    if new.get("status") == "on_the_way" and cfg["tell_customers"]:
        told = await _tell(conn, org_id, dict(j), f"Hi {first}, {tech} from {business} is on the way for your {j['service']} (job #{j['number']}).")
    if new.get("status") == "done":
        await emit(conn, org_id, "job.done", {"job_id": jid, "number": j["number"]})
        amount = new.get("amount") or j["amount"]
        if amount and not j["invoice_id"] and j["contact_id"]:
            cur = (await conn.execute(text("select currency from app.org_settings"))).scalar_one_or_none() or "INR"
            inv = (await conn.execute(text("""insert into app.invoices (org_id, contact_id, number, currency, amount, amount_paid, issued_on, due_on, status, source)
                values (:o, :k, :n, :c, :a, 0, :i, :d, 'open', 'dispatcher') on conflict (org_id, number) do nothing returning id::text"""),
                {"o": org_id, "k": j["contact_id"], "n": f"JOB-{j['number']}", "c": cur, "a": amount, "i": date.today(),
                 "d": date.today() + timedelta(days=cfg["invoice_days"])})).scalar_one_or_none()
            if inv:
                await conn.execute(text("update app.service_jobs set invoice_id = cast(:v as uuid) where id = cast(:i as uuid)"), {"v": inv, "i": jid})
                from agentry.invoices import enroll_open
                await enroll_open(conn, org_id)
        if cfg["tell_customers"]:
            told = await _tell(conn, org_id, dict(j), f"Hi {first}, your {j['service']} (job #{j['number']}) is done. Thank you for choosing {business}!"
                               + (f" The bill of ₹{float(amount):,.0f} will follow." if amount else ""))
    if new.get("status"):
        await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"job.{new['status']}", target_type="job", target_id=jid)
    return {"id": jid, "status": new.get("status") or j["status"], "told": told}


def tech_message(j: dict) -> str:
    return (f"Job #{j['number']}: {j['service']}\n{j['day']:%a %d %b} ({j['slot']})\n{j['customer']}{' · ' + j['phone'] if j.get('phone') else ''}\n"
            f"{j.get('address') or j.get('area') or ''}\n{j.get('description') or ''}").strip()


async def add_photo(org_id: str, jid: str, data: bytes, filename: str | None) -> str:
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("photos can be up to 10 MB")
    if not re.search(r"\.(jpe?g|png|webp)$", (filename or "").lower()):
        raise ValueError("send a photo (JPG, PNG or WEBP)")
    p = Path(settings.documents_dir) / org_id / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    f = p / f"{uuid.uuid4()}{Path(filename or 'x.jpg').suffix.lower()}"
    f.write_bytes(data)
    rel = str(f.relative_to(Path(settings.documents_dir)))
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.service_jobs set photos = photos || cast(:p as jsonb) where id = cast(:i as uuid)"), {"p": json.dumps([rel]), "i": jid})
    return rel
