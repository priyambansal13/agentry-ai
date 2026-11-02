"""Catalogue & quotes in the portal (ROADMAP-V3 A3): the product catalogue, quotes, sending, won / lost.

Who: owners, managers and front desk make and send quotes (conversation:act); finance and viewers read (invoice:read).
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, current_org
from agentry.automations import catalog_quotes as cq
from agentry.automations.content import brand
from agentry.automations.support_desk import table_rows
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/quotes", dependencies=[Depends(require_page("quotes"))])


def _read(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
    if not (ctx.can("conversation", "read") or ctx.can("invoice", "read")):
        raise HTTPException(403, "quotes are for the team")
    return ctx


Reader = Annotated[OrgContext, Depends(_read)]


def _act(ctx: OrgContext) -> None:
    if not ctx.can("conversation", "act"):
        raise HTTPException(403, "only people who talk to customers send quotes")


@router.get("")
async def quotes(ctx: Reader, status: str | None = None) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id::text, number, customer, phone, email, total, currency, status, source, valid_until, sent_at,
            followups, created_at from app.quotes where (cast(:s as text) is null or status = :s) order by created_at desc limit 300"""), {"s": status})).mappings().all()
        stats = (await conn.execute(text("""select count(*) filter (where status = 'sent') as open, count(*) filter (where status = 'won') as won,
            count(*) filter (where status = 'lost') as lost, coalesce(sum(total) filter (where status = 'won'), 0) as won_value,
            coalesce(sum(total) filter (where status = 'sent'), 0) as open_value from app.quotes where created_at > now() - interval '90 days'"""))).mappings().one()
        products = (await conn.execute(text("select count(*) from app.products where active"))).scalar_one()
    return {"items": [dict(r) for r in rows], "stats": {k: float(v) for k, v in stats.items()}, "products": products,
            "can_act": ctx.can("conversation", "act")}


@router.get("/products")
async def products(ctx: Reader, q: str | None = None) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select code, name, category, unit, price, gst_rate, stock, min_qty from app.products where active
            and (cast(:q as text) is null or name ilike :p or code ilike :p or category ilike :p) order by category nulls last, name limit 1000"""),
            {"q": q, "p": f"%{q}%"})).mappings().all()
    return {"items": [{k: (float(v) if k in ("price", "gst_rate", "stock", "min_qty") and v is not None else v) for k, v in r.items()} for r in rows]}


@router.post("/products/import")
async def import_products(ctx: Reader, file: Annotated[UploadFile, File()]) -> dict:
    _act(ctx)
    data = await file.read()
    try:
        async with tenant_session(ctx.org_id) as conn:
            return await cq.import_products(conn, ctx.org_id, table_rows(data, file.filename))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class Line(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=40)]
    qty: Annotated[float, Field(gt=0, le=1e7)]


class QuoteIn(BaseModel):
    customer: Annotated[str, Field(min_length=2, max_length=120)]
    phone: Annotated[str | None, Field(max_length=20)] = None
    email: Annotated[str | None, Field(max_length=200)] = None
    items: Annotated[list[Line], Field(min_length=1, max_length=60)]
    note: Annotated[str | None, Field(max_length=500)] = None
    send: bool = False


@router.post("", status_code=201)
async def create(body: QuoteIn, ctx: Reader) -> dict:
    _act(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            q = await cq.create_quote(conn, ctx.org_id, items=[i.model_dump() for i in body.items], customer=body.customer, phone=body.phone,
                                      email=body.email, note=body.note, user_id=ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    if body.send:
        q["sent"] = (await cq.send_quote(ctx.org_id, q["id"], user_id=ctx.principal.user_id))["status"]
    return q


async def _quote(conn, qid: str) -> dict:
    q = (await conn.execute(text("select * from app.quotes where id = cast(:i as uuid)"), {"i": qid})).mappings().first()
    if not q:
        raise HTTPException(404, "quote not found")
    return dict(q)


@router.get("/{qid}")
async def quote(qid: str, ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        q = await _quote(conn, qid)
    return {k: v for k, v in q.items() if k not in ("org_id", "token")} | {"id": qid, "link": cq.public_link(q["token"])}


@router.get("/{qid}/pdf")
async def quote_pdf(qid: str, ctx: Reader) -> Response:
    async with tenant_session(ctx.org_id) as conn:
        q = await _quote(conn, qid)
        _s, cfg = await cq.settings_of(conn)
        kit = await brand.get_kit(conn, ctx.org_id)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": ctx.org_id})).scalar_one_or_none() or ""
    return Response(cq.pdf(q, business, cfg, kit), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{q["number"]}.pdf"'})


@router.post("/{qid}/send")
async def send(qid: str, ctx: Reader) -> dict:
    _act(ctx)
    return await cq.send_quote(ctx.org_id, qid, user_id=ctx.principal.user_id)


class Outcome(BaseModel):
    outcome: Literal["won", "lost"]


@router.post("/{qid}/outcome")
async def outcome(qid: str, body: Outcome, ctx: Reader) -> dict:
    _act(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            await cq.set_outcome(conn, ctx.org_id, qid, body.outcome, ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    return {"id": qid, "status": body.outcome}
