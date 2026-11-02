"""Support desk in the portal (ROADMAP-V3 A2): tickets with SLAs, the order sheet.

Who: anyone who works conversations (owner, manager, front desk) handles tickets; viewers read.
"""
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import support_desk as sd
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/tickets", dependencies=[Depends(require_page("tickets"))])
Reader = Annotated[OrgContext, Depends(require("conversation", "read"))]
Worker = Annotated[OrgContext, Depends(require("conversation", "act"))]
COLS = """t.id::text, t.number, t.subject, t.summary, t.category, t.priority, t.status, t.assignee, t.order_ref, t.channel, t.source,
    t.sla_due_at, t.first_response_at, t.resolved_at, t.breached_at, t.csat, t.created_at, t.updated_at, t.conversation_id::text, k.name as customer"""


@router.get("")
async def tickets(ctx: Reader, status: str | None = None, mine: bool = False, q: str | None = None) -> dict:
    where, p = ["true"], {}
    if status == "active":
        where.append("t.status in ('open','waiting_customer')")
    elif status:
        where.append("t.status = :s")
        p["s"] = status
    if mine:
        where.append("t.assignee = :u")
        p["u"] = ctx.principal.user_id
    if q:
        where.append("(t.subject ilike :q or t.order_ref ilike :q or k.name ilike :q or t.number::text = :n)")
        p |= {"q": f"%{q}%", "n": q.strip().lstrip("#")}
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text(f"""select {COLS} from app.tickets t left join app.contacts k on k.id = t.contact_id
            where {' and '.join(where)} order by (t.status in ('resolved','closed')), array_position(array['urgent','high','normal','low'], t.priority),
            t.sla_due_at nulls last limit 500"""), p)).mappings().all()
        stats = (await conn.execute(text("""select count(*) filter (where status in ('open','waiting_customer')) as active,
            count(*) filter (where breached_at is not null and status in ('open','waiting_customer')) as breached,
            count(*) filter (where resolved_at > now() - interval '30 days') as resolved_30d, round(avg(csat)::numeric, 1) as csat,
            round(extract(epoch from percentile_cont(0.5) within group (order by first_response_at - created_at)) / 60) as median_first_reply_min
            from app.tickets"""))).mappings().one()
        team = (await conn.execute(text("""select u.id, u.name from auth.member m join auth."user" u on u.id = m."userId"
            where m."organizationId" = :o order by u.name"""), {"o": ctx.org_id})).mappings().all()
        orders = (await conn.execute(text("select count(*), max(updated_at) from app.orders"))).one()
    now = datetime.now(UTC)
    stats = {k: (float(v) if v is not None and k in ("csat", "median_first_reply_min") else v) for k, v in dict(stats).items()}
    return {"items": [dict(r) | {"overdue": bool(r["sla_due_at"] and r["sla_due_at"] < now and r["status"] == "open" and not r["first_response_at"])}
                      for r in rows], "stats": stats, "team": [dict(t) for t in team], "can_work": ctx.can("conversation", "act"),
            "orders": {"count": orders[0], "updated": orders[1]}}


@router.get("/{tid}")
async def ticket(tid: str, ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        t = (await conn.execute(text(f"""select {COLS}, t.notes from app.tickets t left join app.contacts k on k.id = t.contact_id
            where t.id = cast(:i as uuid)"""), {"i": tid})).mappings().first()
        if not t:
            raise HTTPException(404, "ticket not found")
        msgs = (await conn.execute(text("""select direction, author, body, created_at from app.messages where conversation_id = cast(:c as uuid)
            order by created_at desc limit 30"""), {"c": t["conversation_id"]})).mappings().all() if t["conversation_id"] else []
        order = (await conn.execute(text("select * from app.orders where upper(order_ref) = upper(:r)"), {"r": t["order_ref"]})).mappings().first() \
            if t["order_ref"] else None
    return dict(t) | {"messages": [dict(m) for m in reversed(msgs)], "order": {k: v for k, v in dict(order).items() if k not in ("org_id", "id")} if order else None}


class TicketIn(BaseModel):
    subject: Annotated[str, Field(min_length=3, max_length=200)]
    summary: Annotated[str | None, Field(max_length=4000)] = None
    category: Literal["order", "delivery", "refund", "product", "complaint", "billing", "technical", "other"] = "other"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    conversation_id: str | None = None
    order_ref: Annotated[str | None, Field(max_length=60)] = None
    assignee: str | None = None


@router.post("", status_code=201)
async def create(body: TicketIn, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        return await sd.open_ticket(conn, ctx.org_id, subject=body.subject, summary=body.summary, category=body.category, priority=body.priority,
                                    conversation_id=body.conversation_id, order_ref=body.order_ref, source="person", assignee=body.assignee)


class TicketEdit(BaseModel):
    status: Literal["open", "waiting_customer", "resolved", "closed"] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    category: Literal["order", "delivery", "refund", "product", "complaint", "billing", "technical", "other"] | None = None
    assignee: str | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None


@router.patch("/{tid}")
async def edit(tid: str, body: TicketEdit, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            row = await sd.update_ticket(conn, ctx.org_id, tid, body.model_dump(exclude_unset=True), user_id=ctx.principal.user_id,
                                         actor_type=ctx.actor_type)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    return {"id": tid, "status": row["status"]}


@router.post("/orders/import")
async def import_orders(ctx: Worker, file: Annotated[UploadFile, File()]) -> dict:
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(422, "the sheet can be up to 10 MB")
    try:
        rows = sd.table_rows(data, file.filename)
        async with tenant_session(ctx.org_id) as conn:
            return await sd.import_orders(conn, ctx.org_id, rows)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
