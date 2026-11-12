"""Filing tracker (CA Firm pack): every filing on one board, and clients ask its status on WhatsApp.

    board    one card per filing: Documents pending -> In preparation -> In review -> Filed -> Verified; an owner, a due
             date, an acknowledgement number once filed; "my work" shows a staff member's cards
    season   "Start ITR AY 2026-27 for every individual client" creates the cards in one go (skips existing ones)
    status   a client who writes "is my ITR filed?" on WhatsApp gets the answer from the board (only their own filings)
    due      a daily check: cards due within N days (or overdue) and not filed become a Needs-you card for the firm
Filing a card emits ca.filing_filed (metric returns_filed).
"""
import re
from datetime import UTC, date, datetime, timedelta

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit
from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.db import system_session, tenant_session
from agentry.events import emit


class TrackerConfig(BaseModel):
    status_replies: bool = Field(True, title="Answer clients who ask about their filing on WhatsApp",
                                 description="\"Is my ITR filed?\" gets the status from the board: only that client's own filings",
                                 json_schema_extra={"editable_by": "client"})
    due_alert_days: int = Field(3, ge=0, le=30, title="Alert the firm this many days before a filing is due",
                                json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_filing_tracker", name="Filing tracker",
    description="Every filing on one board (documents pending to verified), owners and due dates; clients ask its status on WhatsApp.",
    config_model=TrackerConfig, metrics=("returns_filed",),
))


def title_for(kind: str, period: str) -> str:
    return f"{core.KINDS.get(kind, kind)} {period}".strip()


async def create_filing(conn: AsyncConnection, org_id: str, client_id: str, *, kind: str, period: str, due_on: date | None = None,
                        assignee: str | None = None, source: str = "manual", title: str | None = None, notes: str | None = None) -> str | None:
    """A new card (None if this client already has this filing for this period). The document chaser's checklist is
    built from the client's profile when that agent is on."""
    from agentry.automations.ca import chaser
    if kind not in core.KINDS:
        raise core.CaError("unknown filing type")
    if not period.strip():
        raise core.CaError("enter the period (e.g. AY 2026-27 or 2026-10)")
    c = (await conn.execute(text("select profile, kind, assignee from app.ca_clients where id = cast(:c as uuid)"), {"c": client_id})).mappings().first()
    if not c:
        raise core.CaError("client not found")
    checklist = chaser.checklist_for(kind, c["profile"] or {}, c["kind"]) if await core.enabled(conn, "ca_document_chaser") else []
    fid = (await conn.execute(text("""insert into app.ca_filings (org_id, client_id, kind, period, title, due_on, assignee, source, notes, checklist,
        status) values (:o, cast(:c as uuid), :k, :p, :t, :d, :a, :s, :n, cast(:cl as jsonb), :st)
        on conflict (org_id, client_id, kind, period) do nothing returning id::text"""),
        {"o": org_id, "c": client_id, "k": kind, "p": period.strip(), "t": title or title_for(kind, period.strip()), "d": due_on,
         "a": assignee or c["assignee"], "s": source, "n": notes, "cl": core.json.dumps(checklist),
         "st": "docs_pending" if checklist or kind in ("itr", "tax_audit") else "in_prep"})).scalar_one_or_none()
    if fid:
        await emit(conn, org_id, "ca.filing_created", {"filing_id": fid, "kind": kind, "period": period, "source": source})
    return fid


def season_matches(client: dict, kinds: list[str] | None, flag: str | None) -> bool:
    if kinds and client["kind"] not in kinds:
        return False
    return not flag or bool((client["profile"] or {}).get(flag))


async def start_season(conn: AsyncConnection, org_id: str, *, kind: str, period: str, due_on: date | None, client_kinds: list[str] | None,
                       flag: str | None, user_id: str | None) -> dict:
    clients = (await conn.execute(text("select id::text, kind, profile from app.ca_clients order by name"))).mappings().all()
    made = skipped = 0
    for c in clients:
        if not season_matches(dict(c), client_kinds, flag):
            continue
        if await create_filing(conn, org_id, c["id"], kind=kind, period=period, due_on=due_on, source="season"):
            made += 1
        else:
            skipped += 1
    await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action="ca.season_started",
                       metadata={"kind": kind, "period": period, "created": made, "already_there": skipped})
    return {"created": made, "already_there": skipped}


