"""Billing for clients (plan, statements with evidence, disputes, results report, exports, notification prefs)
and for Agentry HQ (plans, generating and issuing statements, resolving disputes, client detail with margin)."""
import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit, billing
from agentry.auth import OrgContext, Principal, client_ip, require, require_staff
from agentry.db import app_engine, system_session, tenant_session
from agentry.features import enabled_automations
from agentry.notify.alerts import kinds_for

router = APIRouter(tags=["billing"])


def _month(m: str | None) -> tuple[date, date]:
    d = datetime.strptime(m, "%Y-%m").date() if m else datetime.now(UTC).date()
    return billing.month_bounds(d)


async def _statement(conn, sid: str) -> dict:
    st = (await conn.execute(text("select * from app.statements where id = cast(:s as uuid)"), {"s": sid})).mappings().first()
    if not st:
        raise HTTPException(404, "statement not found")
    lines = (await conn.execute(text("select * from app.statement_lines where statement_id = :s order by position"), {"s": sid})).mappings().all()
    ids = [i for ln in lines for i in ln["evidence"]]
    # bookings made on a phone call carry the call itself as evidence: length, summary, and whether it can be played
    outcomes = (await conn.execute(text("""select o.id, o.kind, o.occurred_at, o.value, o.strength, o.evidence,
          case when c.channel = 'voice' then jsonb_build_object('conversation_id', c.id, 'duration_seconds', c.metadata->'duration_seconds',
            'summary', c.metadata->'call'->>'summary', 'recording', c.metadata ? 'recording') end as call
        from app.outcomes o left join app.conversations c on c.id = cast(nullif(o.evidence->>'conversation_id', '') as uuid)
        where o.id = any(cast(:ids as uuid[])) order by o.occurred_at"""), {"ids": ids})).mappings().all() if ids else []
    excluded = (await conn.execute(text("""select kind, occurred_at, value, exclusion_reason, evidence from app.outcomes
        where status <> 'billable' and occurred_at >= :a and occurred_at < :b order by occurred_at"""),
        {"a": st["period_start"], "b": st["period_end"] + timedelta(days=1)})).mappings().all()
    org = (await conn.execute(text("""select o.name, s.country, s.profile from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
    return {"statement": dict(st), "lines": [dict(ln) for ln in lines], "evidence": {str(o["id"]): dict(o) for o in outcomes},
            "excluded": [dict(e) for e in excluded], "client": {"name": org["name"], "country": org["country"]}}


# ---------- client ----------

@router.get("/org/billing")
async def billing_home(ctx: Annotated[OrgContext, Depends(require("billing", "read"))]) -> dict:
    """Plan, a live estimate for this month (computed in a transaction that is rolled back), and past statements."""
    start, end = _month(None)
    estimate = None
    async with app_engine.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(text("select set_config('app.org_id', :o, true)"), {"o": ctx.org_id})
            plan = (await conn.execute(text("select * from app.pricing_plans"))).mappings().first()
            if plan:
                sid = await billing.generate_statement(conn, ctx.org_id, start, end)
                estimate = await _statement(conn, sid)
        finally:
            await tx.rollback()
    async with tenant_session(ctx.org_id) as conn:
        statements = (await conn.execute(text("""select id, number, period_start, period_end, status, total, currency, issued_at,
            dispute_until, paid_at, payment_link from app.statements where status <> 'draft' or :staff order by period_start desc"""),
            {"staff": ctx.principal.is_staff})).mappings().all()
    return {"plan": dict(plan) if plan else None, "estimate": estimate, "statements": [dict(s) for s in statements]}


@router.get("/org/billing/statements/{sid}")
async def statement_detail(sid: str, ctx: Annotated[OrgContext, Depends(require("billing", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        d = await _statement(conn, sid)
    if d["statement"]["status"] == "draft" and not ctx.principal.is_staff:
        raise HTTPException(404, "statement not found")
    return d


class Dispute(BaseModel):
    reason: Annotated[str, Field(min_length=5, max_length=1000)]


@router.post("/org/billing/lines/{line_id}/dispute")
async def dispute_line(line_id: str, body: Dispute, request: Request, ctx: Annotated[OrgContext, Depends(require("billing", "manage"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            await billing.dispute(conn, line_id, body.reason)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="billing.line_disputed", target_type="statement_line", target_id=line_id,
                           metadata={"reason": body.reason}, ip=client_ip(request))
    return {"disputed": True}


@router.get("/org/reports/results")
async def results_report(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))], month: str | None = None) -> dict:
    """Monthly results report: what the agents delivered, its value, what Agentry cost, and the ROI multiple."""
    start, end = _month(month)
    async with tenant_session(ctx.org_id) as conn:
        return await billing.month_report(conn, start, end)


EXPORTS = {
    "contacts": "select name, email, phone, phone_e164, company, source, created_at from app.contacts where merged_into is null order by created_at",
    "leads": """select k.name, k.email, k.phone_e164, l.source, l.stage, l.qualification::text, l.owner_automation, l.created_at
                from app.leads l join app.contacts k on k.id = l.contact_id order by l.created_at""",
    "invoices": "select number, currency, amount, amount_paid, issued_on, due_on, status, source, notes from app.invoices order by due_on",
    "conversations": """select c.channel, c.subject, c.status, m.direction, m.author, m.body, m.created_at from app.messages m
                        join app.conversations c on c.id = m.conversation_id order by m.created_at""",
}


@router.get("/org/export/{kind}.csv")
async def export(kind: str, request: Request, ctx: Annotated[OrgContext, Depends(require("data", "export"))]) -> StreamingResponse:
    if kind not in EXPORTS:
        raise HTTPException(404, "unknown export")
    async with tenant_session(ctx.org_id) as conn:
        result = await conn.execute(text(EXPORTS[kind]))
        cols, rows = list(result.keys()), result.all()
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="data.exported", target_type="export", target_id=kind, ip=client_ip(request))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{kind}-{date.today()}.csv"'})


async def _my_kinds(ctx: OrgContext) -> dict[str, list[str]]:
    async with tenant_session(ctx.org_id) as conn:
        automations = await enabled_automations(conn)
    return kinds_for(ctx.role, automations, ctx.principal.is_staff)


@router.get("/org/notifications")
async def get_prefs(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    """Only the alerts this person may receive (their role) about automations this client has."""
    from agentry.notify.alerts import whatsapp_alerts
    kinds = await _my_kinds(ctx)
    async with tenant_session(ctx.org_id) as conn:
        p = (await conn.execute(text("select prefs from app.notification_preferences where user_id = :u"), {"u": ctx.principal.user_id})).scalar_one_or_none()
    wa = await whatsapp_alerts(ctx.org_id) is not None
    tg = await _telegram_linked(ctx)
    channels = ["email"] + (["whatsapp"] if wa else []) + (["telegram"] if tg else [])
    return {"prefs": {k: (p or {}).get(k, default) for k, default in kinds.items() if k != "cards" or tg},
            "channels": channels, "whatsapp_to": (p or {}).get("whatsapp_to")}


async def _telegram_linked(ctx: OrgContext) -> bool:
    async with tenant_session(ctx.org_id) as conn:
        return bool((await conn.execute(text("select 1 from app.telegram_links where user_id = :u"), {"u": ctx.principal.user_id})).first())


@router.put("/org/notifications")
async def set_prefs(prefs: dict[str, list[str]], ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    from agentry.notify.alerts import whatsapp_alerts
    kinds = await _my_kinds(ctx)
    allowed = {"email"} | ({"whatsapp"} if await whatsapp_alerts(ctx.org_id) else set()) | ({"telegram"} if await _telegram_linked(ctx) else set())
    clean = {k: [c for c in v if c in allowed and (k != "cards" or c == "telegram")] for k, v in prefs.items() if k in kinds}
    async with tenant_session(ctx.org_id) as conn:
        old = (await conn.execute(text("select prefs from app.notification_preferences where user_id = :u"), {"u": ctx.principal.user_id})).scalar_one_or_none() or {}
        merged = {**old, **clean}
        await conn.execute(text("""insert into app.notification_preferences (user_id, org_id, prefs) values (:u, :o, cast(:p as jsonb))
            on conflict (user_id, org_id) do update set prefs = excluded.prefs"""),
            {"u": ctx.principal.user_id, "o": ctx.org_id, "p": json.dumps(merged)})
    linked = await _telegram_linked(ctx)
    return {"prefs": {k: merged.get(k, default) for k, default in kinds.items() if k != "cards" or linked}}


class WhatsAppNumber(BaseModel):
    number: str | None = Field(None, max_length=20)


@router.put("/org/notifications/whatsapp")
async def set_whatsapp_number(body: WhatsAppNumber, ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    """The number this person's WhatsApp alerts go to (#3)."""
    from agentry.leads import normalize_phone
    async with tenant_session(ctx.org_id) as conn:
        e164 = None
        if body.number:
            region = (await conn.execute(text("select country from app.org_settings"))).scalar() or "IN"
            e164 = normalize_phone(body.number, region)
            if not e164:
                raise HTTPException(422, "that doesn't look like a valid phone number")
        await conn.execute(text("""insert into app.notification_preferences (user_id, org_id, prefs)
            values (:u, :o, jsonb_strip_nulls(jsonb_build_object('whatsapp_to', cast(:n as text))))
            on conflict (user_id, org_id) do update set prefs = (app.notification_preferences.prefs - 'whatsapp_to')
              || jsonb_strip_nulls(jsonb_build_object('whatsapp_to', cast(:n as text)))"""),
            {"u": ctx.principal.user_id, "o": ctx.org_id, "n": e164})
    return {"whatsapp_to": e164}


# ---------- Agentry HQ ----------

@router.get("/hq/orgs/{org_id}")
async def hq_org(org_id: str, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    m_start, m_end = billing.month_bounds(datetime.now(UTC).date().replace(day=1) - timedelta(days=1))  # last full month
    async with tenant_session(org_id) as conn:
        settings_ = (await conn.execute(text("""select s.*, o.name, o.slug from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().first()
        if not settings_:
            raise HTTPException(404, "client not found")
        plan = (await conn.execute(text("select * from app.pricing_plans"))).mappings().first()
        statements = (await conn.execute(text("""select id, number, period_start, status, total, currency,
            (select count(*) from app.statement_lines l where l.statement_id = s.id and l.disputed and l.dispute_resolution is null) as open_disputes
            from app.statements s order by period_start desc"""))).mappings().all()
        autos = (await conn.execute(text("select template_key, status from app.automation_instances order by template_key"))).mappings().all()
        m = await billing.margin(conn, _dt(m_start), _dt(m_end + timedelta(days=1)))
        outcomes = dict((await conn.execute(text("""select kind || ':' || status, count(*) from app.outcomes group by 1"""))).all())
    async with system_session() as conn:
        members = (await conn.execute(text("""select u.name, u.email, m.role from auth.member m join auth."user" u on u.id = m."userId"
            where m."organizationId" = :o"""), {"o": org_id})).mappings().all()
    return {"org": {k: settings_[k] for k in ("name", "slug", "status", "industry_pack", "country", "currency", "website")},
            "plan": dict(plan) if plan else None, "statements": [dict(s) for s in statements], "automations": [dict(a) for a in autos],
            "members": [dict(m) for m in members], "margin": {"month": f"{m_start:%Y-%m}", **m}, "outcomes": outcomes}


@router.put("/hq/orgs/{org_id}/plan")
async def set_plan(org_id: str, plan: billing.PricingPlan, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with tenant_session(org_id) as conn:
        await billing.save_plan(conn, org_id, plan)
        await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff.user_id, action="billing.plan_set",
                           metadata=json.loads(plan.model_dump_json()))
    return {"ok": True}


class Generate(BaseModel):
    month: Annotated[str, Field(pattern=r"^\d{4}-\d{2}$")]


@router.post("/hq/orgs/{org_id}/statements", status_code=201)
async def generate(org_id: str, body: Generate, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    start, end = _month(body.month)
    async with tenant_session(org_id) as conn:
        try:
            sid = await billing.generate_statement(conn, org_id, start, end)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    return {"statement_id": sid}


@router.post("/hq/orgs/{org_id}/statements/{sid}/issue")
async def issue(org_id: str, sid: str, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with tenant_session(org_id) as conn:
        try:
            r = await billing.issue(conn, org_id, sid)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff.user_id, action="billing.statement_issued",
                           target_type="statement", target_id=sid)
        from agentry.events import emit
        await emit(conn, org_id, "statement.issued", {"statement_id": sid})
    return r


@router.get("/hq/orgs/{org_id}/statements/{sid}")
async def hq_statement(org_id: str, sid: str, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with tenant_session(org_id) as conn:
        return await _statement(conn, sid)


class Resolve(BaseModel):
    accept: bool = False
    credit: Annotated[Decimal | None, Field(gt=0)] = None  # partial credit instead of all-or-nothing
    note: Annotated[str | None, Field(max_length=300)] = None
    exclude_outcomes: list[str] | None = None


@router.post("/hq/orgs/{org_id}/lines/{line_id}/resolve")
async def resolve(org_id: str, line_id: str, body: Resolve, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with tenant_session(org_id) as conn:
        try:
            await billing.resolve(conn, line_id, body.accept, credit=body.credit, note=body.note, exclude_outcomes=body.exclude_outcomes)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        outcome = "partial" if body.credit is not None else ("accepted" if body.accept else "rejected")
        await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff.user_id,
                           action=f"billing.dispute_{outcome}", target_type="statement_line", target_id=line_id,
                           metadata={"credit": str(body.credit)} if body.credit is not None else {})
    return {"resolved": True}


@router.get("/hq/billing")
async def hq_billing(_: Annotated[Principal, Depends(require_staff)], months: Annotated[int, Query(ge=1, le=12)] = 1) -> dict:
    """Revenue and margin across all clients over the last `months` full calendar months (statements are monthly)."""
    end = datetime.now(UTC).date().replace(day=1)
    start = end
    for _ in range(months):
        start = (start - timedelta(days=1)).replace(day=1)
    out = []
    async with system_session() as conn:
        orgs = (await conn.execute(text("""select o.id, o.name from app.pricing_plans p join auth.organization o on o.id = p.org_id order by o.name"""))).all()
    for o in orgs:
        async with tenant_session(o.id) as conn:
            out.append({"org_id": o.id, "name": o.name, **await billing.margin(conn, _dt(start), _dt(end))})
    return {"months": months, "from": start.isoformat(), "to": (end - timedelta(days=1)).isoformat(), "items": out}


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)



# ---------- Telegram: link this person to Agentry's team bot ----------

@router.get("/org/telegram")
async def telegram_status(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    from agentry import telegram_team
    return await telegram_team.link_status(ctx.org_id, ctx.principal.user_id)


@router.post("/org/telegram/link")
async def telegram_link(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    """A one-time t.me link (15 minutes): opening it in Telegram ties this person's chat to the bot, in this business."""
    from agentry import telegram_team
    from agentry.connectors.telegram import TelegramError
    try:
        return await telegram_team.create_link(ctx.org_id, ctx.principal.user_id)
    except TelegramError as e:
        raise HTTPException(503, str(e)) from e


@router.delete("/org/telegram")
async def telegram_unlink(request: Request, ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    from agentry import telegram_team
    await telegram_team.unlink(ctx.org_id, ctx.principal.user_id)
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="telegram.unlinked", target_type="user", target_id=ctx.principal.user_id, ip=client_ip(request))
    return {"linked": False}
