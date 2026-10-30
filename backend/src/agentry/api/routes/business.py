"""Invoices, leads pipeline, reactivation campaigns, lead forms, payment gateway connections."""
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, require
from agentry.automations.lead_reactivation import eligibility, import_old_leads, start_campaign
from agentry.automations.speed_to_lead import capture, create_source
from agentry.config import settings
from agentry.connectors.http import client
from agentry.connectors.store import save_connection
from agentry.db import system_session, tenant_session
from agentry.features import require_connection, require_page
from agentry.invoices import (
    apply_payment,
    enroll_open,
    map_columns,
    normalise_rows,
    parse_file,
    upsert_invoices,
)
from agentry.leads import dedupe

router = APIRouter(tags=["business"])
MAX_UPLOAD = 5 * 1024 * 1024


# ---------- invoices ----------

@router.get("/org/invoices", dependencies=[Depends(require_page("invoices"))])
async def list_invoices(ctx: Annotated[OrgContext, Depends(require("invoice", "read"))],
                        status: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 200) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""
            select i.id, i.number, i.currency, i.amount, i.amount_paid, i.amount - i.amount_paid as balance, i.issued_on, i.due_on,
                   i.status, i.source, i.payment_link, i.notes, current_date - i.due_on as days_overdue,
                   k.name as contact_name, k.company, k.email, (k.email is not null or k.phone_e164 is not null) as contactable,
                   e.status as reminders, e.last_step, e.paused_until, e.stop_reason,
                   (select count(*) from jsonb_array_elements(coalesce(e.log, '[]')) st, jsonb_array_elements(st->'results') r
                     where r->>'status' in ('sent','recorded')) as reminders_sent,
                   (select count(*) from app.approvals a where a.kind = 'outbound_draft' and a.status = 'pending'
                     and a.payload->>'enrollment_id' = e.id::text) as reminders_awaiting
            from app.invoices i left join app.contacts k on k.id = i.contact_id
            left join lateral (select * from app.sequence_enrollments e where e.subject_type = 'invoice' and e.subject_id = i.id
                               order by e.created_at desc limit 1) e on true
            where (cast(:s as text) is null or i.status = :s) order by i.due_on limit :l"""), {"s": status, "l": limit})).mappings().all()
        buckets = (await conn.execute(text("""
            select currency,
              sum(amount - amount_paid) filter (where current_date - due_on <= 0) as not_due,
              sum(amount - amount_paid) filter (where current_date - due_on between 1 and 7) as d1_7,
              sum(amount - amount_paid) filter (where current_date - due_on between 8 and 14) as d8_14,
              sum(amount - amount_paid) filter (where current_date - due_on between 15 and 30) as d15_30,
              sum(amount - amount_paid) filter (where current_date - due_on > 30) as d30_plus
            from app.invoices where status in ('open','partially_paid') group by currency"""))).mappings().all()
        recovered = (await conn.execute(text("""select coalesce(sum(amount), 0) from app.payments
            where received_at > now() - interval '30 days' and invoice_id is not null"""))).scalar_one()
    return {"items": [dict(r) for r in rows], "ageing": [dict(b) for b in buckets], "recovered_30d": float(recovered)}


@router.post("/org/invoices/import", dependencies=[Depends(require_page("invoices"))])
async def import_invoices(ctx: Annotated[OrgContext, Depends(require("invoice", "act"))], request: Request,
                          file: Annotated[UploadFile, File()], commit: Annotated[bool, Form()] = False) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large (max 5 MB)")
    try:
        rows = parse_file(data, file.filename or "upload.csv")
    except Exception as e:
        raise HTTPException(422, f"couldn't read that file: {e}") from e
    if not rows:
        raise HTTPException(422, "the file has no rows")
    async with tenant_session(ctx.org_id) as conn:
        currency = (await conn.execute(text("select currency from app.org_settings"))).scalar_one()
    mapping, how = await map_columns(ctx.org_id, list(rows[0].keys()), rows)
    missing = [f for f in ("number", "amount", "due_on") if f not in mapping]
    if missing:
        return {"ok": False, "mapping": mapping, "missing": missing, "columns": list(rows[0].keys())}
    clean, issues = normalise_rows(rows, mapping, currency)
    preview = {"ok": True, "mapping": mapping, "mapped_by": how, "rows": len(rows), "valid": len(clean), "issues": issues[:20],
               "sample": [{k: str(v) if v is not None else None for k, v in r.items()} for r in clean[:5]]}
    if not commit:
        return preview
    async with tenant_session(ctx.org_id) as conn:
        result = await upsert_invoices(conn, ctx.org_id, clean, source="import")
        merged = await dedupe(conn)
        enrolled = await enroll_open(conn, ctx.org_id)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="invoices.imported", metadata={"file": file.filename, **{k: result[k] for k in ("created", "updated")}},
                           ip=client_ip(request))
    async with tenant_session(ctx.org_id) as conn:
        no_contact = (await conn.execute(text("""select count(*) from app.invoices i left join app.contacts k on k.id = i.contact_id
            where i.status in ('open', 'partially_paid') and (k.id is null or (k.email is null and k.phone_e164 is null))"""))).scalar_one()
    return {**preview, "created": result["created"], "updated": result["updated"], "contacts_merged": merged,
            "reminders_started": enrolled, "no_contact": no_contact}


class ManualPayment(BaseModel):
    amount: Annotated[Decimal, Field(gt=0)]
    reference: Annotated[str, Field(min_length=1, max_length=120)]


@router.post("/org/invoices/{invoice_id}/payments", status_code=201, dependencies=[Depends(require_page("invoices"))])
async def record_payment(invoice_id: str, body: ManualPayment, request: Request,
                         ctx: Annotated[OrgContext, Depends(require("invoice", "act"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        inv = (await conn.execute(text("select currency from app.invoices where id = cast(:i as uuid)"), {"i": invoice_id})).first()
        if not inv:
            raise HTTPException(404, "invoice not found")
        pid = await apply_payment(conn, ctx.org_id, invoice_id=invoice_id, amount=body.amount, currency=inv.currency,
                                  gateway="manual", reference=body.reference, match="manual")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="invoice.payment_recorded", target_type="invoice", target_id=invoice_id,
                           metadata={"amount": str(body.amount), "reference": body.reference}, ip=client_ip(request))
    if pid is None:
        raise HTTPException(409, "a payment with this reference is already recorded")
    return {"payment_id": pid}


@router.post("/org/invoices/{invoice_id}/reminders/{action}", dependencies=[Depends(require_page("invoices"))])
async def reminders(invoice_id: str, action: str, ctx: Annotated[OrgContext, Depends(require("invoice", "act"))]) -> dict:
    if action not in ("pause", "resume", "stop"):
        raise HTTPException(404, "unknown action")
    new = {"pause": "paused", "resume": "active", "stop": "stopped"}[action]
    async with tenant_session(ctx.org_id) as conn:
        ids = (await conn.execute(text("""update app.sequence_enrollments set status = :s, paused_until = null,
            stop_reason = case when :s = 'stopped' then 'stopped by user' else stop_reason end, updated_at = now()
            where subject_id = cast(:i as uuid) and status in ('active','paused') returning id"""), {"s": new, "i": invoice_id})).scalars().all()
        from agentry.events import emit
        for eid in ids:
            await emit(conn, ctx.org_id, "sequence.changed", {"enrollment_id": str(eid), "action": action})
    return {"updated": len(ids), "status": new}


class InvoiceStatus(BaseModel):
    action: Literal["reopen", "write_off", "void"]
    note: Annotated[str | None, Field(max_length=500)] = None


@router.post("/org/invoices/{invoice_id}/status", dependencies=[Depends(require_page("invoices"))])
async def invoice_status(invoice_id: str, body: InvoiceStatus, request: Request,
                         ctx: Annotated[OrgContext, Depends(require("invoice", "act"))]) -> dict:
    """Resolve a dispute (#9): reopen (reminders start again), write it off, or void it (sent by mistake)."""
    async with tenant_session(ctx.org_id) as conn:
        inv = (await conn.execute(text("select id, number, status, amount, amount_paid from app.invoices where id = cast(:i as uuid)"),
                                  {"i": invoice_id})).mappings().first()
        if not inv:
            raise HTTPException(404, "invoice not found")
        if inv["status"] == "paid":
            raise HTTPException(409, "this invoice is paid")
        new = {"reopen": "partially_paid" if inv["amount_paid"] > 0 else "open", "write_off": "written_off", "void": "void"}[body.action]
        note = f"{datetime.now(UTC):%d %b}: {body.action.replace('_', ' ')} by {ctx.principal.name or 'a team member'}" + (f": {body.note}" if body.note else "")
        await conn.execute(text("""update app.invoices set status = :s, reminders_ended_at = null, updated_at = now(),
            notes = concat_ws(E'\n', notes, cast(:n as text)) where id = cast(:i as uuid)"""), {"s": new, "n": note, "i": invoice_id})
        await conn.execute(text("""update app.approvals set status = 'resolved', decided_at = now(), decided_by = :u
            where status = 'pending' and kind = 'dispute' and automation_key = 'invoice_follow_up'
              and (payload->>'invoice_id' = :i or conversation_id in (select id from app.conversations where metadata->>'subject_id' = :i))"""),
            {"u": ctx.principal.user_id, "i": invoice_id})
        if body.action == "reopen":
            await enroll_open(conn, ctx.org_id)
        else:
            from agentry.invoices import withdraw_reminder_cards
            await withdraw_reminder_cards(conn, invoice_id, new)
        from agentry.events import emit
        for eid in (await conn.execute(text("""select id from app.sequence_enrollments where subject_id = cast(:i as uuid)
                and status in ('active', 'paused')"""), {"i": invoice_id})).scalars():
            await emit(conn, ctx.org_id, "sequence.changed", {"enrollment_id": str(eid), "action": body.action})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=f"invoice.{body.action}", target_type="invoice", target_id=inv["number"], ip=client_ip(request))
    return {"status": new}


