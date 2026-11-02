"""Renewals & repeat business in the portal (ROADMAP-V3 A4)."""
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import renewals as rn
from agentry.automations.support_desk import table_rows
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/renewals", dependencies=[Depends(require_page("renewals"))])
Reader = Annotated[OrgContext, Depends(require("conversation", "read"))]
Worker = Annotated[OrgContext, Depends(require("conversation", "act"))]


@router.get("")
async def renewals(ctx: Reader, status: str | None = None) -> dict:
    today = datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id::text, customer, phone, email, item, due_on, amount, every, status, reminded, winback_sent, payment_link,
            renewals from app.renewals where (cast(:s as text) is null or status = :s) order by status <> 'upcoming', due_on limit 1000"""), {"s": status})).mappings().all()
        stats = (await conn.execute(text("""select count(*) filter (where status = 'upcoming' and due_on <= :m) as due_30,
            coalesce(sum(amount) filter (where status = 'upcoming' and due_on <= :m), 0) as due_30_value, count(*) filter (where status = 'lapsed') as lapsed,
            coalesce(sum(renewals), 0) as renewed from app.renewals"""), {"m": today + timedelta(days=30)})).mappings().one()
    return {"items": [dict(r) | {"days_left": (r["due_on"] - today).days} for r in rows], "stats": {k: float(v) for k, v in stats.items()},
            "can_work": ctx.can("conversation", "act")}


class RenewalIn(BaseModel):
    customer: Annotated[str, Field(min_length=2, max_length=120)]
    phone: Annotated[str | None, Field(max_length=20)] = None
    email: Annotated[str | None, Field(max_length=200)] = None
    item: Annotated[str, Field(min_length=2, max_length=120)]
    due_on: date
    amount: Annotated[float | None, Field(ge=0)] = None
    every: Literal["once", "monthly", "quarterly", "half_yearly", "yearly"] = "yearly"
    birthday: Annotated[str | None, Field(pattern=r"^\d{2}-\d{2}$")] = None


@router.post("", status_code=201)
async def add(body: RenewalIn, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        return {"id": await rn.add(conn, ctx.org_id, body.model_dump())}


@router.post("/import")
async def import_sheet(ctx: Worker, file: Annotated[UploadFile, File()]) -> dict:
    try:
        async with tenant_session(ctx.org_id) as conn:
            return await rn.import_sheet(conn, ctx.org_id, table_rows(await file.read(), file.filename))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class Mark(BaseModel):
    action: Literal["renewed", "cancelled"]


@router.post("/{rid}/mark")
async def mark(rid: str, body: Mark, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await rn.mark(conn, ctx.org_id, rid, body.action, ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
