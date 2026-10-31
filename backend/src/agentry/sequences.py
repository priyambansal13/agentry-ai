"""Sequence engine: "step N, X days after the anchor, on these channels, in this tone", for invoices and leads.

One durable DBOS workflow per enrollment (workflow id seq-<enrollment id>):

    loop:  plan = next_action()          # reads the subject fresh: paid? paused? stopped? which step is due?
           done  -> finish
           wait  -> DBOS.recv("seq", timeout) # sleeps (days, durably) until the step is due or an event wakes it
           send  -> send_step()             # consent + suppression checked; approval mode -> "Needs you"

- Catch-up rule: after downtime only the *latest* due step is sent, never a burst of missed ones.
- Events (payment, promise to pay, opt-out, booking, manual pause) update the database, then wake the workflow with
  DBOS.send(seq-<id>, ...); the workflow re-plans from the database, so the database is the single source of truth.
- Pacing: campaign enrollments get a start slot (next_run_at) so a list is worked through gradually.
"""
import json
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.db import tenant_session
from agentry.events import emit
from agentry.leads import can_contact
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.runs import run

MAX_SLEEP = 6 * 3600  # re-plan at least every 6 hours (picks up edited due dates, new pauses)

DEFAULTS = {
    "invoice_default": {"name": "Invoice reminders (7/14/21/28)", "automation_key": "invoice_follow_up", "steps": [
        {"offset_minutes": 7 * 1440, "anchor": "due", "channels": ["email"], "tone": "friendly"},
        {"offset_minutes": 14 * 1440, "anchor": "due", "channels": ["email", "whatsapp"], "tone": "polite",
         "whatsapp_template": "invoice_reminder"},
        {"offset_minutes": 21 * 1440, "anchor": "due", "channels": ["email", "whatsapp"], "tone": "firm",
         "whatsapp_template": "invoice_reminder"},
        {"offset_minutes": 28 * 1440, "anchor": "due", "channels": ["email", "whatsapp"], "tone": "final",
         "whatsapp_template": "invoice_final_reminder"},
    ]},
    "reactivation_default": {"name": "Reactivation: hi again", "automation_key": "lead_reactivation", "steps": [
        {"offset_minutes": 0, "anchor": "enrolled", "channels": ["whatsapp", "email"], "tone": "warm",
         "whatsapp_template": "reactivation_hello", "first_channel_only": True},
        {"offset_minutes": 3 * 1440, "anchor": "enrolled", "channels": ["whatsapp", "email"], "tone": "light",
         "whatsapp_template": "reactivation_follow_up", "first_channel_only": True},
    ]},
    "speed_to_lead_default": {"name": "Speed-to-lead (text)", "automation_key": "speed_to_lead", "steps": [
        {"offset_minutes": 1, "anchor": "enrolled", "channels": ["whatsapp", "email"], "tone": "instant",
         "whatsapp_template": "new_enquiry_hello", "first_channel_only": True},
        {"offset_minutes": 1440, "anchor": "enrolled", "channels": ["whatsapp", "email"], "tone": "follow_up",
         "whatsapp_template": "new_enquiry_follow_up", "first_channel_only": True},
    ]},
}


async def ensure_sequence(conn: AsyncConnection, org_id: str, key: str) -> str:
    d = DEFAULTS[key]
    return str((await conn.execute(text("""insert into app.sequences (org_id, key, name, automation_key, steps)
        values (:o, :k, :n, :a, cast(:s as jsonb)) on conflict (org_id, key) do update set name = app.sequences.name
        returning id"""), {"o": org_id, "k": key, "n": d["name"], "a": d["automation_key"], "s": json.dumps(d["steps"])})).scalar_one())


