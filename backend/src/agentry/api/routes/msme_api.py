"""MSME 45-day recovery (automations/invoice_follow_up/msme.py) on the Invoices page: the registration, what's past the legal
due date and the interest on it, each customer's written credit days, and the MSME Samadhaan claim draft."""
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, require
from agentry.automations.invoice_follow_up import msme
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/invoices/msme", dependencies=[Depends(require_page("invoices"))])
Reader = Annotated[OrgContext, Depends(require("invoice", "read"))]
Actor = Annotated[OrgContext, Depends(require("invoice", "act"))]


@router.get("")
async def overview(ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        return await msme.overview(conn)


class MsmeIn(BaseModel):
    enabled: bool
    udyam: Annotated[str | None, Field(pattern=r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")] = None
    category: Literal["micro", "small", "medium"] | None = None


@router.put("")
async def save(body: MsmeIn, ctx: Actor) -> dict:
    if body.enabled and body.category not in msme.CATEGORIES:
        raise HTTPException(422, "the MSMED Act's payment rules cover micro and small enterprises (not medium)")
    if body.enabled and not body.udyam:
        raise HTTPException(422, "add your Udyam registration number (UDYAM-XX-00-0000000)")
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("update app.org_settings set msme = cast(:m as jsonb)"), {"m": json.dumps(body.model_dump())})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="invoices.msme_settings",
                           metadata={"enabled": body.enabled, "category": body.category})
        return await msme.overview(conn)


class CreditIn(BaseModel):
    credit_days: Annotated[int | None, Field(ge=1, le=365)] = None  # None: no written agreement


@router.put("/customers/{contact_id}")
async def credit_days(contact_id: str, body: CreditIn, ctx: Actor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.contacts set attributes = case when cast(:d as int) is null then attributes - 'credit_days'
            else attributes || jsonb_build_object('credit_days', cast(:d as int)) end where id = cast(:c as uuid)"""),
            {"d": body.credit_days, "c": contact_id})).rowcount
    if not n:
        raise HTTPException(404, "customer not found")
    days, written = msme.credit_days({"credit_days": body.credit_days} if body.credit_days else {})
    return {"credit_days": days, "written": written}


@router.get("/claim/{contact_id}", response_class=PlainTextResponse)
async def claim(contact_id: str, ctx: Reader) -> str:
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await msme.claim_draft(conn, contact_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