class PaymentConfirm(BaseModel):
    approval_id: str
    invoice_id: str | None = None  # for an unmatched payment: the invoice it belongs to
    reference: Annotated[str | None, Field(max_length=120)] = None


@router.post("/org/payments/confirm", dependencies=[Depends(require_page("invoices"))])
async def confirm_payment(body: PaymentConfirm, request: Request, ctx: Annotated[OrgContext, Depends(require("invoice", "act"))]) -> dict:
    """The two "check a payment" cards (#9): the customer says they paid -> confirm it (records the balance as paid);
    a payment we couldn't match -> say which invoice it was for."""
    async with tenant_session(ctx.org_id) as conn:
        a = (await conn.execute(text("""select id, payload from app.approvals where id = cast(:a as uuid) and kind = 'payment_review'
            and status = 'pending'"""), {"a": body.approval_id})).mappings().first()
        if not a:
            raise HTTPException(404, "no such payment to check")
        p = a["payload"] or {}
        if p.get("payment_id"):  # a payment that arrived without a clear invoice
            if not body.invoice_id:
                raise HTTPException(422, "choose the invoice this payment is for")
            pay = (await conn.execute(text("select amount, currency, reference from app.payments where id = cast(:p as uuid)"),
                                      {"p": p["payment_id"]})).mappings().one()
            inv = (await conn.execute(text("""update app.invoices set amount_paid = least(amount, amount_paid + :a),
                status = case when amount_paid + :a >= amount then 'paid' else 'partially_paid' end, updated_at = now()
                where id = cast(:i as uuid) and status in ('open', 'partially_paid', 'disputed') returning number, status"""),
                {"a": pay["amount"], "i": body.invoice_id})).first()
            if not inv:
                raise HTTPException(409, "that invoice isn't open")
            await conn.execute(text("update app.payments set invoice_id = cast(:i as uuid), match = 'manual' where id = cast(:p as uuid)"),
                               {"i": body.invoice_id, "p": p["payment_id"]})
            from agentry.events import emit
            from agentry.invoices import withdraw_reminder_cards
            await withdraw_reminder_cards(conn, body.invoice_id, "paid")
            await emit(conn, ctx.org_id, "payment.received", {"amount": float(pay["amount"]), "currency": pay["currency"],
                                                              "invoice_id": body.invoice_id, "payment_id": p["payment_id"],
                                                              "reference": pay["reference"], "invoice": inv.number, "status": inv.status,
                                                              "match": "manual", "gateway": "manual"})
        else:  # the customer says it's paid: record the balance
            inv_id = p.get("invoice_id")
            row = (await conn.execute(text("select currency, amount - amount_paid as balance from app.invoices where id = cast(:i as uuid)"),
                                      {"i": inv_id})).first()
            if not row or row.balance <= 0:
                raise HTTPException(409, "nothing left to pay on this invoice")
            pid = await apply_payment(conn, ctx.org_id, invoice_id=inv_id, amount=row.balance, currency=row.currency, gateway="manual",
                                      reference=body.reference or p.get("utr") or f"confirmed-{body.approval_id[:8]}", match="manual")
            if pid is None:
                raise HTTPException(409, "a payment with this reference is already recorded")
        await conn.execute(text("update app.approvals set status = 'resolved', decided_at = now(), decided_by = :u where id = cast(:a as uuid)"),
                           {"u": ctx.principal.user_id, "a": body.approval_id})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="payment.confirmed", target_type="approval", target_id=body.approval_id, ip=client_ip(request))
    return {"confirmed": True}


