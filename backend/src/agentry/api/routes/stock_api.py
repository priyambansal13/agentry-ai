"""Stock shelf scanner in the portal (ROADMAP-V3 B2). Anyone who works the business (conversation:act) scans and applies."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import stock as st
from agentry.automations.support_desk import table_rows
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/stock", dependencies=[Depends(require_page("stock"))])
Reader = Annotated[OrgContext, Depends(require("dashboard", "read"))]
Worker = Annotated[OrgContext, Depends(require("conversation", "act"))]


async def _cfg(conn) -> dict:
    row = (await conn.execute(text("select config from app.automation_instances where template_key = 'stock_scanner'"))).scalar_one_or_none()
    return st.StockConfig(**(row or {})).model_dump()


@router.get("")
async def stock(ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        items = (await conn.execute(text("select id::text, name, unit, count, counted_at, reorder_at, reorder_qty, supplier, supplier_phone from app.stock_items order by name"))).mappings().all()
        scans = (await conn.execute(text("select id::text, area, items, status, created_at from app.stock_scans order by created_at desc limit 20"))).mappings().all()
        cfg = await _cfg(conn)
        orders = await st.reorder(conn, ctx.org_id, cfg["business_signoff"])
    num = lambda v: float(v) if v is not None else None
    return {"items": [dict(i) | {k: num(i[k]) for k in ("count", "reorder_at", "reorder_qty")} for i in items], "scans": [dict(s) for s in scans],
            "reorder": orders, "confirm_below": cfg["confirm_below"], "can_work": ctx.can("conversation", "act")}


@router.post("/scan", status_code=201)
async def scan(ctx: Worker, photo: Annotated[UploadFile, File()], area: Annotated[str | None, Form(max_length=80)] = None) -> dict:
    data = await photo.read()
    try:
        return await st.scan(ctx.org_id, data, photo.content_type or "", photo.filename, area, ctx.principal.user_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class Count(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    count: Annotated[float, Field(ge=0, le=1e7)]
    unit: str | None = None
    item_id: str | None = None


class ApplyIn(BaseModel):
    counts: Annotated[list[Count], Field(max_length=300)]
    add_new: bool = True


@router.post("/scans/{sid}/apply")
async def apply(sid: str, body: ApplyIn, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await st.apply(conn, ctx.org_id, sid, [c.model_dump() for c in body.counts], body.add_new)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e


@router.post("/items/import")
async def import_items(ctx: Worker, file: Annotated[UploadFile, File()]) -> dict:
    try:
        async with tenant_session(ctx.org_id) as conn:
            return await st.import_items(conn, ctx.org_id, table_rows(await file.read(), file.filename))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
