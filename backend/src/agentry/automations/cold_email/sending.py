"""Sending cold email (Phase 5.4): approved prospects get a short plain-text sequence from separate sending mailboxes.

    step 0  day 0   the first email: their first line, what you offer, one easy question
    step 1  day 3   a short bump in the same thread
    step 2  day 7   one more reason, still short
    step 3  day 14  the last one: "I'll stop here"

Rules (docs/PHASE-5-COLD-EMAIL.md §5): weekdays in office hours (the business's timezone), each mailbox under its
ramp-up cap (5 on day one, +3 a day, up to its daily cap), one mailbox per prospect so follow-ups stay in one thread,
every email with the business's postal address and a one-click unsubscribe, a suppression check before every send,
and a mailbox that bounces more than 3% (after 20 sends) or gets any spam complaint is paused automatically.
"""
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.cold_email import providers as prov
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.secrets import sign_state

STEP_DAYS = [0, 3, 7, 14]
OFFICE = (9, 30, 17, 30)  # 09:30-17:30, Monday to Friday
BOUNCE_LIMIT, BOUNCE_MIN_SENDS = 0.03, 20


class CannotStart(ValueError):
    pass


def first_name(name: str | None) -> str:
    return (name or "").split()[0] if name else "there"


def unsubscribe_token(org_id: str, prospect_id: str) -> str:
    return sign_state({"t": "unsub", "org": org_id, "p": prospect_id}, ttl_seconds=400 * 86400)


def compose(step: int, p: dict, cfg: dict, mailbox: dict, business: str, first_subject: str | None) -> tuple[str, str]:
    """(subject, body) for one step. Plain text, short, the same footer on every email."""
    fn = first_name(p["name"])
    pitch = (cfg.get("pitch") or "").strip().rstrip(".")
    subject = first_subject or f"Quick question, {fn}"
    if step > 0:
        subject = f"Re: {subject}"
    if step == 0:
        core = f"{p['first_line']}\n\n{pitch}.\n\nWorth a 15-minute call next week to see if it fits {p['company']}?"
    elif step == 1:
        core = "Bumping this up in case it got buried. Happy to send a 2-minute video instead of a call if that's easier."
    elif step == 2:
        core = f"One more thought: {pitch[0].lower() + pitch[1:] if pitch else 'we keep it simple'}, and you see results before paying more.\n\nShall I send a short example?"
    else:
        core = "I'll stop here so I don't crowd your inbox. If the timing is better later, just reply to this email."
    link = f"{settings.web_url}/unsubscribe/{unsubscribe_token(p['org_id'], str(p['id']))}"
    footer = f"{mailbox['sender_name']}\n{business}\n{cfg.get('postal_address') or ''}".rstrip()
    body = f"Hi {fn},\n\n{core}\n\n{footer}\n\nDon't want these emails? Unsubscribe: {link}"
    return subject, body


def cap_today(mailbox: dict, now: datetime) -> int:
    days = max(0, (now - mailbox["started_at"]).days)
    return min(mailbox["daily_cap"], mailbox["start_cap"] + mailbox["ramp_per_day"] * days)


def in_office_hours(now: datetime, tz: str) -> bool:
    local = now.astimezone(ZoneInfo(tz or "Asia/Kolkata"))
    start, end = local.replace(hour=OFFICE[0], minute=OFFICE[1]), local.replace(hour=OFFICE[2], minute=OFFICE[3])
    return local.weekday() < 5 and start <= local <= end


def _local_midnight(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz or "Asia/Kolkata"))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


# ---------- starting and stopping ----------