# ---------- leads pipeline ----------

@router.get("/org/leads", dependencies=[Depends(require_page("leads"))])
async def list_leads(ctx: Annotated[OrgContext, Depends(require("conversation", "read"))],
                     limit: Annotated[int, Query(ge=1, le=500)] = 300) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""
            select l.id, l.source, l.stage, l.qualification, l.owner_automation, l.touches, l.last_touch_at, l.created_at, l.updated_at,
                   k.name, k.email, k.phone_e164 as phone, l.conversation_id
            from app.leads l join app.contacts k on k.id = l.contact_id where k.merged_into is null
            order by l.updated_at desc limit :l"""), {"l": limit})).mappings().all()
        stages = dict((await conn.execute(text("select stage, count(*) from app.leads group by stage"))).all())
    return {"items": [dict(r) for r in rows], "by_stage": stages}


# ---------- reactivation campaigns ----------

@router.post("/org/campaigns/reactivation/import", dependencies=[Depends(require_page("campaigns"))])
async def import_leads(ctx: Annotated[OrgContext, Depends(require("automation", "configure"))],
                       file: Annotated[UploadFile, File()]) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large (max 5 MB)")
    rows = parse_file(data, file.filename or "leads.csv")
    norm = [{k.strip().lower().replace(" ", "_"): (str(v).strip() if v is not None else None) for k, v in r.items()} for r in rows]
    async with tenant_session(ctx.org_id) as conn:
        stats = await import_old_leads(conn, ctx.org_id, norm)
        stats["contacts_merged"] = await dedupe(conn)
        elig = await eligibility(conn)
    return {**stats, "eligible_now": len(elig["eligible"]), "blocked": elig["blocked"]}


@router.get("/org/campaigns", dependencies=[Depends(require_page("campaigns"))])
async def list_campaigns(ctx: Annotated[OrgContext, Depends(require("automation", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""
            select c.id, c.kind, c.name, c.status, c.per_hour, c.stats, c.created_at,
                   count(e.*) filter (where e.status = 'active') as active,
                   count(e.*) filter (where e.last_step >= 0) as contacted,
                   count(e.*) filter (where e.stop_reason = 'booked' or l.stage = 'booked') as booked,
                   count(e.*) filter (where l.stage = 'engaged') as replied
            from app.campaigns c left join app.sequence_enrollments e on e.sequence_id = c.sequence_id and e.created_at >= c.created_at
            left join app.leads l on l.id = e.subject_id
            where c.kind = 'reactivation'
            group by c.id order by c.created_at desc"""))).mappings().all()
        elig = await eligibility(conn)
    return {"items": [dict(r) for r in rows], "eligible_now": len(elig["eligible"]), "blocked": elig["blocked"]}