async def enroll(conn: AsyncConnection, org_id: str, *, sequence_key: str, subject_type: str, subject_id: str,
                 contact_id: str | None, start_at: datetime | None = None) -> str | None:
    """Enroll a subject (idempotent: an active enrollment for the same subject is reused). Emits sequence.enrolled,
    which the worker turns into the durable workflow."""
    seq_id = await ensure_sequence(conn, org_id, sequence_key)
    existing = (await conn.execute(text("""select id from app.sequence_enrollments where sequence_id = :s and subject_id = :x
        and status in ('active','paused')"""), {"s": seq_id, "x": subject_id})).scalar_one_or_none()
    if existing:
        return None
    eid = str((await conn.execute(text("""insert into app.sequence_enrollments (org_id, sequence_id, subject_type, subject_id,
        contact_id, next_run_at) values (:o, :s, :t, :x, :c, :n) returning id"""),
        {"o": org_id, "s": seq_id, "t": subject_type, "x": subject_id, "c": contact_id, "n": start_at})).scalar_one())
    await emit(conn, org_id, "sequence.enrolled", {"enrollment_id": eid})
    return eid


def workflow_id(enrollment_id: str) -> str:
    return f"seq-{enrollment_id}"


# ---------- planning ----------

async def _load(conn: AsyncConnection, enrollment_id: str) -> dict | None:
    row = (await conn.execute(text("""
        select e.*, s.steps, s.automation_key, a.status as automation_status, a.config as automation_config, o.timezone
        from app.sequence_enrollments e join app.sequences s on s.id = e.sequence_id
        left join app.automation_instances a on a.template_key = s.automation_key
        left join app.org_settings o on o.org_id = e.org_id
        where e.id = :e"""), {"e": enrollment_id})).mappings().first()
    return dict(row) if row else None


async def _subject(conn: AsyncConnection, e: dict) -> dict:
    if e["subject_type"] == "invoice":
        inv = (await conn.execute(text("""select i.*, k.name as contact_name, k.company, k.email, k.phone_e164
            from app.invoices i left join app.contacts k on k.id = i.contact_id where i.id = :i"""), {"i": e["subject_id"]})).mappings().one()
        return dict(inv)
    lead = (await conn.execute(text("""select l.*, k.name as contact_name, k.email, k.phone_e164
        from app.leads l left join app.contacts k on k.id = l.contact_id where l.id = :l"""), {"l": e["subject_id"]})).mappings().one()
    return dict(lead)


def _anchor(e: dict, subj: dict, step: dict) -> datetime:
    if step.get("anchor") == "due" and subj.get("due_on"):
        d: date = subj["due_on"]  # 10:00 on the due day in the client's own timezone (#18)
        return datetime(d.year, d.month, d.day, 10, 0, tzinfo=ZoneInfo(e.get("timezone") or "Asia/Kolkata")).astimezone(UTC)
    return e["next_run_at"] or e["created_at"]


def _resolved(e: dict, subj: dict) -> str | None:
    if e["subject_type"] == "invoice":
        if subj["status"] in ("paid", "void", "written_off"):
            return f"invoice {subj['status']}"
        if subj["status"] == "disputed":
            return "invoice disputed"
    elif subj.get("stage") in ("booked", "showed", "won", "lost", "disqualified", "opted_out"):
        return f"lead {subj['stage']}"
    return None


@DBOS.step()
async def next_action(org_id: str, enrollment_id: str, now_iso: str | None = None) -> dict:
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
    async with tenant_session(org_id) as conn:
        e = await _load(conn, enrollment_id)
        if not e or e["status"] in ("stopped", "completed"):
            return {"action": "done", "reason": e["stop_reason"] if e else "missing"}
        subj = await _subject(conn, e)
        if reason := _resolved(e, subj):
            await conn.execute(text("""update app.sequence_enrollments set status = 'completed', stop_reason = :r, updated_at = now()
                where id = :e"""), {"r": reason, "e": enrollment_id})
            return {"action": "done", "reason": reason}
        if e["automation_status"] not in ("live", "approval_mode"):
            return {"action": "wait", "seconds": MAX_SLEEP, "reason": "automation paused"}
        if e["status"] == "paused" and not e["paused_until"]:  # paused by a person until they resume (#6)
            return {"action": "wait", "seconds": MAX_SLEEP, "reason": "paused"}
        if e["paused_until"] and e["paused_until"] > now:
            return {"action": "wait", "seconds": min(MAX_SLEEP, (e["paused_until"] - now).total_seconds()), "reason": "paused"}
        steps = e["steps"]
        due = [i for i, st in enumerate(steps)
               if i > e["last_step"] and _anchor(e, subj, st) + timedelta(minutes=st["offset_minutes"]) <= now]
        if due:
            return {"action": "send", "step": max(due)}  # catch-up: only the latest due step
        if e["last_step"] >= len(steps) - 1:
            await conn.execute(text("""update app.sequence_enrollments set status = 'completed', stop_reason = 'all steps sent',
                updated_at = now() where id = :e"""), {"e": enrollment_id})
            if e["subject_type"] == "invoice" and final_sent(e):
                await _reminders_ended(conn, org_id, subj)  # if the final one still waits for approval: when it's sent
            return {"action": "done", "reason": "all steps sent"}
        nxt = steps[e["last_step"] + 1]
        at = _anchor(e, subj, nxt) + timedelta(minutes=nxt["offset_minutes"])
        return {"action": "wait", "seconds": max(1.0, min(MAX_SLEEP, (at - now).total_seconds())), "reason": "next step"}