async def start_campaign(conn: AsyncConnection, campaign_id: str) -> dict:
    """Every approved line enters the sequence; the first emails go out as mailbox capacity allows."""
    c = (await conn.execute(text("select status, build_status from app.campaigns where id = cast(:c as uuid) and kind = 'cold_email'"),
                            {"c": campaign_id})).mappings().first()
    if not c:
        raise CannotStart("campaign not found")
    cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'cold_email'"))).scalar_one_or_none() or {}
    missing = [label for key, label in (("pitch", "what you offer"), ("postal_address", "your postal address")) if not (cfg.get(key) or "").strip()]
    if missing:
        raise CannotStart(f"add {' and '.join(missing)} in the cold email settings first")
    if not (await conn.execute(text("select 1 from app.sending_mailboxes where status = 'active'"))).first():
        raise CannotStart("no sending mailbox yet: Agentry sets these up on separate domains")
    if c["build_status"] == "building":
        raise CannotStart("the list is still being built")
    n = (await conn.execute(text("""update app.prospects set status = 'active', next_step = 0, next_send_at = now(), updated_at = now()
        where campaign_id = cast(:c as uuid) and review = 'approved' and status = 'waiting'"""), {"c": campaign_id})).rowcount
    if not n and c["status"] != "running":
        raise CannotStart("approve at least one first line first")
    await conn.execute(text("update app.campaigns set status = 'running' where id = cast(:c as uuid)"), {"c": campaign_id})
    return {"queued": n}


async def set_paused(conn: AsyncConnection, campaign_id: str, paused: bool) -> None:
    await conn.execute(text("update app.campaigns set status = :s where id = cast(:c as uuid) and kind = 'cold_email' and status in ('running','paused')"),
                       {"s": "paused" if paused else "running", "c": campaign_id})


async def stop_prospect(conn: AsyncConnection, prospect_id: str, reason: str) -> None:
    await conn.execute(text("""update app.prospects set status = 'stopped', stop_reason = :r, next_send_at = null, updated_at = now()
        where id = cast(:p as uuid) and status in ('waiting','active')"""), {"r": reason, "p": prospect_id})


async def check_mailbox(conn: AsyncConnection, mailbox_id: str) -> str | None:
    """Pause a mailbox whose bounces or complaints say it's hurting the domain. Returns the reason if paused."""
    row = (await conn.execute(text("""select count(*) filter (where kind = 'sent') as sent, count(*) filter (where kind = 'bounce') as bounced,
        count(*) filter (where kind = 'complaint') as complaints from app.email_events
        where mailbox_id = cast(:m as uuid) and at > now() - interval '30 days'"""), {"m": mailbox_id})).mappings().one()
    why = None
    if row["complaints"]:
        why = "a recipient marked an email as spam"
    elif row["sent"] >= BOUNCE_MIN_SENDS and row["bounced"] / row["sent"] > BOUNCE_LIMIT:
        why = f"bounce rate {row['bounced'] / row['sent']:.0%} (limit {BOUNCE_LIMIT:.0%})"
    if why:
        await conn.execute(text("""update app.sending_mailboxes set status = 'paused', paused_reason = :w
            where id = cast(:m as uuid) and status = 'active'"""), {"w": why, "m": mailbox_id})
    return why


# ---------- the sender ----------