async def update_filing(conn: AsyncConnection, org_id: str, filing_id: str, changes: dict, *, user_id: str | None, actor_type: str = "user") -> dict:
    f = (await conn.execute(text("select * from app.ca_filings where id = cast(:i as uuid) for update"), {"i": filing_id})).mappings().first()
    if not f:
        raise core.CaError("filing not found")
    if "status" in changes and changes["status"] not in core.STATUSES:
        raise core.CaError("unknown status")
    new = {k: changes[k] for k in ("status", "assignee", "due_on", "ack_no", "filed_on", "notes", "title", "position") if k in changes}
    if new.get("status") in ("filed", "verified") and not (new.get("filed_on") or f["filed_on"]):
        new["filed_on"] = date.today()
    if not new:
        return dict(f)
    sets = ", ".join(f"{k} = :{k}" for k in new)
    moved = "status" in new and new["status"] != f["status"]
    row = (await conn.execute(text(f"""update app.ca_filings set {sets}, updated_at = now(){', status_at = now()' if moved else ''}
        where id = cast(:id as uuid) returning *"""), new | {"id": filing_id})).mappings().one()
    if moved:
        await audit.record(conn, org_id=org_id, actor_type=actor_type, actor_user_id=user_id, action="ca.filing_moved", target_type="ca_filing",
                           target_id=filing_id, metadata={"from": f["status"], "to": new["status"]})
        if new["status"] == "filed" and f["status"] != "verified":
            await emit(conn, org_id, "ca.filing_filed", {"filing_id": filing_id, "kind": f["kind"], "period": f["period"]})
    return dict(row)


async def board(conn: AsyncConnection, *, status: str | None = None, kind: str | None = None, period: str | None = None,
                assignee: str | None = None, client_id: str | None = None, q: str | None = None) -> list[dict]:
    where, p = ["true"], {}
    for col, v in (("f.status", status), ("f.kind", kind), ("f.period", period), ("f.assignee", assignee)):
        if v:
            where.append(f"{col} = :{col[2:]}")
            p[col[2:]] = v
    if client_id:
        where.append("f.client_id = cast(:client as uuid)")
        p["client"] = client_id
    if q:
        where.append("(c.name ilike :q or c.pan ilike :q or f.title ilike :q)")
        p["q"] = f"%{q}%"
    rows = (await conn.execute(text(f"""select f.id::text, f.client_id::text, c.name as client, c.pan, f.kind, f.period, f.title, f.due_on,
        f.status, f.assignee, f.ack_no, f.filed_on, f.notes, f.source, f.status_at, f.checklist, f.chase, f.position,
        (select count(*) from app.ca_files x where x.filing_id = f.id) as files
        from app.ca_filings f join app.ca_clients c on c.id = f.client_id where {' and '.join(where)}
        order by array_position(array['docs_pending','in_prep','review','filed','verified'], f.status), f.position, f.due_on nulls last, c.name
        limit 1000"""), p)).mappings().all()
    today = date.today()
    out = []
    for r in rows:
        d = dict(r)
        missing = [i["label"] for i in d.pop("checklist") or [] if i.get("status") == "missing"]
        d["missing"] = missing
        d["overdue"] = bool(d["due_on"] and d["due_on"] < today and d["status"] not in ("filed", "verified"))
        out.append(d)
    return out


# ---------- clients ask on WhatsApp ----------

ASKS_STATUS = re.compile(r"\b(status|filed|file[d]? (my|the)|itr|return|refund|gst|tds|acknowledg|ack|update on|kab tak|ho gaya|hua)\b", re.IGNORECASE)


