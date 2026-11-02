"""Festival campaigns in the portal (ROADMAP-V3 B3)."""
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import festivals as fv
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/festivals", dependencies=[Depends(require_page("festivals"))])
Reader = Annotated[OrgContext, Depends(require("dashboard", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]


@router.get("")
async def overview(ctx: Reader) -> dict:
    today = datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        _s, cfg = await fv.settings_of(conn)
        plans = (await conn.execute(text("select id::text, festival, name, on_date, plan, checks, status from app.festival_plans order by on_date desc limit 40"))).mappings().all()
    return {"upcoming": [f | {"date": str(f["date"])} for f in fv.upcoming({**cfg, "festivals": list(fv.FESTIVALS)}, today, 120)],
            "chosen": cfg["festivals"], "plans": [dict(p) for p in plans], "can_edit": ctx.can("automation", "configure")}


class PlanIn(BaseModel):
    festival: str
    on_date: date


@router.post("/plans", status_code=201)
async def plan(body: PlanIn, ctx: Editor) -> dict:
    if body.festival not in fv.FESTIVALS:
        raise HTTPException(422, "unknown festival")
    try:
        return await fv.make_plan(ctx.org_id, body.festival, body.on_date)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class StatusIn(BaseModel):
    status: Literal["draft", "approved", "done", "skipped"]


@router.patch("/plans/{pid}")
async def set_status(pid: str, body: StatusIn, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        p = (await conn.execute(text("select status from app.festival_plans where id = cast(:i as uuid)"), {"i": pid})).scalar_one_or_none()
        if p is None:
            raise HTTPException(404, "plan not found")
        if body.status == "approved" and p == "needs_attention":
            raise HTTPException(409, "fix the flagged wording first (make a new plan, or set your offer in settings)")
        await conn.execute(text("update app.festival_plans set status = :s, updated_at = now() where id = cast(:i as uuid)"), {"s": body.status, "i": pid})
    return {"id": pid, "status": body.status}