async def send_due(org_id: str, now: datetime | None = None) -> dict:
    """Send every email that's due now, within office hours and mailbox caps. Safe to run as often as you like."""
    now = now or datetime.now(UTC)
    sent, waiting = 0, 0
    p = prov.get()
    async with tenant_session(org_id) as conn:
        org = (await conn.execute(text("""select s.timezone, coalesce(o.name, '') as business from app.org_settings s
            join auth.organization o on o.id = s.org_id"""))).mappings().one()
        if not in_office_hours(now, org["timezone"]):
            return {"sent": 0, "reason": "outside office hours"}
        cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'cold_email'"))).scalar_one_or_none() or {}
        boxes = [dict(b) for b in (await conn.execute(text("select * from app.sending_mailboxes where status = 'active' order by created_at"))).mappings()]
        midnight = _local_midnight(now, org["timezone"])
        left = {}
        for b in boxes:
            used = (await conn.execute(text("""select count(*) from app.email_events where mailbox_id = :m and kind = 'sent' and at >= :t"""),
                                       {"m": b["id"], "t": midnight})).scalar_one()
            left[str(b["id"])] = max(0, cap_today(b, now) - used)
        due = (await conn.execute(text("""select p.*, co.name as company from app.prospects p
            join app.prospect_companies co on co.id = p.company_id join app.campaigns c on c.id = p.campaign_id
            where c.kind = 'cold_email' and c.status = 'running' and p.status = 'active' and p.next_send_at <= :n
            order by p.next_step desc, p.next_send_at limit 500"""), {"n": now})).mappings().all()  # follow-ups first
        for row in due:
            pr = dict(row)
            if (await conn.execute(text("select 1 from app.suppressions where address = :a and channel in ('email','all')"),
                                   {"a": pr["email"]})).first():
                await stop_prospect(conn, str(pr["id"]), "on the do-not-contact list")
                continue
            box = next((b for b in boxes if str(b["id"]) == str(pr["mailbox_id"])), None) if pr["mailbox_id"] else \
                max(boxes, key=lambda b: left[str(b["id"])], default=None)
            if pr["mailbox_id"] and box is None:  # its mailbox was paused: the thread waits rather than jumping mailboxes
                waiting += 1
                continue
            if box is None or left[str(box["id"])] <= 0:
                waiting += 1
                continue
            first_subject = (await conn.execute(text("""select detail->>'subject' from app.email_events where prospect_id = :p and kind = 'sent'
                and step = 0"""), {"p": pr["id"]})).scalar_one_or_none()
            subject, body = compose(pr["next_step"], pr, cfg, box, org["business"], first_subject)
            unsub_api = f"{settings.api_public_url}/public/unsubscribe/{unsubscribe_token(org_id, str(pr['id']))}"
            headers = {"List-Unsubscribe": f"<{unsub_api}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
            from agentry import governance
            d = await governance.decide(conn, org_id, "cold_email.send", now)
            if d.mode == "shadow":  # watching only: nothing goes out; the person stays queued
                waiting += 1
                continue
            if d.mode != "send":  # today's business-wide limit: the rest wait until tomorrow
                waiting += 1
                break
            msg_id = await p.send(box, pr["email"], subject, body, headers)
            left[str(box["id"])] -= 1
            sent += 1
            await conn.execute(text("""insert into app.email_events (org_id, campaign_id, prospect_id, mailbox_id, kind, step, detail, at)
                values (:o, :c, :p, :m, 'sent', :s, cast(:d as jsonb), :now)"""),
                {"o": org_id, "c": pr["campaign_id"], "p": pr["id"], "m": box["id"], "s": pr["next_step"], "now": now,
                 "d": json.dumps({"subject": subject, "body": body, "message_id": msg_id})})
            nxt = pr["next_step"] + 1
            first_at = now if pr["next_step"] == 0 else (await conn.execute(text("""select at from app.email_events
                where prospect_id = :p and kind = 'sent' and step = 0"""), {"p": pr["id"]})).scalar_one()
            await conn.execute(text("""update app.prospects set mailbox_id = :m, next_step = :n, updated_at = now(),
                next_send_at = :at, status = case when :done then 'finished' else status end where id = :p"""),
                {"m": box["id"], "n": nxt, "p": pr["id"], "done": nxt >= len(STEP_DAYS),
                 "at": None if nxt >= len(STEP_DAYS) else first_at + timedelta(days=STEP_DAYS[nxt])})
        await conn.execute(text("""update app.campaigns c set status = 'completed' where c.kind = 'cold_email' and c.status = 'running'
            and not exists (select 1 from app.prospects p where p.campaign_id = c.id and p.status in ('waiting','active'))
            and exists (select 1 from app.prospects p where p.campaign_id = c.id and p.status in ('finished','stopped'))"""))
    return {"sent": sent, "waiting_for_capacity": waiting}


@DBOS.step()
async def orgs_sending() -> list[str]:
    async with system_session() as conn:
        return list((await conn.execute(text("select distinct org_id from app.campaigns where kind = 'cold_email' and status = 'running'"))).scalars())


@DBOS.step()
async def send_due_step(org_id: str) -> dict:
    return await send_due(org_id)


@DBOS.workflow()
async def send_cold_emails(scheduled_time: datetime, context) -> None:
    for org_id in await orgs_sending():
        await send_due_step(org_id)