def final_sent(e: dict) -> bool:
    """Did the last step really go out? In approval mode a step can be "done" while its message still waits in Needs you."""
    last = len(e["steps"]) - 1
    return any(entry.get("step") == last and any(r.get("status") in ("sent", "recorded") for r in entry.get("results", []))
               for entry in (e.get("log") or []))


async def _reminders_ended(conn: AsyncConnection, org_id: str, inv: dict) -> None:
    """Every reminder went out and the invoice is still unpaid: time for a phone call (#12). Once per invoice."""
    done = (await conn.execute(text("""update app.invoices set reminders_ended_at = now() where id = :i and reminders_ended_at is null
        returning id"""), {"i": inv["id"]})).first()
    if not done:
        return
    balance = float(inv["amount"]) - float(inv["amount_paid"])
    days = (datetime.now(UTC).date() - inv["due_on"]).days
    await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
        values (:o, 'escalation', 'invoice_follow_up', :t, :b, cast(:p as jsonb))"""),
        {"o": org_id, "t": f"Reminders finished: invoice {inv['number']} still unpaid ({_money(balance, inv['currency'])})",
         "b": f"{inv.get('company') or inv.get('contact_name') or 'The customer'} hasn't paid {days} days after the due date, "
              f"after every reminder. Time for a call{(' to ' + inv['phone_e164']) if inv.get('phone_e164') else ''}.",
         "p": json.dumps({"invoice_id": str(inv["id"]), "phone": inv.get("phone_e164"), "urgent": True})})


# ---------- composing ----------

def _money(amount, currency: str) -> str:
    v = float(amount)
    if currency == "INR":  # Indian grouping: 1,10,000 not 110,000
        whole = f"{round(v):d}"
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1]) if head else ""
        return f"₹{head + ',' if head else ''}{tail}"
    return f"{currency} {v:,.2f}"


def _drop_sentences_with(body: str, token: str) -> str:
    """Remove every sentence that refers to a fact we don't have (e.g. [PAY_LINK] with no payment link)."""
    lines = []
    for line in body.split("\n"):
        if token in line:
            parts = re.split(r"(?<=[.!?])\s+", line)
            line = " ".join(p for p in parts if token not in p)
        lines.append(line)
    return "\n".join(lines)