class CampaignStart(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    per_hour: Annotated[int, Field(ge=1, le=200)] = 20


@router.post("/org/campaigns/reactivation", status_code=201, dependencies=[Depends(require_page("campaigns"))])
async def start_reactivation(body: CampaignStart, request: Request,
                             ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        status = (await conn.execute(text("select status from app.automation_instances where template_key = 'lead_reactivation'"))).scalar_one_or_none()
        if status not in ("live", "approval_mode"):
            raise HTTPException(409, "Lead reactivation isn't switched on for this business")
        result = await start_campaign(conn, ctx.org_id, body.name, body.per_hour)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="campaign.started", metadata={"name": body.name, "enrolled": result["enrolled"]}, ip=client_ip(request))
    return result


# ---------- lead forms (speed-to-lead) ----------

@router.get("/org/lead-sources", dependencies=[Depends(require_page("lead_forms"))])
async def list_sources(ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("select id, name, key, created_at from app.lead_sources order by created_at"))).mappings().all()
    base = settings.api_public_url.rstrip("/")
    return {"items": [dict(r) | {"url": f"{base}/hooks/leads/{r['key']}"} for r in rows]}


class SourceCreate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=60)]


@router.post("/org/lead-sources", status_code=201, dependencies=[Depends(require_page("lead_forms"))])
async def add_source(body: SourceCreate, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        s = await create_source(conn, ctx.org_id, body.name)
    return s | {"url": f"{settings.api_public_url.rstrip('/')}/hooks/leads/{s['key']}"}


@router.post("/hooks/leads/{key}", status_code=201)
async def lead_hook(key: str, request: Request) -> dict:
    """Public endpoint for website forms and ad-lead integrations. Accepts JSON or form posts."""
    async with system_session() as conn:
        src = (await conn.execute(text("select org_id, name from app.lead_sources where key = :k"), {"k": key})).first()
    if not src:
        raise HTTPException(404, "unknown form")
    ctype = request.headers.get("content-type", "")
    raw = await request.json() if "json" in ctype else dict(await request.form())
    data = {k: str(v)[:2000] for k, v in raw.items() if k in ("name", "phone", "email", "message", "whatsapp_optin", "utm_source")}
    if not (data.get("phone") or data.get("email")):
        raise HTTPException(422, "phone or email is required")
    async with tenant_session(src.org_id) as conn:
        lead_id = await capture(conn, src.org_id, src.name, data)
    return {"ok": True, "lead_id": lead_id}


# ---------- payment gateways ----------

class RazorpayCreds(BaseModel):
    key_id: Annotated[str, Field(pattern=r"^rzp_(test|live)_\w+$")]
    key_secret: Annotated[str, Field(min_length=8, max_length=200)]
    webhook_secret: Annotated[str, Field(min_length=8, max_length=200)]


@router.post("/org/connections/razorpay", status_code=201, dependencies=[Depends(require_connection("gateways"))])
async def connect_razorpay(body: RazorpayCreds, ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    async with client() as c:
        r = await c.get("https://api.razorpay.com/v1/payment_links?count=1", auth=(body.key_id, body.key_secret))
    if r.status_code == 401:
        raise HTTPException(422, "Razorpay rejected these keys")
    cid = await save_connection(ctx.org_id, provider="razorpay", account_ref=body.key_id, display_name=body.key_id,
                                secret=body.model_dump(), connected_by=ctx.principal.user_id)
    return {"connected": True, "webhook_url": f"{settings.api_public_url.rstrip('/')}/webhooks/razorpay/{cid}",
            "events": ["payment.captured", "payment_link.paid"]}


class StripeCreds(BaseModel):
    webhook_secret: Annotated[str, Field(pattern=r"^whsec_\w+$")]
    secret_key: Annotated[str | None, Field(pattern=r"^(sk|rk)_(live|test)_\w+$")] = None  # optional: payment links in reminders
    account_label: Annotated[str, Field(min_length=2, max_length=80)] = "Stripe"


@router.post("/org/connections/stripe", status_code=201, dependencies=[Depends(require_connection("gateways"))])
async def connect_stripe(body: StripeCreds, ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    cid = await save_connection(ctx.org_id, provider="stripe", account_ref=body.account_label, display_name=body.account_label,
                                secret={"webhook_secret": body.webhook_secret, **({"secret_key": body.secret_key} if body.secret_key else {})},
                                connected_by=ctx.principal.user_id)
    return {"connected": True, "webhook_url": f"{settings.api_public_url.rstrip('/')}/webhooks/stripe/{cid}",
            "events": ["checkout.session.completed", "payment_intent.succeeded"]}


def _json(v) -> str:
    return json.dumps(v, default=str)