async def status_text(conn: AsyncConnection, client_id: str) -> str:
    rows = (await conn.execute(text("""select title, status, due_on, ack_no, filed_on, checklist from app.ca_filings
        where client_id = cast(:c as uuid) and (status <> 'verified' or updated_at > now() - interval '60 days')
        order by created_at desc limit 6"""), {"c": client_id})).mappings().all()
    if not rows:
        return "We don't have a filing in progress for you right now. Someone from the team will get back to you."
    lines = []
    for r in rows:
        s = f"• {r['title']}: {core.STATUS_LABEL[r['status']]}"
        if r["status"] in ("filed", "verified") and r["ack_no"]:
            s += f" (acknowledgement {r['ack_no']}{', ' + r['filed_on'].strftime('%d %b %Y') if r['filed_on'] else ''})"
        elif r["status"] == "docs_pending":
            missing = [i["label"] for i in r["checklist"] or [] if i.get("status") == "missing"]
            if missing:
                s += ". Still needed from you: " + ", ".join(missing)
        elif r["due_on"]:
            s += f" (due {r['due_on'].strftime('%d %b')})"
        lines.append(s)
    return "Here's where your filings are:\n" + "\n".join(lines) + "\n\nReply here if you have a question; the team will see it."


async def answer_status(org_id: str, conversation_id: str, wa_id: str, body: str) -> bool:
    """A firm's client asking about their filing on WhatsApp: answered from the board. False when it isn't that."""
    if not ASKS_STATUS.search(body or ""):
        return False
    async with tenant_session(org_id) as conn:
        cfg = await core.enabled(conn, "ca_filing_tracker")
        if not cfg or cfg["status"] not in ("live", "approval_mode") or not cfg.get("status_replies", True):
            return False
        client = await core.client_by_phone(conn, wa_id)
        if not client:
            return False
        reply = await status_text(conn, client["id"])
    from agentry.connectors.whatsapp import send_text
    mid = await send_text(org_id, wa_id, reply)
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, :c, 'out', 'agent', :b, cast(:m as jsonb))"""),
            {"o": org_id, "c": conversation_id, "b": reply, "m": core.json.dumps({"external_id": f"wa:{mid}", "sent_from": "ca_filing_tracker"})})
    return True


# ---------- due dates ----------

async def due_alerts(org_id: str, today: date | None = None) -> int:
    today = today or datetime.now(UTC).date()
    async with tenant_session(org_id) as conn:
        cfg = await core.enabled(conn, "ca_filing_tracker")
        if not cfg:
            return 0
        days = int(cfg.get("due_alert_days", 3))
        rows = (await conn.execute(text("""select f.id::text, f.title, f.due_on, f.status, c.name from app.ca_filings f
            join app.ca_clients c on c.id = f.client_id where f.status not in ('filed','verified') and f.due_on is not null
            and f.due_on <= :until order by f.due_on"""), {"until": today + timedelta(days=days)})).mappings().all()
        made = 0
        for r in rows:
            late = (today - r["due_on"]).days
            when = f"overdue by {late} day{'s' if late != 1 else ''}" if late > 0 else "due today" if late == 0 else f"due {r['due_on']:%d %b}"
            if await core.card(conn, org_id, "ca_filing_tracker", f"{r['name']}: {r['title']} is {when}",
                               f"Status: {core.STATUS_LABEL[r['status']]}. Open the filing board to move it on.",
                               {"key": f"due:{r['id']}:{'late' if late > 0 else 'soon'}", "filing_id": r["id"]}):
                made += 1
    return made


@DBOS.step()
async def ca_daily_step() -> dict:
    from agentry import official_rules
    from agentry.automations.ca import calendar, chaser, recurring
    await official_rules.fresh()
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select distinct org_id from app.automation_instances
            where template_key = any(:k) and status in ('live','approval_mode')"""), {"k": list(core.CA_KEYS)})).scalars())
    out = {"due": 0, "reminders": 0, "calendar": 0, "recurring": 0}
    for o in orgs:
        out["recurring"] += await recurring.book_due(o)
        out["calendar"] += await calendar.daily(o)
        out["due"] += await due_alerts(o)
        out["reminders"] += await chaser.send_reminders(o)
    return out


@DBOS.workflow()
async def ca_daily(scheduled_time: datetime, context) -> None:
    await ca_daily_step()