async def compose(conn: AsyncConnection, org_id: str, e: dict, subj: dict, step: dict, step_index: int) -> dict:
    """Subject + body for one email step. Amounts, dates and links come from the database, never from the model."""
    biz = (await conn.execute(text("""select o.name, s.persona->>'signoff' as signoff, s.profile->>'offer' as offer
        from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
    signoff = biz["signoff"] or f"The {biz['name']} team"
    first = (subj.get("contact_name") or "there").split()[0]
    if e["subject_type"] == "invoice":
        if (e.get("automation_config") or {}).get("payment_links", True):
            from agentry.invoices import payment_link
            subj["payment_link"] = await payment_link(conn, org_id, subj) or subj.get("payment_link")
        balance = float(subj["amount"]) - float(subj["amount_paid"])
        facts = {"[INVOICE]": subj["number"], "[AMOUNT]": _money(balance, subj["currency"]),
                 "[DUE_DATE]": subj["due_on"].strftime("%d %b %Y"), "[PAY_LINK]": subj.get("payment_link") or ""}
        days = (datetime.now(UTC).date() - subj["due_on"]).days
        prompt = load("invoice_reminder_writer")
        vars_ = {"business": biz["name"], "signoff": signoff, "contact_name": subj.get("contact_name") or "",
                 "company": subj.get("company") or "", "step_number": step_index + 1, "step_total": len(e["steps"]),
                 "tone": step["tone"], "days_overdue": max(days, 0), "history": subj.get("notes") or "none",
                 "pay_link_available": "yes" if facts["[PAY_LINK]"] else "no"}
        fallback = {"subject": "Reminder: invoice [INVOICE] ([AMOUNT])",
                    "body": f"Hi {first},\n\nA quick reminder that invoice [INVOICE] for [AMOUNT] was due on [DUE_DATE]."
                            + (" You can pay here: [PAY_LINK]" if facts["[PAY_LINK]"] else "")
                            + f"\n\nIf it's already on its way, please ignore this note.\n\nThanks,\n{signoff}"}
    else:
        q = subj.get("qualification") or {}
        prompt = load("reactivation_writer")
        vars_ = {"business": biz["name"], "signoff": signoff, "first_name": first,
                 "interest": q.get("interest") or q.get("need") or "our services", "when": q.get("last_contact") or "a while ago",
                 "step_number": step_index + 1, "step_total": len(e["steps"]), "offer": biz["offer"] or ""}
        facts = {}
        fallback = {"subject": f"Still thinking about {vars_['interest']}?",
                    "body": f"Hi {first},\n\nYou'd asked us about {vars_['interest']} a while ago. Is that still on your mind? "
                            f"Happy to answer any questions or find you a time.\n\n{signoff}"}
    try:
        res = await complete("writer", prompt.render(**vars_), org_id=org_id, prompt_key=prompt.key,
                             prompt_version=prompt.version, json_output=True, mock_response=json.dumps(fallback))
        msg = res.data if isinstance(res.data, dict) and res.data.get("body") else fallback
    except AllModelsFailed:
        msg = fallback
    subject, body = msg.get("subject") or fallback["subject"], msg["body"]
    if not facts.get("[PAY_LINK]"):
        body = _drop_sentences_with(body, "[PAY_LINK]")
    for k, v in facts.items():
        subject, body = subject.replace(k, v), body.replace(k, v)
    if e["subject_type"] == "invoice" and facts["[AMOUNT]"] not in body:
        body += f"\n\n(Invoice {facts['[INVOICE]']}: {facts['[AMOUNT]']} due on {facts['[DUE_DATE]']}.)"  # facts always present
    body = re.sub(r"\[PAY_LINK\]|\[[A-Z_]+\]", "", body)
    return {"subject": subject, "body": body.strip(), "template_params": [first, *(
        [facts["[INVOICE]"], facts["[AMOUNT]"], facts["[DUE_DATE]"]] if e["subject_type"] == "invoice"
        else [vars_["interest"]])]}


# ---------- sending ----------

@DBOS.step()
async def send_step(org_id: str, enrollment_id: str, step_index: int) -> dict:
    async with tenant_session(org_id) as conn:
        agent = (await conn.execute(text("""select s.automation_key from app.sequence_enrollments e join app.sequences s on s.id = e.sequence_id
            where e.id = cast(:e as uuid)"""), {"e": enrollment_id})).scalar_one_or_none() or "sequences"
    async with run(org_id, agent, "sequence.step", key=f"seq:{enrollment_id}:{step_index}", subject=("enrollment", enrollment_id)) as r:
        out = await _send_step(org_id, enrollment_id, step_index)
        r.step(f"step {step_index + 1}", results=[f"{x['channel']}: {x['status']}" for x in out["results"]])
        return out


async def _send_step(org_id: str, enrollment_id: str, step_index: int) -> dict:
    from agentry.outbound import (  # late import: outbound depends on connectors
        channel_problem,
        deliver_outbound,
    )
    async with tenant_session(org_id) as conn:
        e = await _load(conn, enrollment_id)
        subj = await _subject(conn, e)
        step = e["steps"][step_index]
        msg = await compose(conn, org_id, e, subj, step, step_index)
        results = []
        for channel in step["channels"]:
            ok, why = await can_contact(conn, e["contact_id"], channel) if e["contact_id"] else (False, "no contact")
            if not ok:
                results.append({"channel": channel, "status": "skipped", "reason": why})
                continue
            if why := await channel_problem(org_id, channel, step.get("whatsapp_template")):  # no card for a message that can't go
                results.append({"channel": channel, "status": "skipped", "reason": why})
                continue
            if e["automation_status"] == "approval_mode":
                await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
                    values (:o, 'outbound_draft', :a, :t, :b, cast(:p as jsonb))"""),
                    {"o": org_id, "a": e["automation_key"], "b": msg["body"],
                     "t": f"{step['tone'].replace('_', ' ').capitalize()} {channel} to {subj.get('contact_name') or subj.get('email') or 'contact'}"
                          + (f" · invoice {subj['number']}" if e["subject_type"] == "invoice" else ""),
                     "p": json.dumps({"enrollment_id": enrollment_id, "step": step_index, "channel": channel,
                                      "subject": msg["subject"], "template": step.get("whatsapp_template"),
                                      "template_params": msg["template_params"]})})
                results.append({"channel": channel, "status": "awaiting_approval"})
            else:
                results.append({"channel": channel, **await deliver_outbound(
                    conn, org_id, enrollment=e, channel=channel, subject=msg["subject"], body=msg["body"],
                    template=step.get("whatsapp_template"), template_params=msg["template_params"])})
            if step.get("first_channel_only") and results[-1]["status"] in ("sent", "recorded", "awaiting_approval"):
                break
        await conn.execute(text("""update app.sequence_enrollments set last_step = :i, updated_at = now(),
            log = log || cast(:l as jsonb) where id = :e"""),
            {"i": step_index, "e": enrollment_id,
             "l": json.dumps([{"step": step_index, "at": datetime.now(UTC).isoformat(), "results": results}])})
        if e["subject_type"] == "lead" and any(r["status"] in ("sent", "recorded") for r in results):
            await conn.execute(text("""update app.leads set touches = touches + 1, last_touch_at = now(),
                stage = case when stage in ('new','nurture') then 'contacted' else stage end where id = :l"""), {"l": e["subject_id"]})
        for r in results:
            if r["status"] in ("sent", "recorded"):
                await emit(conn, org_id, "message.sent", {"channel": r["channel"], "enrollment_id": enrollment_id,
                                                          "automation": e["automation_key"]})
    return {"step": step_index, "results": results}


@DBOS.workflow()
async def run_enrollment(org_id: str, enrollment_id: str) -> str:
    for _ in range(500):  # hard cap on iterations; each wait is at most MAX_SLEEP
        plan = await next_action(org_id, enrollment_id)
        if plan["action"] == "done":
            return plan["reason"]
        if plan["action"] == "send":
            await send_step(org_id, enrollment_id, plan["step"])
            continue
        await DBOS.recv_async("seq", timeout_seconds=plan["seconds"])  # woken early by events
    return "iteration cap"


async def start(org_id: str, enrollment_id: str) -> None:
    with SetWorkflowID(workflow_id(enrollment_id)):
        await DBOS.start_workflow_async(run_enrollment, org_id, enrollment_id)


async def wake(enrollment_id: str, reason: str) -> None:
    """Make a sleeping enrollment re-plan now (after a payment, pause, resume, stop...). If its workflow hasn't started
    yet (the enrollment is seconds old) or already finished, there's nothing to wake: it plans from the database when it
    starts, and the watchdog starts any that are missing."""
    from dbos._error import DBOSNonExistentWorkflowError
    try:
        await DBOS.send_async(workflow_id(enrollment_id), {"reason": reason}, topic="seq")
    except DBOSNonExistentWorkflowError:
        pass
